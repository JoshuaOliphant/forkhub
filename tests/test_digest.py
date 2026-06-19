# ABOUTME: Tests for the DigestService that generates and delivers digest notifications.
# ABOUTME: Uses a StubNotificationBackend for deterministic delivery testing.

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from forkhub.models import Digest, DigestConfig
from forkhub.services.digest import DigestService
from tests.stubs import (
    StubNotificationBackend,
    make_fork,
    make_signal,
    make_tracked_repo,
)

if TYPE_CHECKING:
    from forkhub.database import Database

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pydantic_digest_config(**overrides: object) -> DigestConfig:
    """Create a DigestConfig Pydantic model with sensible defaults.

    The shared make_digest_config returns a dict for DB insertion.
    This helper returns a DigestConfig model for service-layer tests.
    """
    kwargs: dict[str, object] = {
        "tracked_repo_id": None,
        "frequency": "weekly",
        "day_of_week": 1,
        "time_of_day": "09:00",
        "min_significance": 5,
        "categories": None,
        "file_patterns": None,
        "backends": ["console"],
    }
    kwargs.update(overrides)
    return DigestConfig(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def repo_in_db(db: Database) -> dict:
    repo = make_tracked_repo()
    await db.insert_tracked_repo(repo)
    return repo


@pytest.fixture
async def fork_in_db(db: Database, repo_in_db: dict) -> dict:
    fork = make_fork(repo_in_db["id"], github_id=5001, owner="alice", full_name="alice/linux")
    await db.insert_fork(fork)
    return fork


@pytest.fixture
def stub_backend() -> StubNotificationBackend:
    return StubNotificationBackend()


@pytest.fixture
def failing_backend() -> StubNotificationBackend:
    return StubNotificationBackend(name="failing", should_fail=True)


# ---------------------------------------------------------------------------
# File pattern matching tests
# ---------------------------------------------------------------------------


class TestFilePatternMatching:
    def test_edge_cases(self):
        """Empty files returns false; empty patterns returns true (include all)."""
        svc = DigestService.__new__(DigestService)
        assert svc._matches_file_patterns([], ["src/*.py"]) is False
        assert svc._matches_file_patterns(["src/gpu.py"], []) is True


# ---------------------------------------------------------------------------
# Digest generation tests
# ---------------------------------------------------------------------------


class TestDigestGeneration:
    async def test_significance_and_category_filtering(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
        repo_in_db: dict,
        fork_in_db: dict,
    ):
        """Digest filters by significance threshold and category."""
        # Significance filtering: low significance excluded
        sig_low = make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            significance=2,
            summary="Minor tweak",
        )
        sig_high = make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            significance=8,
            summary="Major feature",
        )
        await db.insert_signal(sig_low)
        await db.insert_signal(sig_high)

        config = _make_pydantic_digest_config(tracked_repo_id=repo_in_db["id"], min_significance=5)
        svc = DigestService(db, [stub_backend])
        digest = await svc.generate_digest(config)

        assert len(digest.signal_ids) == 1
        assert digest.signal_ids[0] == sig_high["id"]

        # Category filtering: only matching categories included
        sig_feature = make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            category="feature",
            summary="Feature change",
        )
        sig_fix = make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            category="fix",
            summary="Bug fix",
        )
        await db.insert_signal(sig_feature)
        await db.insert_signal(sig_fix)

        config = _make_pydantic_digest_config(
            tracked_repo_id=repo_in_db["id"],
            categories=["fix"],
            min_significance=1,
        )
        digest = await svc.generate_digest(config)

        # Should have the fix signal plus the sig_high from above (which is feature, not fix)
        # Actually, category filter only includes "fix" category, so only sig_fix matches
        fix_ids = [sid for sid in digest.signal_ids if sid == sig_fix["id"]]
        assert len(fix_ids) == 1

    async def test_file_pattern_filtering(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
        repo_in_db: dict,
        fork_in_db: dict,
    ):
        """Only signals with files matching configured patterns should be included."""
        sig_src = make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            summary="Source change",
            files_involved=json.dumps(["src/gpu.py"]),
        )
        sig_docs = make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            summary="Docs change",
            files_involved=json.dumps(["docs/readme.md"]),
        )
        await db.insert_signal(sig_src)
        await db.insert_signal(sig_docs)

        config = _make_pydantic_digest_config(
            tracked_repo_id=repo_in_db["id"],
            file_patterns=["src/*.py"],
            min_significance=1,
        )
        svc = DigestService(db, [stub_backend])
        digest = await svc.generate_digest(config)

        assert len(digest.signal_ids) == 1
        assert digest.signal_ids[0] == sig_src["id"]

    async def test_header_shows_full_name_not_repo_id(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
        repo_in_db: dict,
        fork_in_db: dict,
    ):
        """The repository section header uses the human full_name, not the raw repo UUID."""
        signal = make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            significance=8,
            summary="Major feature",
        )
        await db.insert_signal(signal)

        config = _make_pydantic_digest_config(
            tracked_repo_id=repo_in_db["id"],
            min_significance=5,
        )
        svc = DigestService(db, [stub_backend])
        digest = await svc.generate_digest(config)

        assert f"## Repository {repo_in_db['full_name']}" in digest.body
        assert repo_in_db["id"] not in digest.body

    async def test_groups_multiple_repos_with_single_batch_lookup(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
    ):
        """A global digest spanning several repos resolves all headers via one batch query."""
        repo_a = make_tracked_repo(owner="alice", name="proj", full_name="alice/proj", github_id=1)
        repo_b = make_tracked_repo(owner="bob", name="proj", full_name="bob/proj", github_id=2)
        await db.insert_tracked_repo(repo_a)
        await db.insert_tracked_repo(repo_b)
        fork_a = make_fork(repo_a["id"], github_id=9001, owner="ca", full_name="ca/proj")
        fork_b = make_fork(repo_b["id"], github_id=9002, owner="cb", full_name="cb/proj")
        await db.insert_fork(fork_a)
        await db.insert_fork(fork_b)
        await db.insert_signal(
            make_signal(fork_a["id"], repo_a["id"], significance=8, summary="A change")
        )
        await db.insert_signal(
            make_signal(fork_b["id"], repo_b["id"], significance=8, summary="B change")
        )

        calls: list[list[str]] = []
        original = db.get_tracked_repos

        async def spy(ids: list[str]) -> dict:
            calls.append(list(ids))
            return await original(ids)

        db.get_tracked_repos = spy  # type: ignore[method-assign]

        config = _make_pydantic_digest_config(tracked_repo_id=None, min_significance=5)
        svc = DigestService(db, [stub_backend])
        digest = await svc.generate_digest(config)

        assert "## Repository alice/proj" in digest.body
        assert "## Repository bob/proj" in digest.body
        # The N+1 fix means exactly one batch lookup, regardless of repo count.
        assert len(calls) == 1
        assert set(calls[0]) == {repo_a["id"], repo_b["id"]}

    async def test_raises_when_repo_missing_violates_fk_invariant(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
        repo_in_db: dict,
        fork_in_db: dict,
    ):
        """If a signal's repo is unexpectedly absent, generation raises (survives python -O)."""
        signal = make_signal(fork_in_db["id"], repo_in_db["id"], significance=8, summary="Orphaned")
        await db.insert_signal(signal)

        async def empty_batch(ids: list[str]) -> dict:
            return {}

        db.get_tracked_repos = empty_batch  # type: ignore[method-assign]

        config = _make_pydantic_digest_config(tracked_repo_id=repo_in_db["id"], min_significance=5)
        svc = DigestService(db, [stub_backend])
        with pytest.raises(LookupError, match=repo_in_db["id"]):
            await svc.generate_digest(config)


# ---------------------------------------------------------------------------
# generate_and_deliver convenience method tests
# ---------------------------------------------------------------------------


class TestGenerateAndDeliver:
    async def test_default_config_used_when_none(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
        repo_in_db: dict,
        fork_in_db: dict,
    ):
        """When config is None, a sensible default should be used."""
        signal = make_signal(fork_in_db["id"], repo_in_db["id"], significance=8)
        await db.insert_signal(signal)

        svc = DigestService(db, [stub_backend])
        digest, results = await svc.generate_and_deliver(config=None)

        assert isinstance(digest, Digest)
        assert len(results) == 1

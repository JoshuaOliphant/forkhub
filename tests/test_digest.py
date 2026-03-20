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

# ABOUTME: Tests for the DigestService that generates and delivers digest notifications.
# ABOUTME: Uses a StubNotificationBackend for deterministic delivery testing.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from forkhub.database import Database
from forkhub.models import DeliveryResult, Digest, DigestConfig
from forkhub.services.digest import DigestService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uuid() -> str:
    return str(uuid4())


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _days_ago_iso(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _make_tracked_repo(**overrides) -> dict:
    defaults = {
        "id": _uuid(),
        "github_id": 123456,
        "owner": "torvalds",
        "name": "linux",
        "full_name": "torvalds/linux",
        "tracking_mode": "active",
        "default_branch": "main",
        "description": "Linux kernel source tree",
        "fork_depth": 1,
        "excluded": False,
        "webhook_id": None,
        "last_synced_at": None,
        "created_at": _now_iso(),
    }
    defaults.update(overrides)
    return defaults


def _make_fork(tracked_repo_id: str, **overrides) -> dict:
    defaults = {
        "id": _uuid(),
        "tracked_repo_id": tracked_repo_id,
        "github_id": 789012,
        "owner": "gregkh",
        "full_name": "gregkh/linux",
        "default_branch": "main",
        "description": "Greg KH's linux fork",
        "vitality": "active",
        "stars": 42,
        "stars_previous": 40,
        "parent_fork_id": None,
        "depth": 1,
        "last_pushed_at": _now_iso(),
        "commits_ahead": 10,
        "commits_behind": 5,
        "head_sha": "abc123def456",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    defaults.update(overrides)
    return defaults


def _make_signal(fork_id: str, tracked_repo_id: str, **overrides) -> dict:
    defaults = {
        "id": _uuid(),
        "fork_id": fork_id,
        "tracked_repo_id": tracked_repo_id,
        "category": "feature",
        "summary": "Added GPU support",
        "detail": "Implements CUDA acceleration for training loop",
        "files_involved": json.dumps(["src/gpu.py", "src/train.py"]),
        "significance": 7,
        "embedding": None,
        "is_upstream": False,
        "release_tag": None,
        "created_at": _now_iso(),
    }
    defaults.update(overrides)
    return defaults


def _make_digest_config(**overrides) -> DigestConfig:
    """Create a DigestConfig Pydantic model with sensible defaults."""
    kwargs = {
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
    return DigestConfig(**kwargs)


# ---------------------------------------------------------------------------
# Stub NotificationBackend
# ---------------------------------------------------------------------------


class StubNotificationBackend:
    """Deterministic notification backend for testing.

    Records all delivered digests and can be configured to succeed or fail.
    """

    def __init__(self, name: str = "stub", should_fail: bool = False) -> None:
        self._name = name
        self._should_fail = should_fail
        self.delivered: list[Digest] = []

    async def deliver(self, digest: Digest) -> DeliveryResult:
        self.delivered.append(digest)
        if self._should_fail:
            return DeliveryResult(
                backend_name=self._name,
                success=False,
                error="Simulated delivery failure",
                delivered_at=datetime.now(UTC),
            )
        return DeliveryResult(
            backend_name=self._name,
            success=True,
            error=None,
            delivered_at=datetime.now(UTC),
        )

    def backend_name(self) -> str:
        return self._name


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    """Provide an in-memory Database connected and schema-created."""
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def repo_in_db(db: Database) -> dict:
    repo = _make_tracked_repo()
    await db.insert_tracked_repo(repo)
    return repo


@pytest.fixture
async def fork_in_db(db: Database, repo_in_db: dict) -> dict:
    fork = _make_fork(repo_in_db["id"], github_id=5001, owner="alice", full_name="alice/linux")
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
    def test_exact_file_match(self):
        svc = DigestService.__new__(DigestService)
        assert svc._matches_file_patterns(["src/gpu.py"], ["src/gpu.py"]) is True

    def test_glob_star_match(self):
        svc = DigestService.__new__(DigestService)
        assert svc._matches_file_patterns(["src/gpu.py"], ["src/*.py"]) is True

    def test_glob_double_star_match(self):
        svc = DigestService.__new__(DigestService)
        assert svc._matches_file_patterns(["src/deep/nested/gpu.py"], ["**/*.py"]) is True

    def test_no_match(self):
        svc = DigestService.__new__(DigestService)
        assert svc._matches_file_patterns(["src/gpu.py"], ["docs/*.md"]) is False

    def test_empty_files_returns_false(self):
        svc = DigestService.__new__(DigestService)
        assert svc._matches_file_patterns([], ["src/*.py"]) is False

    def test_empty_patterns_returns_true(self):
        """No patterns means no filtering (include all)."""
        svc = DigestService.__new__(DigestService)
        assert svc._matches_file_patterns(["src/gpu.py"], []) is True

    def test_multiple_patterns_any_match(self):
        svc = DigestService.__new__(DigestService)
        assert svc._matches_file_patterns(["docs/readme.md"], ["src/*.py", "docs/*.md"]) is True

    def test_multiple_files_any_match(self):
        svc = DigestService.__new__(DigestService)
        assert (
            svc._matches_file_patterns(["config.toml", "src/gpu.py"], ["src/*.py"]) is True
        )


# ---------------------------------------------------------------------------
# Digest generation tests
# ---------------------------------------------------------------------------


class TestDigestGeneration:
    async def test_generates_digest_with_signals(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
        repo_in_db: dict,
        fork_in_db: dict,
    ):
        """Digest should include signal summaries in the body."""
        signal = _make_signal(fork_in_db["id"], repo_in_db["id"], significance=7)
        await db.insert_signal(signal)

        config = _make_digest_config(tracked_repo_id=repo_in_db["id"])
        svc = DigestService(db, [stub_backend])
        digest = await svc.generate_digest(config)

        assert isinstance(digest, Digest)
        assert digest.title  # title should not be empty
        assert "GPU" in digest.body or "gpu" in digest.body.lower()
        assert len(digest.signal_ids) == 1

    async def test_significance_filtering(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
        repo_in_db: dict,
        fork_in_db: dict,
    ):
        """Signals below min_significance should be excluded."""
        sig_low = _make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            significance=2,
            summary="Minor tweak",
        )
        sig_high = _make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            significance=8,
            summary="Major feature",
        )
        await db.insert_signal(sig_low)
        await db.insert_signal(sig_high)

        config = _make_digest_config(tracked_repo_id=repo_in_db["id"], min_significance=5)
        svc = DigestService(db, [stub_backend])
        digest = await svc.generate_digest(config)

        assert len(digest.signal_ids) == 1
        assert digest.signal_ids[0] == sig_high["id"]

    async def test_category_filtering(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
        repo_in_db: dict,
        fork_in_db: dict,
    ):
        """Only signals matching configured categories should be included."""
        sig_feature = _make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            category="feature",
            summary="Feature change",
        )
        sig_fix = _make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            category="fix",
            summary="Bug fix",
        )
        await db.insert_signal(sig_feature)
        await db.insert_signal(sig_fix)

        config = _make_digest_config(
            tracked_repo_id=repo_in_db["id"],
            categories=["fix"],
            min_significance=1,
        )
        svc = DigestService(db, [stub_backend])
        digest = await svc.generate_digest(config)

        assert len(digest.signal_ids) == 1
        assert digest.signal_ids[0] == sig_fix["id"]

    async def test_file_pattern_filtering(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
        repo_in_db: dict,
        fork_in_db: dict,
    ):
        """Only signals with files matching configured patterns should be included."""
        sig_src = _make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            summary="Source change",
            files_involved=json.dumps(["src/gpu.py"]),
        )
        sig_docs = _make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            summary="Docs change",
            files_involved=json.dumps(["docs/readme.md"]),
        )
        await db.insert_signal(sig_src)
        await db.insert_signal(sig_docs)

        config = _make_digest_config(
            tracked_repo_id=repo_in_db["id"],
            file_patterns=["src/*.py"],
            min_significance=1,
        )
        svc = DigestService(db, [stub_backend])
        digest = await svc.generate_digest(config)

        assert len(digest.signal_ids) == 1
        assert digest.signal_ids[0] == sig_src["id"]

    async def test_empty_digest_when_no_signals(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
        repo_in_db: dict,
    ):
        """Digest with no matching signals should have empty body and signal_ids."""
        config = _make_digest_config(tracked_repo_id=repo_in_db["id"])
        svc = DigestService(db, [stub_backend])
        digest = await svc.generate_digest(config)

        assert isinstance(digest, Digest)
        assert len(digest.signal_ids) == 0

    async def test_since_parameter_filters_by_time(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
        repo_in_db: dict,
        fork_in_db: dict,
    ):
        """The since parameter should filter signals by creation time."""
        old_signal = _make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            summary="Old change",
            created_at="2020-01-01T00:00:00+00:00",
        )
        recent_signal = _make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            summary="Recent change",
            created_at=_now_iso(),
        )
        await db.insert_signal(old_signal)
        await db.insert_signal(recent_signal)

        config = _make_digest_config(
            tracked_repo_id=repo_in_db["id"],
            min_significance=1,
        )
        svc = DigestService(db, [stub_backend])
        since = datetime(2024, 1, 1, tzinfo=UTC)
        digest = await svc.generate_digest(config, since=since)

        assert len(digest.signal_ids) == 1
        assert digest.signal_ids[0] == recent_signal["id"]

    async def test_digest_saved_to_database(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
        repo_in_db: dict,
        fork_in_db: dict,
    ):
        """Generated digest should be persisted in the database."""
        signal = _make_signal(fork_in_db["id"], repo_in_db["id"], significance=7)
        await db.insert_signal(signal)

        config = _make_digest_config(tracked_repo_id=repo_in_db["id"])
        svc = DigestService(db, [stub_backend])
        digest = await svc.generate_digest(config)

        # Verify digest exists in DB
        cursor = await db._db.execute("SELECT * FROM digests WHERE id = ?", (digest.id,))
        row = await cursor.fetchone()
        assert row is not None
        assert row["title"] == digest.title

    async def test_digest_title_contains_date(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
        repo_in_db: dict,
    ):
        """Digest title should contain the current date."""
        config = _make_digest_config(tracked_repo_id=repo_in_db["id"])
        svc = DigestService(db, [stub_backend])
        digest = await svc.generate_digest(config)

        today = datetime.now(UTC)
        # Title should contain year or month name
        assert str(today.year) in digest.title or today.strftime("%B") in digest.title

    async def test_global_config_queries_all_repos(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
    ):
        """A config with no tracked_repo_id should query signals from all repos."""
        # Create two repos with signals
        repo1 = _make_tracked_repo(github_id=1001, owner="a", name="r1", full_name="a/r1")
        repo2 = _make_tracked_repo(github_id=1002, owner="b", name="r2", full_name="b/r2")
        await db.insert_tracked_repo(repo1)
        await db.insert_tracked_repo(repo2)

        fork1 = _make_fork(repo1["id"], github_id=2001, owner="f1", full_name="f1/r1")
        fork2 = _make_fork(repo2["id"], github_id=2002, owner="f2", full_name="f2/r2")
        await db.insert_fork(fork1)
        await db.insert_fork(fork2)

        sig1 = _make_signal(fork1["id"], repo1["id"], summary="Change in repo 1")
        sig2 = _make_signal(fork2["id"], repo2["id"], summary="Change in repo 2")
        await db.insert_signal(sig1)
        await db.insert_signal(sig2)

        config = _make_digest_config(tracked_repo_id=None, min_significance=1)
        svc = DigestService(db, [stub_backend])
        digest = await svc.generate_digest(config)

        assert len(digest.signal_ids) == 2


# ---------------------------------------------------------------------------
# Delivery tests
# ---------------------------------------------------------------------------


class TestDigestDelivery:
    async def test_deliver_dispatches_to_all_backends(
        self,
        db: Database,
    ):
        """deliver_digest should call deliver on every backend."""
        backend1 = StubNotificationBackend(name="email")
        backend2 = StubNotificationBackend(name="slack")

        svc = DigestService(db, [backend1, backend2])

        digest = Digest(
            title="Test Digest",
            body="Some body text",
            signal_ids=["sig-1"],
        )
        # Save to DB first so deliver_digest can update it
        digest_dict = digest.model_dump()
        digest_dict["created_at"] = digest.created_at.isoformat()
        digest_dict["delivered_at"] = None
        digest_dict["signal_ids"] = json.dumps(digest.signal_ids)
        await db.insert_digest(digest_dict)

        results = await svc.deliver_digest(digest)

        assert len(results) == 2
        assert backend1.delivered == [digest]
        assert backend2.delivered == [digest]
        assert results[0].backend_name == "email"
        assert results[1].backend_name == "slack"
        assert all(r.success for r in results)

    async def test_deliver_collects_failure_results(
        self,
        db: Database,
    ):
        """Failed deliveries should still be collected in results."""
        good_backend = StubNotificationBackend(name="good")
        bad_backend = StubNotificationBackend(name="bad", should_fail=True)

        svc = DigestService(db, [good_backend, bad_backend])

        digest = Digest(
            title="Test Digest",
            body="Some body text",
            signal_ids=[],
        )
        digest_dict = digest.model_dump()
        digest_dict["created_at"] = digest.created_at.isoformat()
        digest_dict["delivered_at"] = None
        digest_dict["signal_ids"] = json.dumps(digest.signal_ids)
        await db.insert_digest(digest_dict)

        results = await svc.deliver_digest(digest)

        assert len(results) == 2
        success_result = next(r for r in results if r.backend_name == "good")
        failure_result = next(r for r in results if r.backend_name == "bad")
        assert success_result.success is True
        assert failure_result.success is False
        assert failure_result.error is not None

    async def test_deliver_updates_delivered_at(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
    ):
        """After delivery, the digest's delivered_at should be updated in DB."""
        svc = DigestService(db, [stub_backend])

        digest = Digest(
            title="Test Digest",
            body="Some body",
            signal_ids=[],
        )
        digest_dict = digest.model_dump()
        digest_dict["created_at"] = digest.created_at.isoformat()
        digest_dict["delivered_at"] = None
        digest_dict["signal_ids"] = json.dumps(digest.signal_ids)
        await db.insert_digest(digest_dict)

        await svc.deliver_digest(digest)

        cursor = await db._db.execute("SELECT delivered_at FROM digests WHERE id = ?", (digest.id,))
        row = await cursor.fetchone()
        assert row is not None
        assert row["delivered_at"] is not None


# ---------------------------------------------------------------------------
# generate_and_deliver convenience method tests
# ---------------------------------------------------------------------------


class TestGenerateAndDeliver:
    async def test_generates_and_delivers(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
        repo_in_db: dict,
        fork_in_db: dict,
    ):
        """generate_and_deliver should produce a digest and deliver it."""
        signal = _make_signal(fork_in_db["id"], repo_in_db["id"], significance=8)
        await db.insert_signal(signal)

        config = _make_digest_config(tracked_repo_id=repo_in_db["id"])
        svc = DigestService(db, [stub_backend])
        digest, results = await svc.generate_and_deliver(config)

        assert isinstance(digest, Digest)
        assert len(results) == 1
        assert results[0].success is True
        assert len(stub_backend.delivered) == 1

    async def test_default_config_used_when_none(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
        repo_in_db: dict,
        fork_in_db: dict,
    ):
        """When config is None, a sensible default should be used."""
        signal = _make_signal(fork_in_db["id"], repo_in_db["id"], significance=8)
        await db.insert_signal(signal)

        svc = DigestService(db, [stub_backend])
        digest, results = await svc.generate_and_deliver(config=None)

        assert isinstance(digest, Digest)
        assert len(results) == 1

    async def test_with_since_parameter(
        self,
        db: Database,
        stub_backend: StubNotificationBackend,
        repo_in_db: dict,
        fork_in_db: dict,
    ):
        """generate_and_deliver should respect the since parameter."""
        old_signal = _make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            summary="Old signal",
            significance=8,
            created_at="2020-01-01T00:00:00+00:00",
        )
        recent_signal = _make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            summary="Recent signal",
            significance=8,
            created_at=_now_iso(),
        )
        await db.insert_signal(old_signal)
        await db.insert_signal(recent_signal)

        config = _make_digest_config(tracked_repo_id=repo_in_db["id"], min_significance=1)
        svc = DigestService(db, [stub_backend])
        since = datetime(2024, 1, 1, tzinfo=UTC)
        digest, results = await svc.generate_and_deliver(config, since=since)

        assert len(digest.signal_ids) == 1
        assert digest.signal_ids[0] == recent_signal["id"]

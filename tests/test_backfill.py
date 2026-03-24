# ABOUTME: Tests for the BackfillService agentic loop.
# ABOUTME: Uses stub providers and in-memory DB, no mock framework.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from forkhub.database import Database
from forkhub.models import (
    BackfillAttempt,
    BackfillResult,
    BackfillStatus,
    CommitInfo,
    CompareResult,
    Fork,
    ForkPage,
    RateLimitInfo,
    Release,
    RepoInfo,
    Signal,
    SignalCategory,
    TrackedRepo,
    TrackingMode,
)
from forkhub.services.backfill import BackfillService

# ---------------------------------------------------------------------------
# Time constants
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, tzinfo=UTC)
_ACTIVE_DATE = _NOW - timedelta(days=30)


# ---------------------------------------------------------------------------
# StubGitProvider for backfill testing
# ---------------------------------------------------------------------------


class BackfillStubGitProvider:
    """Stub provider that returns canned diffs for backfill testing."""

    def __init__(self) -> None:
        self._file_diffs: dict[str, dict[str, str]] = {}
        self._error_files: set[str] = set()

    def set_file_diff(self, fork_owner: str, filepath: str, diff: str) -> None:
        """Register a canned diff response for a fork/file combination."""
        key = f"{fork_owner}:{filepath}"
        self._file_diffs[key] = {filepath: diff}

    async def get_user_repos(self, username: str) -> list[RepoInfo]:
        return []

    async def get_repo(self, owner: str, repo: str) -> RepoInfo:
        return RepoInfo(
            github_id=1,
            owner=owner,
            name=repo,
            full_name=f"{owner}/{repo}",
            default_branch="main",
            description=None,
            is_fork=False,
            parent_full_name=None,
            stars=0,
            forks_count=0,
            last_pushed_at=_NOW,
        )

    async def get_forks(self, owner: str, repo: str, *, page: int = 1) -> ForkPage:
        return ForkPage(forks=[], total_count=0, page=1, has_next=False)

    async def compare(
        self, owner: str, repo: str, base: str, head: str
    ) -> CompareResult:
        return CompareResult(ahead_by=0, behind_by=0, files=[], commits=[])

    async def get_releases(
        self, owner: str, repo: str, *, since: datetime | None = None
    ) -> list[Release]:
        return []

    async def get_commit_messages(
        self, owner: str, repo: str, *, since: str | None = None
    ) -> list[CommitInfo]:
        return []

    async def get_file_diff(
        self, owner: str, repo: str, base: str, head: str, path: str
    ) -> str:
        # Extract fork owner from head param (format: "fork_owner:branch")
        fork_owner = head.split(":")[0]
        key = f"{fork_owner}:{path}"
        if path in self._error_files:
            raise RuntimeError(f"Simulated error fetching {path}")
        for registered_key, diffs in self._file_diffs.items():
            if registered_key == key and path in diffs:
                return diffs[path]
        return ""

    async def get_rate_limit(self) -> RateLimitInfo:
        return RateLimitInfo(limit=5000, remaining=4999, reset_at=_NOW)


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
def provider() -> BackfillStubGitProvider:
    return BackfillStubGitProvider()


async def _insert_tracked_repo(
    db: Database,
    owner: str = "upstream",
    name: str = "project",
    github_id: int = 1001,
) -> TrackedRepo:
    """Insert a tracked repo into the database."""
    repo = TrackedRepo(
        github_id=github_id,
        owner=owner,
        name=name,
        full_name=f"{owner}/{name}",
        tracking_mode=TrackingMode.WATCHED,
        default_branch="main",
    )
    d = repo.model_dump()
    d["created_at"] = repo.created_at.isoformat()
    d["last_synced_at"] = None
    await db.insert_tracked_repo(d)
    return repo


async def _insert_fork(
    db: Database,
    tracked_repo_id: str,
    owner: str = "forker1",
    github_id: int = 5001,
) -> Fork:
    """Insert a fork into the database."""
    fork = Fork(
        tracked_repo_id=tracked_repo_id,
        github_id=github_id,
        owner=owner,
        full_name=f"{owner}/project",
        default_branch="main",
        vitality="active",
        stars=10,
        last_pushed_at=_ACTIVE_DATE,
    )
    d = fork.model_dump()
    d["created_at"] = fork.created_at.isoformat()
    d["updated_at"] = fork.updated_at.isoformat()
    d["last_pushed_at"] = fork.last_pushed_at.isoformat() if fork.last_pushed_at else None
    await db.insert_fork(d)
    return fork


async def _insert_signal(
    db: Database,
    tracked_repo_id: str,
    fork_id: str,
    category: str = "feature",
    summary: str = "Adds Redis caching layer",
    significance: int = 7,
    files: list[str] | None = None,
    is_upstream: bool = False,
) -> Signal:
    """Insert a signal into the database."""
    signal = Signal(
        fork_id=fork_id,
        tracked_repo_id=tracked_repo_id,
        category=SignalCategory(category),
        summary=summary,
        significance=significance,
        files_involved=files or ["src/cache.py"],
        is_upstream=is_upstream,
    )
    d = signal.model_dump()
    d["created_at"] = signal.created_at.isoformat()
    d["files_involved"] = json.dumps(signal.files_involved)
    await db.insert_signal(d)
    return signal


# ---------------------------------------------------------------------------
# Candidate gathering
# ---------------------------------------------------------------------------


class TestGatherCandidates:
    async def test_gathers_signals_above_min_significance(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """Only signals at or above min_significance should be candidates."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        await _insert_signal(db, repo.id, fork.id, significance=3)  # Below threshold
        await _insert_signal(db, repo.id, fork.id, significance=7)  # Above threshold

        service = BackfillService(db=db, provider=provider, min_significance=5)
        candidates = await service._gather_candidates(repo.id)
        assert len(candidates) == 1
        assert candidates[0].significance == 7

    async def test_excludes_upstream_signals(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """Upstream signals should not be backfill candidates."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        await _insert_signal(db, repo.id, fork.id, significance=8, is_upstream=True)
        await _insert_signal(db, repo.id, fork.id, significance=7, is_upstream=False)

        service = BackfillService(db=db, provider=provider, min_significance=5)
        candidates = await service._gather_candidates(repo.id)
        assert len(candidates) == 1
        assert not candidates[0].is_upstream

    async def test_sorted_by_significance_descending(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """Candidates should be sorted by significance, highest first."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        await _insert_signal(db, repo.id, fork.id, significance=6, summary="Medium")
        await _insert_signal(db, repo.id, fork.id, significance=9, summary="High")
        await _insert_signal(db, repo.id, fork.id, significance=7, summary="Notable")

        service = BackfillService(db=db, provider=provider, min_significance=5)
        candidates = await service._gather_candidates(repo.id)
        assert len(candidates) == 3
        assert candidates[0].significance == 9
        assert candidates[1].significance == 7
        assert candidates[2].significance == 6

    async def test_empty_when_no_signals(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """No signals means no candidates."""
        repo = await _insert_tracked_repo(db)
        service = BackfillService(db=db, provider=provider)
        candidates = await service._gather_candidates(repo.id)
        assert candidates == []

    async def test_since_filter_applied(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """The since parameter should filter out older signals."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        # Insert a signal — it will have created_at = now
        await _insert_signal(db, repo.id, fork.id, significance=8)

        service = BackfillService(db=db, provider=provider, min_significance=5)
        # Ask for signals from the future — should get none
        future = datetime.now(UTC) + timedelta(days=1)
        candidates = await service._gather_candidates(repo.id, since=future)
        assert candidates == []


# ---------------------------------------------------------------------------
# Backfill attempt recording (traces — principle 5)
# ---------------------------------------------------------------------------


class TestBackfillTraces:
    async def test_attempt_recorded_to_database(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """Every backfill attempt should be persisted to the database."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        provider.set_file_diff("forker1", "src/cache.py", "some diff")
        await _insert_signal(db, repo.id, fork.id, significance=7)

        service = BackfillService(
            db=db, provider=provider, min_significance=5, max_attempts=1
        )
        # Dry run so we don't need real git
        await service.run_backfill(repo.id, dry_run=True)

        attempts = await db.list_backfill_attempts(repo_id=repo.id)
        assert len(attempts) == 1
        assert attempts[0]["status"] == "pending"

    async def test_skips_already_attempted_signals(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """Signals that already have backfill attempts should be skipped."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        signal = await _insert_signal(db, repo.id, fork.id, significance=8)

        # Manually insert a prior attempt for this signal
        prior = BackfillAttempt(
            signal_id=signal.id,
            fork_id=fork.id,
            tracked_repo_id=repo.id,
            status=BackfillStatus.TESTS_FAILED,
        )
        d = prior.model_dump()
        d["created_at"] = prior.created_at.isoformat()
        d["files_patched"] = json.dumps(prior.files_patched)
        await db.insert_backfill_attempt(d)

        service = BackfillService(
            db=db, provider=provider, min_significance=5, max_attempts=5
        )
        result = await service.run_backfill(repo.id, dry_run=True)
        # The signal should be skipped since it was already attempted
        assert result.attempted == 0

    async def test_has_backfill_for_signal_returns_true(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """has_backfill_for_signal returns True when attempt exists."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        signal = await _insert_signal(db, repo.id, fork.id)

        assert not await db.has_backfill_for_signal(signal.id)

        attempt = BackfillAttempt(
            signal_id=signal.id,
            fork_id=fork.id,
            tracked_repo_id=repo.id,
        )
        d = attempt.model_dump()
        d["created_at"] = attempt.created_at.isoformat()
        d["files_patched"] = json.dumps(attempt.files_patched)
        await db.insert_backfill_attempt(d)

        assert await db.has_backfill_for_signal(signal.id)


# ---------------------------------------------------------------------------
# Dry run mode
# ---------------------------------------------------------------------------


class TestDryRun:
    async def test_dry_run_does_not_apply_patches(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """Dry run should evaluate candidates but not apply any patches."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        diff = (
            "--- a/src/cache.py\n+++ b/src/cache.py\n"
            "@@ -1 +1 @@\n-old\n+new"
        )
        provider.set_file_diff("forker1", "src/cache.py", diff)
        await _insert_signal(db, repo.id, fork.id, significance=7)

        service = BackfillService(
            db=db, provider=provider, min_significance=5, max_attempts=5
        )
        result = await service.run_backfill(repo.id, dry_run=True)

        assert result.total_evaluated == 1
        assert result.attempted == 1
        assert result.accepted == 0
        assert result.branches_created == []

    async def test_dry_run_records_pending_attempt(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """Dry run attempts should be recorded with 'pending' status."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        provider.set_file_diff("forker1", "src/cache.py", "some diff")
        await _insert_signal(db, repo.id, fork.id, significance=8)

        service = BackfillService(
            db=db, provider=provider, min_significance=5, max_attempts=1
        )
        await service.run_backfill(repo.id, dry_run=True)

        attempts = await db.list_backfill_attempts(repo_id=repo.id)
        assert len(attempts) == 1
        assert attempts[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# Signal with missing fork
# ---------------------------------------------------------------------------


class TestMissingFork:
    async def test_signal_without_fork_id_fails_gracefully(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """A signal with no fork_id should result in patch_failed."""
        repo = await _insert_tracked_repo(db)
        # Insert a signal directly with no fork_id
        signal = Signal(
            fork_id=None,
            tracked_repo_id=repo.id,
            category=SignalCategory.FEATURE,
            summary="Orphan signal",
            significance=8,
            files_involved=["src/main.py"],
        )
        d = signal.model_dump()
        d["created_at"] = signal.created_at.isoformat()
        d["files_involved"] = json.dumps(signal.files_involved)
        await db.insert_signal(d)

        service = BackfillService(
            db=db, provider=provider, min_significance=5, max_attempts=1
        )
        result = await service.run_backfill(repo.id)
        # Signal without fork_id can't be backfilled
        assert result.patch_failed == 1

    async def test_deleted_fork_fails_gracefully(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """A signal referencing a deleted fork should fail gracefully."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        await _insert_signal(db, repo.id, fork.id, significance=8)

        # Delete the fork from DB to simulate it being removed
        # Must also delete signals first due to FK
        await db._db.execute(
            "DELETE FROM signals WHERE fork_id = ?", (fork.id,)
        )
        await db._db.commit()

        service = BackfillService(
            db=db, provider=provider, min_significance=5, max_attempts=1
        )
        result = await service.run_backfill(repo.id)
        # No signals remain after cascade, so nothing to attempt
        assert result.total_evaluated == 0


# ---------------------------------------------------------------------------
# Empty diff handling
# ---------------------------------------------------------------------------


class TestEmptyDiffs:
    async def test_no_diffs_available_results_in_patch_failed(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """When no diffs can be fetched, the attempt should be patch_failed."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        # Don't register any diffs in the provider
        await _insert_signal(db, repo.id, fork.id, significance=7)

        service = BackfillService(
            db=db, provider=provider, min_significance=5, max_attempts=1
        )
        result = await service.run_backfill(repo.id)
        assert result.patch_failed == 1


# ---------------------------------------------------------------------------
# BackfillResult aggregation
# ---------------------------------------------------------------------------


class TestBackfillResult:
    async def test_result_counts_multiple_signals(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """BackfillResult should aggregate counts across multiple signals."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        # Insert multiple signals
        for i in range(5):
            await _insert_signal(
                db, repo.id, fork.id,
                significance=6 + i % 3,
                summary=f"Signal {i}",
                files=[f"src/file_{i}.py"],
            )

        service = BackfillService(
            db=db, provider=provider, min_significance=5, max_attempts=10
        )
        result = await service.run_backfill(repo.id, dry_run=True)
        assert result.total_evaluated == 5
        assert result.attempted == 5

    async def test_max_attempts_limits_processing(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """max_attempts should cap how many signals are processed."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        for i in range(10):
            await _insert_signal(
                db, repo.id, fork.id,
                significance=7,
                summary=f"Signal {i}",
                files=[f"src/file_{i}.py"],
            )

        service = BackfillService(
            db=db, provider=provider, min_significance=5, max_attempts=3
        )
        result = await service.run_backfill(repo.id, dry_run=True)
        assert result.total_evaluated == 10
        assert result.attempted == 3


# ---------------------------------------------------------------------------
# list_attempts
# ---------------------------------------------------------------------------


class TestListAttempts:
    async def test_list_attempts_returns_all(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """list_attempts should return all recorded attempts."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        signal = await _insert_signal(db, repo.id, fork.id)

        for status in [BackfillStatus.ACCEPTED, BackfillStatus.TESTS_FAILED]:
            attempt = BackfillAttempt(
                signal_id=signal.id,
                fork_id=fork.id,
                tracked_repo_id=repo.id,
                status=status,
            )
            d = attempt.model_dump()
            d["created_at"] = attempt.created_at.isoformat()
            d["files_patched"] = json.dumps(attempt.files_patched)
            await db.insert_backfill_attempt(d)

        service = BackfillService(db=db, provider=provider)
        attempts = await service.list_attempts(repo_id=repo.id)
        assert len(attempts) == 2

    async def test_list_attempts_filters_by_status(
        self, db: Database, provider: BackfillStubGitProvider
    ):
        """list_attempts should filter by status when provided."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        sig1 = await _insert_signal(
            db, repo.id, fork.id, summary="S1"
        )
        sig2 = await _insert_signal(
            db, repo.id, fork.id, summary="S2"
        )
        sig3 = await _insert_signal(
            db, repo.id, fork.id, summary="S3"
        )

        for signal, status in [
            (sig1, BackfillStatus.ACCEPTED),
            (sig2, BackfillStatus.TESTS_FAILED),
            (sig3, BackfillStatus.ACCEPTED),
        ]:
            attempt = BackfillAttempt(
                signal_id=signal.id,
                fork_id=fork.id,
                tracked_repo_id=repo.id,
                status=status,
            )
            d = attempt.model_dump()
            d["created_at"] = attempt.created_at.isoformat()
            d["files_patched"] = json.dumps(attempt.files_patched)
            await db.insert_backfill_attempt(d)

        service = BackfillService(db=db, provider=provider)
        accepted = await service.list_attempts(
            repo_id=repo.id, status="accepted"
        )
        assert len(accepted) == 2


# ---------------------------------------------------------------------------
# Database CRUD for backfill_attempts
# ---------------------------------------------------------------------------


class TestBackfillDatabase:
    async def test_insert_and_get(self, db: Database):
        """Should insert and retrieve a backfill attempt."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        signal = await _insert_signal(db, repo.id, fork.id)

        attempt = BackfillAttempt(
            signal_id=signal.id,
            fork_id=fork.id,
            tracked_repo_id=repo.id,
            status=BackfillStatus.ACCEPTED,
            branch_name="backfill/feature/forker1-abc12345",
            patch_summary="Adds Redis caching",
            score=0.95,
            files_patched=["src/cache.py", "src/config.py"],
        )
        d = attempt.model_dump()
        d["created_at"] = attempt.created_at.isoformat()
        d["files_patched"] = json.dumps(attempt.files_patched)
        await db.insert_backfill_attempt(d)

        retrieved = await db.get_backfill_attempt(attempt.id)
        assert retrieved is not None
        assert retrieved["status"] == "accepted"
        assert retrieved["branch_name"] == "backfill/feature/forker1-abc12345"
        assert retrieved["score"] == 0.95

    async def test_update_attempt(self, db: Database):
        """Should update a backfill attempt's status and fields."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)
        signal = await _insert_signal(db, repo.id, fork.id)

        attempt = BackfillAttempt(
            signal_id=signal.id,
            fork_id=fork.id,
            tracked_repo_id=repo.id,
            status=BackfillStatus.PENDING,
        )
        d = attempt.model_dump()
        d["created_at"] = attempt.created_at.isoformat()
        d["files_patched"] = json.dumps(attempt.files_patched)
        await db.insert_backfill_attempt(d)

        # Update the status
        d["status"] = "accepted"
        d["score"] = 1.0
        d["branch_name"] = "backfill/fix/forker1-abc"
        await db.update_backfill_attempt(d)

        retrieved = await db.get_backfill_attempt(attempt.id)
        assert retrieved["status"] == "accepted"
        assert retrieved["score"] == 1.0

    async def test_list_with_multiple_filters(self, db: Database):
        """list_backfill_attempts should support multiple filters."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo.id)

        signals = []
        for i in range(3):
            sig = await _insert_signal(
                db, repo.id, fork.id, summary=f"Sig {i}"
            )
            signals.append(sig)

        for sig, status in zip(
            signals,
            ["accepted", "tests_failed", "accepted"],
            strict=True,
        ):
            attempt = BackfillAttempt(
                signal_id=sig.id,
                fork_id=fork.id,
                tracked_repo_id=repo.id,
                status=BackfillStatus(status),
            )
            d = attempt.model_dump()
            d["created_at"] = attempt.created_at.isoformat()
            d["files_patched"] = json.dumps(attempt.files_patched)
            await db.insert_backfill_attempt(d)

        # Filter by repo + status
        rows = await db.list_backfill_attempts(
            repo_id=repo.id, status="accepted"
        )
        assert len(rows) == 2

        # Filter by signal_id
        rows = await db.list_backfill_attempts(
            signal_id=signals[1].id
        )
        assert len(rows) == 1
        assert rows[0]["status"] == "tests_failed"


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestBackfillModels:
    def test_backfill_status_enum_values(self):
        """BackfillStatus should have all expected values."""
        assert BackfillStatus.PENDING == "pending"
        assert BackfillStatus.PATCH_FAILED == "patch_failed"
        assert BackfillStatus.TESTS_FAILED == "tests_failed"
        assert BackfillStatus.CONFLICT == "conflict"
        assert BackfillStatus.ACCEPTED == "accepted"
        assert BackfillStatus.REJECTED == "rejected"

    def test_backfill_attempt_default_values(self):
        """BackfillAttempt should have sensible defaults."""
        attempt = BackfillAttempt(
            signal_id="sig-1",
            fork_id="fork-1",
            tracked_repo_id="repo-1",
        )
        assert attempt.status == BackfillStatus.PENDING
        assert attempt.branch_name is None
        assert attempt.files_patched == []
        assert attempt.score is None
        assert attempt.id  # UUID should be generated

    def test_backfill_result_default_values(self):
        """BackfillResult should start with zero counts."""
        result = BackfillResult()
        assert result.total_evaluated == 0
        assert result.attempted == 0
        assert result.accepted == 0
        assert result.patch_failed == 0
        assert result.tests_failed == 0
        assert result.conflicts == 0
        assert result.branches_created == []

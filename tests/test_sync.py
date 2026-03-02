# ABOUTME: Tests for the SyncService that discovers and compares forks.
# ABOUTME: Uses a StubGitProvider with canned fork data, no mock framework.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from forkhub.config import SyncSettings
from forkhub.database import Database
from forkhub.models import (
    CommitInfo,
    CompareResult,
    FileChange,
    ForkInfo,
    ForkPage,
    ForkVitality,
    RateLimitInfo,
    Release,
    RepoInfo,
    TrackedRepo,
    TrackingMode,
)
from forkhub.services.sync import RepoSyncResult, SyncResult, SyncService

# ---------------------------------------------------------------------------
# Time constants
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, tzinfo=UTC)
_ACTIVE_DATE = _NOW - timedelta(days=30)  # 30 days ago = active
_DORMANT_DATE = _NOW - timedelta(days=200)  # 200 days ago = dormant
_DEAD_DATE = _NOW - timedelta(days=400)  # 400 days ago = dead


# ---------------------------------------------------------------------------
# StubGitProvider with fork-related canned data
# ---------------------------------------------------------------------------


class SyncStubGitProvider:
    """Stub provider with rich fork data for sync testing."""

    def __init__(self) -> None:
        self._forks: dict[str, list[ForkInfo]] = {
            "owner/repo-a": [
                ForkInfo(
                    github_id=5001,
                    owner="forker1",
                    full_name="forker1/repo-a",
                    default_branch="main",
                    description="Forker 1's copy",
                    stars=15,
                    last_pushed_at=_ACTIVE_DATE,
                    has_diverged=True,
                    created_at=_NOW - timedelta(days=60),
                ),
                ForkInfo(
                    github_id=5002,
                    owner="forker2",
                    full_name="forker2/repo-a",
                    default_branch="main",
                    description="Forker 2's copy",
                    stars=3,
                    last_pushed_at=_DORMANT_DATE,
                    has_diverged=False,
                    created_at=_NOW - timedelta(days=300),
                ),
                ForkInfo(
                    github_id=5003,
                    owner="forker3",
                    full_name="forker3/repo-a",
                    default_branch="main",
                    description="Forker 3's dead fork",
                    stars=0,
                    last_pushed_at=_DEAD_DATE,
                    has_diverged=False,
                    created_at=_NOW - timedelta(days=500),
                ),
            ],
            "owner/repo-b": [
                ForkInfo(
                    github_id=6001,
                    owner="forker4",
                    full_name="forker4/repo-b",
                    default_branch="main",
                    description="Forker 4's copy",
                    stars=7,
                    last_pushed_at=_ACTIVE_DATE,
                    has_diverged=True,
                    created_at=_NOW - timedelta(days=10),
                ),
            ],
        }
        self._compare_results: dict[str, CompareResult] = {
            "forker1/repo-a": CompareResult(
                ahead_by=5,
                behind_by=2,
                files=[
                    FileChange(
                        filename="src/new_feature.py",
                        status="added",
                        additions=100,
                        deletions=0,
                        patch="+ new code",
                    ),
                ],
                commits=[
                    CommitInfo(
                        sha="abc123",
                        message="Add new feature",
                        author="forker1",
                        authored_at=_NOW,
                    ),
                ],
            ),
        }
        self._releases: dict[str, list[Release]] = {
            "owner/repo-a": [
                Release(
                    tag="v2.0.0",
                    name="Version 2.0",
                    body="Big release",
                    published_at=_NOW - timedelta(days=1),
                    is_prerelease=False,
                ),
                Release(
                    tag="v1.5.0",
                    name="Version 1.5",
                    body="Older release",
                    published_at=_NOW - timedelta(days=60),
                    is_prerelease=False,
                ),
            ],
        }
        # Track the HEAD SHAs that the provider reports
        self._head_shas: dict[str, str] = {
            "forker1/repo-a": "new-sha-forker1",
            "forker2/repo-a": "unchanged-sha-forker2",
            "forker3/repo-a": "new-sha-forker3",
            "forker4/repo-b": "new-sha-forker4",
        }
        # Flag to simulate errors for specific forks
        self._error_forks: set[str] = set()

    async def get_user_repos(self, username: str) -> list[RepoInfo]:
        return []

    async def get_repo(self, owner: str, repo: str) -> RepoInfo:
        full_name = f"{owner}/{repo}"
        return RepoInfo(
            github_id=hash(full_name) % 100000,
            owner=owner,
            name=repo,
            full_name=full_name,
            default_branch="main",
            description=None,
            is_fork=False,
            parent_full_name=None,
            stars=0,
            forks_count=0,
            last_pushed_at=_NOW,
        )

    async def get_forks(self, owner: str, repo: str, *, page: int = 1) -> ForkPage:
        full_name = f"{owner}/{repo}"
        forks = self._forks.get(full_name, [])
        return ForkPage(
            forks=forks,
            total_count=len(forks),
            page=1,
            has_next=False,
        )

    async def compare(
        self, owner: str, repo: str, base: str, head: str
    ) -> CompareResult:
        # The head parameter encodes the fork owner: "forker1:main"
        fork_owner = head.split(":")[0]
        fork_full = f"{fork_owner}/{repo}"

        if fork_full in self._error_forks:
            raise RuntimeError(f"Simulated API error for {fork_full}")

        if fork_full in self._compare_results:
            return self._compare_results[fork_full]
        return CompareResult(ahead_by=0, behind_by=0, files=[], commits=[])

    async def get_releases(
        self, owner: str, repo: str, *, since: datetime | None = None
    ) -> list[Release]:
        full_name = f"{owner}/{repo}"
        releases = self._releases.get(full_name, [])
        if since is not None:
            releases = [r for r in releases if r.published_at > since]
        return releases

    async def get_commit_messages(
        self, owner: str, repo: str, *, since: str | None = None
    ) -> list[CommitInfo]:
        return []

    async def get_file_diff(
        self, owner: str, repo: str, base: str, head: str, path: str
    ) -> str:
        return ""

    async def get_rate_limit(self) -> RateLimitInfo:
        return RateLimitInfo(limit=5000, remaining=4999, reset_at=_NOW)

    def get_head_sha(self, fork_full_name: str) -> str | None:
        """Helper for tests to look up the SHA a fork should have."""
        return self._head_shas.get(fork_full_name)


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
def provider() -> SyncStubGitProvider:
    return SyncStubGitProvider()


@pytest.fixture
def settings() -> SyncSettings:
    return SyncSettings(max_forks_per_repo=5000)


@pytest.fixture
def sync_service(
    db: Database, provider: SyncStubGitProvider, settings: SyncSettings
) -> SyncService:
    return SyncService(db=db, provider=provider, settings=settings, clock=_NOW)


async def _insert_tracked_repo(
    db: Database,
    owner: str = "owner",
    name: str = "repo-a",
    github_id: int = 1001,
    last_synced_at: datetime | None = None,
) -> TrackedRepo:
    """Helper to insert a tracked repo into the database."""
    repo = TrackedRepo(
        github_id=github_id,
        owner=owner,
        name=name,
        full_name=f"{owner}/{name}",
        tracking_mode=TrackingMode.WATCHED,
        default_branch="main",
        last_synced_at=last_synced_at,
    )
    d = repo.model_dump()
    d["created_at"] = repo.created_at.isoformat()
    d["last_synced_at"] = repo.last_synced_at.isoformat() if repo.last_synced_at else None
    await db.insert_tracked_repo(d)
    return repo


async def _insert_fork_in_db(
    db: Database,
    tracked_repo_id: str,
    github_id: int,
    owner: str,
    full_name: str,
    head_sha: str | None = None,
    stars: int = 0,
    last_pushed_at: datetime | None = None,
) -> dict:
    """Helper to insert a fork record directly into the database."""
    from forkhub.models import Fork

    fork = Fork(
        tracked_repo_id=tracked_repo_id,
        github_id=github_id,
        owner=owner,
        full_name=full_name,
        default_branch="main",
        head_sha=head_sha,
        stars=stars,
        last_pushed_at=last_pushed_at,
    )
    d = fork.model_dump()
    d["created_at"] = fork.created_at.isoformat()
    d["updated_at"] = fork.updated_at.isoformat()
    d["last_pushed_at"] = fork.last_pushed_at.isoformat() if fork.last_pushed_at else None
    await db.insert_fork(d)
    return d


# ---------------------------------------------------------------------------
# Full sync pipeline
# ---------------------------------------------------------------------------


class TestSyncRepo:
    async def test_discovers_forks_and_returns_result(
        self, sync_service: SyncService, db: Database
    ):
        """sync_repo should discover forks and return a RepoSyncResult."""
        repo = await _insert_tracked_repo(db)
        result = await sync_service.sync_repo(repo.id)
        assert isinstance(result, RepoSyncResult)
        assert result.repo_full_name == "owner/repo-a"
        # 3 forks from the stub, all are new
        assert result.new_forks == 3

    async def test_head_sha_unchanged_forks_skipped(
        self, sync_service: SyncService, db: Database, provider: SyncStubGitProvider
    ):
        """Forks whose HEAD SHA hasn't changed should be skipped."""
        repo = await _insert_tracked_repo(db)
        # Pre-insert forker2's fork with the same SHA the provider will report
        await _insert_fork_in_db(
            db,
            tracked_repo_id=repo.id,
            github_id=5002,
            owner="forker2",
            full_name="forker2/repo-a",
            head_sha="unchanged-sha-forker2",
        )
        result = await sync_service.sync_repo(repo.id)
        # forker2 should NOT be in the changed list since SHA is the same
        assert "forker2/repo-a" not in result.changed_forks
        # forker1 and forker3 should be new since they weren't in DB yet
        assert result.new_forks == 2

    async def test_changed_forks_get_updated(
        self, sync_service: SyncService, db: Database, provider: SyncStubGitProvider
    ):
        """Forks with changed HEAD SHA should get their comparison data updated."""
        repo = await _insert_tracked_repo(db)
        # Pre-insert forker1's fork with an OLD sha
        await _insert_fork_in_db(
            db,
            tracked_repo_id=repo.id,
            github_id=5001,
            owner="forker1",
            full_name="forker1/repo-a",
            head_sha="old-sha",
            stars=10,
        )
        result = await sync_service.sync_repo(repo.id)
        assert "forker1/repo-a" in result.changed_forks
        # Verify the fork record in DB was updated
        fork_row = await db.get_fork_by_name("forker1/repo-a")
        assert fork_row is not None
        assert fork_row["head_sha"] == "new-sha-forker1"
        assert fork_row["commits_ahead"] == 5
        assert fork_row["commits_behind"] == 2


# ---------------------------------------------------------------------------
# Vitality classification
# ---------------------------------------------------------------------------


class TestVitalityClassification:
    async def test_active_within_90_days(self, sync_service: SyncService):
        """A fork pushed within 90 days should be classified as active."""
        result = sync_service._classify_vitality(_ACTIVE_DATE)
        assert result == ForkVitality.ACTIVE

    async def test_dormant_90_to_365_days(self, sync_service: SyncService):
        """A fork pushed 90-365 days ago should be classified as dormant."""
        result = sync_service._classify_vitality(_DORMANT_DATE)
        assert result == ForkVitality.DORMANT

    async def test_dead_over_365_days(self, sync_service: SyncService):
        """A fork pushed >365 days ago should be classified as dead."""
        result = sync_service._classify_vitality(_DEAD_DATE)
        assert result == ForkVitality.DEAD

    async def test_unknown_when_none(self, sync_service: SyncService):
        """A fork with no push date should be classified as unknown."""
        result = sync_service._classify_vitality(None)
        assert result == ForkVitality.UNKNOWN

    async def test_boundary_exactly_90_days(self, sync_service: SyncService):
        """Exactly 90 days ago is still active (boundary test)."""
        boundary = _NOW - timedelta(days=90)
        result = sync_service._classify_vitality(boundary)
        assert result == ForkVitality.ACTIVE

    async def test_boundary_91_days(self, sync_service: SyncService):
        """91 days ago crosses into dormant."""
        boundary = _NOW - timedelta(days=91)
        result = sync_service._classify_vitality(boundary)
        assert result == ForkVitality.DORMANT

    async def test_boundary_exactly_365_days(self, sync_service: SyncService):
        """Exactly 365 days ago is still dormant."""
        boundary = _NOW - timedelta(days=365)
        result = sync_service._classify_vitality(boundary)
        assert result == ForkVitality.DORMANT

    async def test_boundary_366_days(self, sync_service: SyncService):
        """366 days ago crosses into dead."""
        boundary = _NOW - timedelta(days=366)
        result = sync_service._classify_vitality(boundary)
        assert result == ForkVitality.DEAD


# ---------------------------------------------------------------------------
# Star count updates
# ---------------------------------------------------------------------------


class TestStarUpdates:
    async def test_star_count_updated_on_sync(
        self, sync_service: SyncService, db: Database
    ):
        """Fork star counts should be updated from provider data during sync."""
        repo = await _insert_tracked_repo(db)
        # Pre-insert with old star count
        await _insert_fork_in_db(
            db,
            tracked_repo_id=repo.id,
            github_id=5001,
            owner="forker1",
            full_name="forker1/repo-a",
            head_sha="old-sha",
            stars=5,
        )
        await sync_service.sync_repo(repo.id)
        fork_row = await db.get_fork_by_name("forker1/repo-a")
        assert fork_row is not None
        # Provider says forker1 has 15 stars
        assert fork_row["stars"] == 15
        # Previous stars should have been captured
        assert fork_row["stars_previous"] == 5


# ---------------------------------------------------------------------------
# Release detection
# ---------------------------------------------------------------------------


class TestReleaseDetection:
    async def test_new_releases_detected(
        self, sync_service: SyncService, db: Database
    ):
        """Releases published since last sync should be counted."""
        # Repo was last synced 30 days ago
        last_synced = _NOW - timedelta(days=30)
        repo = await _insert_tracked_repo(db, last_synced_at=last_synced)
        result = await sync_service.sync_repo(repo.id)
        # Only v2.0.0 was published 1 day ago (after last sync 30 days ago)
        # v1.5.0 was 60 days ago (before last sync)
        assert result.new_releases == 1

    async def test_no_releases_when_never_synced(
        self, sync_service: SyncService, db: Database
    ):
        """First sync (never synced before) should report all releases."""
        repo = await _insert_tracked_repo(db, last_synced_at=None)
        result = await sync_service.sync_repo(repo.id)
        # When since=None, all releases are returned
        assert result.new_releases == 2


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestSyncErrorHandling:
    async def test_individual_fork_error_doesnt_stop_sync(
        self, sync_service: SyncService, db: Database, provider: SyncStubGitProvider
    ):
        """An error on one fork's compare should not prevent other forks from syncing."""
        repo = await _insert_tracked_repo(db)
        # Pre-insert forker1 with old SHA to trigger compare, but mark it to error
        await _insert_fork_in_db(
            db,
            tracked_repo_id=repo.id,
            github_id=5001,
            owner="forker1",
            full_name="forker1/repo-a",
            head_sha="old-sha",
        )
        provider._error_forks.add("forker1/repo-a")
        result = await sync_service.sync_repo(repo.id)
        # Should have errors but still process other forks
        assert len(result.errors) > 0
        assert "forker1/repo-a" in result.errors[0]
        # forker2 and forker3 should still have been processed (they are new)
        assert result.new_forks == 2


# ---------------------------------------------------------------------------
# sync_all
# ---------------------------------------------------------------------------


class TestSyncAll:
    async def test_aggregates_results_from_multiple_repos(
        self, sync_service: SyncService, db: Database
    ):
        """sync_all should aggregate results across all tracked repos."""
        await _insert_tracked_repo(db, owner="owner", name="repo-a", github_id=1001)
        await _insert_tracked_repo(db, owner="owner", name="repo-b", github_id=1002)
        result = await sync_service.sync_all()
        assert isinstance(result, SyncResult)
        assert result.repos_synced == 2
        assert len(result.results) == 2
        # repo-a has 3 forks, repo-b has 1
        assert result.total_changed_forks == 0  # all new, none "changed"

    async def test_skips_excluded_repos(
        self, sync_service: SyncService, db: Database
    ):
        """sync_all should not sync excluded repos."""
        repo = await _insert_tracked_repo(db)
        # Exclude the repo
        row = await db.get_tracked_repo(repo.id)
        row["excluded"] = True
        await db.update_tracked_repo(row)
        result = await sync_service.sync_all()
        assert result.repos_synced == 0


# ---------------------------------------------------------------------------
# last_synced_at
# ---------------------------------------------------------------------------


class TestLastSyncedAt:
    async def test_last_synced_at_updated_after_sync(
        self, sync_service: SyncService, db: Database
    ):
        """sync_repo should update the repo's last_synced_at timestamp."""
        repo = await _insert_tracked_repo(db)
        row_before = await db.get_tracked_repo(repo.id)
        assert row_before["last_synced_at"] is None
        await sync_service.sync_repo(repo.id)
        row_after = await db.get_tracked_repo(repo.id)
        assert row_after["last_synced_at"] is not None


# ---------------------------------------------------------------------------
# Vitality update during sync
# ---------------------------------------------------------------------------


class TestVitalityDuringSync:
    async def test_vitality_updated_on_sync(
        self, sync_service: SyncService, db: Database
    ):
        """Fork vitality should be updated based on last_pushed_at during sync."""
        repo = await _insert_tracked_repo(db)
        await sync_service.sync_repo(repo.id)
        # forker1 pushed 30 days ago = active
        fork1 = await db.get_fork_by_name("forker1/repo-a")
        assert fork1["vitality"] == "active"
        # forker2 pushed 200 days ago = dormant
        fork2 = await db.get_fork_by_name("forker2/repo-a")
        assert fork2["vitality"] == "dormant"
        # forker3 pushed 400 days ago = dead
        fork3 = await db.get_fork_by_name("forker3/repo-a")
        assert fork3["vitality"] == "dead"

# ABOUTME: Tests for the SyncService that discovers and compares forks.
# ABOUTME: Uses a StubGitProvider with canned fork data, no mock framework.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from forkhub.config import SyncSettings
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
    SyncStatus,
    TrackedRepo,
    TrackingMode,
)
from forkhub.services.sync import SyncService

if TYPE_CHECKING:
    from forkhub.database import Database

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
        # Mapping of full_name -> HTTP status code for repos that should error
        self._error_repos: dict[str, int] = {}
        # Extra user repos for discovery testing
        self._user_repos: dict[str, list[RepoInfo]] = {}

    async def get_user_repos(self, username: str) -> list[RepoInfo]:
        return self._user_repos.get(username, [])

    async def get_repo(self, owner: str, repo: str) -> RepoInfo:
        full_name = f"{owner}/{repo}"
        if full_name in self._error_repos:
            exc = RuntimeError(f"HTTP {self._error_repos[full_name]} for {full_name}")
            exc.status_code = self._error_repos[full_name]  # type: ignore[attr-defined]
            raise exc
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
        if full_name in self._error_repos:
            exc = RuntimeError(f"HTTP {self._error_repos[full_name]} for {full_name}")
            exc.status_code = self._error_repos[full_name]  # type: ignore[attr-defined]
            raise exc
        forks = self._forks.get(full_name, [])
        return ForkPage(
            forks=forks,
            total_count=len(forks),
            page=1,
            has_next=False,
        )

    async def compare(self, owner: str, repo: str, base: str, head: str) -> CompareResult:
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

    async def get_file_diff(self, owner: str, repo: str, base: str, head: str, path: str) -> str:
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
    sync_status: str = "ok",
    last_sync_error: str | None = None,
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
        sync_status=SyncStatus(sync_status),
        last_sync_error=last_sync_error,
    )
    d = repo.model_dump()
    d["created_at"] = repo.created_at.isoformat()
    d["last_synced_at"] = repo.last_synced_at.isoformat() if repo.last_synced_at else None
    d["sync_status"] = str(repo.sync_status)
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
# Vitality classification
# ---------------------------------------------------------------------------


class TestVitalityClassification:
    async def test_unknown_when_none(self, sync_service: SyncService):
        """A fork with no push date should be classified as unknown."""
        result = sync_service._classify_vitality(None)
        assert result == ForkVitality.UNKNOWN


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
# Inaccessible repo detection
# ---------------------------------------------------------------------------


class TestInaccessibleRepoDetection:
    async def test_inaccessible_repos_skipped_in_sync_all(
        self, sync_service: SyncService, db: Database, provider: SyncStubGitProvider
    ):
        """sync_all should skip repos with sync_status='inaccessible'."""
        await _insert_tracked_repo(
            db,
            owner="owner",
            name="repo-a",
            github_id=1001,
            sync_status="inaccessible",
            last_sync_error="404",
        )
        await _insert_tracked_repo(
            db,
            owner="owner",
            name="repo-b",
            github_id=1002,
        )
        result = await sync_service.sync_all()
        # Only repo-b should be synced
        assert result.repos_synced == 1
        assert result.results[0].repo_full_name == "owner/repo-b"


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


class TestReconciliation:
    async def test_reconcile_phase2_failure_preserves_phase1_results(
        self, sync_service: SyncService, db: Database, provider: SyncStubGitProvider
    ):
        """If Phase 2 (discovery) fails, Phase 1 results should still be returned."""
        repo = await _insert_tracked_repo(
            db,
            sync_status="inaccessible",
            last_sync_error="404",
        )
        # Provider succeeds for get_repo (Phase 1 recovers the repo)
        # but get_user_repos will fail for discovery

        class FailingTracker:
            async def discover_owned_repos(self, username):
                raise ConnectionError("API rate limited")

        result = await sync_service.reconcile(
            username="testuser",
            tracker_service=FailingTracker(),  # type: ignore[arg-type]
        )
        # Phase 1 should have succeeded
        assert repo.full_name in result.repos_recovered
        # Phase 2 failed, so no discovered repos
        assert result.new_repos_discovered == []

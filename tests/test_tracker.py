# ABOUTME: Tests for the TrackerService that manages repo discovery and tracking.
# ABOUTME: Uses a StubGitProvider with canned data instead of real GitHub API calls.

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from forkhub.database import Database
from forkhub.models import (
    CommitInfo,
    CompareResult,
    ForkPage,
    RateLimitInfo,
    Release,
    RepoInfo,
    TrackingMode,
)
from forkhub.services.tracker import TrackerService

# ---------------------------------------------------------------------------
# StubGitProvider — implements the GitProvider protocol with canned data
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, tzinfo=UTC)


class StubGitProvider:
    """Stub implementation of GitProvider with canned repo and fork data."""

    def __init__(self) -> None:
        self.user_repos: dict[str, list[RepoInfo]] = {
            "testuser": [
                RepoInfo(
                    github_id=1001,
                    owner="testuser",
                    name="alpha",
                    full_name="testuser/alpha",
                    default_branch="main",
                    description="Alpha project",
                    is_fork=False,
                    parent_full_name=None,
                    stars=10,
                    forks_count=3,
                    last_pushed_at=_NOW,
                ),
                RepoInfo(
                    github_id=1002,
                    owner="testuser",
                    name="beta",
                    full_name="testuser/beta",
                    default_branch="main",
                    description="Beta project",
                    is_fork=False,
                    parent_full_name=None,
                    stars=5,
                    forks_count=1,
                    last_pushed_at=_NOW,
                ),
                RepoInfo(
                    github_id=1003,
                    owner="testuser",
                    name="forked-lib",
                    full_name="testuser/forked-lib",
                    default_branch="main",
                    description="A forked library",
                    is_fork=True,
                    parent_full_name="upstream-org/forked-lib",
                    stars=0,
                    forks_count=0,
                    last_pushed_at=_NOW,
                ),
            ],
        }
        self.repos: dict[str, RepoInfo] = {
            "testuser/alpha": self.user_repos["testuser"][0],
            "testuser/beta": self.user_repos["testuser"][1],
            "testuser/forked-lib": self.user_repos["testuser"][2],
            "upstream-org/forked-lib": RepoInfo(
                github_id=2001,
                owner="upstream-org",
                name="forked-lib",
                full_name="upstream-org/forked-lib",
                default_branch="main",
                description="The original library",
                is_fork=False,
                parent_full_name=None,
                stars=500,
                forks_count=50,
                last_pushed_at=_NOW,
            ),
        }

    async def get_user_repos(self, username: str) -> list[RepoInfo]:
        return self.user_repos.get(username, [])

    async def get_repo(self, owner: str, repo: str) -> RepoInfo:
        full_name = f"{owner}/{repo}"
        if full_name not in self.repos:
            raise ValueError(f"Repo not found: {full_name}")
        return self.repos[full_name]

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
def provider() -> StubGitProvider:
    return StubGitProvider()


@pytest.fixture
def tracker(db: Database, provider: StubGitProvider) -> TrackerService:
    return TrackerService(db=db, provider=provider)


# ---------------------------------------------------------------------------
# discover_owned_repos
# ---------------------------------------------------------------------------


class TestDiscoverOwnedRepos:
    async def test_discover_adds_new_repos(
        self, tracker: TrackerService, db: Database
    ):
        """Discovering repos for a user should insert them as tracked repos."""
        result = await tracker.discover_owned_repos("testuser")
        # The stub has 3 repos for testuser, but only 2 are non-forks
        # discover_owned_repos tracks non-fork repos as 'owned'
        assert len(result) == 2
        assert all(r.tracking_mode == TrackingMode.OWNED for r in result)
        names = {r.full_name for r in result}
        assert names == {"testuser/alpha", "testuser/beta"}

    async def test_discover_skips_already_tracked(
        self, tracker: TrackerService, db: Database
    ):
        """Second call to discover should not duplicate repos."""
        await tracker.discover_owned_repos("testuser")
        second = await tracker.discover_owned_repos("testuser")
        # Second call should return empty since they're already tracked
        assert len(second) == 0
        # Database should still have exactly 2
        all_repos = await db.list_tracked_repos()
        assert len(all_repos) == 2

    async def test_discover_respects_excluded_flag(
        self, tracker: TrackerService, db: Database
    ):
        """Excluded repos should not be re-added on discover."""
        await tracker.discover_owned_repos("testuser")
        await tracker.exclude_repo("testuser/alpha")
        # Rediscover should not re-add excluded repo
        result = await tracker.discover_owned_repos("testuser")
        assert len(result) == 0
        # The excluded repo should still be excluded in DB
        all_repos = await db.list_tracked_repos(include_excluded=True)
        excluded = [r for r in all_repos if r["excluded"]]
        assert len(excluded) == 1
        assert excluded[0]["full_name"] == "testuser/alpha"


# ---------------------------------------------------------------------------
# track_repo
# ---------------------------------------------------------------------------


class TestTrackRepo:
    async def test_track_repo_adds_watched(
        self, tracker: TrackerService, db: Database
    ):
        """Tracking a repo should add it with the correct mode and metadata."""
        result = await tracker.track_repo("testuser", "alpha")
        assert result.full_name == "testuser/alpha"
        assert result.tracking_mode == TrackingMode.WATCHED
        assert result.github_id == 1001
        assert result.default_branch == "main"
        assert result.description == "Alpha project"
        # Verify it's in the database
        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is not None

    async def test_track_repo_custom_mode(
        self, tracker: TrackerService, db: Database
    ):
        """Tracking with a custom mode should be honored."""
        result = await tracker.track_repo(
            "testuser", "alpha", mode=TrackingMode.UPSTREAM
        )
        assert result.tracking_mode == TrackingMode.UPSTREAM

    async def test_track_repo_raises_on_duplicate(
        self, tracker: TrackerService, db: Database
    ):
        """Tracking an already-tracked repo should raise ValueError."""
        await tracker.track_repo("testuser", "alpha")
        with pytest.raises(ValueError, match="already tracked"):
            await tracker.track_repo("testuser", "alpha")


# ---------------------------------------------------------------------------
# untrack_repo
# ---------------------------------------------------------------------------


class TestUntrackRepo:
    async def test_untrack_removes_repo(
        self, tracker: TrackerService, db: Database
    ):
        """Untracking should remove the repo from the database."""
        await tracker.track_repo("testuser", "alpha")
        await tracker.untrack_repo("testuser", "alpha")
        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is None

    async def test_untrack_cascades_forks(
        self, tracker: TrackerService, db: Database
    ):
        """Untracking should cascade-delete associated forks."""
        repo = await tracker.track_repo("testuser", "alpha")
        # Manually insert a fork linked to this repo
        from forkhub.models import Fork

        fork = Fork(
            tracked_repo_id=repo.id,
            github_id=9999,
            owner="someone",
            full_name="someone/alpha",
            default_branch="main",
        )
        fork_dict = fork.model_dump()
        fork_dict["created_at"] = fork.created_at.isoformat()
        fork_dict["updated_at"] = fork.updated_at.isoformat()
        fork_dict["last_pushed_at"] = (
            fork.last_pushed_at.isoformat() if fork.last_pushed_at else None
        )
        await db.insert_fork(fork_dict)
        # Now untrack
        await tracker.untrack_repo("testuser", "alpha")
        fork_row = await db.get_fork(fork.id)
        assert fork_row is None

    async def test_untrack_nonexistent_is_noop(
        self, tracker: TrackerService, db: Database
    ):
        """Untracking a repo that isn't tracked should not raise."""
        await tracker.untrack_repo("nobody", "nothing")


# ---------------------------------------------------------------------------
# exclude / include
# ---------------------------------------------------------------------------


class TestExcludeInclude:
    async def test_exclude_sets_flag(
        self, tracker: TrackerService, db: Database
    ):
        """Excluding a repo should set excluded=True."""
        await tracker.track_repo("testuser", "alpha")
        await tracker.exclude_repo("testuser/alpha")
        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is not None
        assert row["excluded"] == 1  # SQLite stores bool as int

    async def test_include_clears_flag(
        self, tracker: TrackerService, db: Database
    ):
        """Including a previously excluded repo should set excluded=False."""
        await tracker.track_repo("testuser", "alpha")
        await tracker.exclude_repo("testuser/alpha")
        await tracker.include_repo("testuser/alpha")
        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is not None
        assert row["excluded"] == 0

    async def test_exclude_nonexistent_is_noop(
        self, tracker: TrackerService, db: Database
    ):
        """Excluding a non-tracked repo should not raise."""
        await tracker.exclude_repo("nobody/nothing")

    async def test_include_nonexistent_is_noop(
        self, tracker: TrackerService, db: Database
    ):
        """Including a non-tracked repo should not raise."""
        await tracker.include_repo("nobody/nothing")


# ---------------------------------------------------------------------------
# list_tracked_repos
# ---------------------------------------------------------------------------


class TestListTrackedRepos:
    async def test_list_all_non_excluded(
        self, tracker: TrackerService, db: Database
    ):
        """Listing repos should return only non-excluded repos."""
        await tracker.discover_owned_repos("testuser")
        result = await tracker.list_tracked_repos()
        assert len(result) == 2

    async def test_list_filtered_by_mode(
        self, tracker: TrackerService, db: Database
    ):
        """Listing with a mode filter should only return matching repos."""
        await tracker.discover_owned_repos("testuser")
        await tracker.track_repo(
            "upstream-org", "forked-lib", mode=TrackingMode.UPSTREAM
        )
        owned = await tracker.list_tracked_repos(mode=TrackingMode.OWNED)
        upstream = await tracker.list_tracked_repos(mode=TrackingMode.UPSTREAM)
        assert len(owned) == 2
        assert len(upstream) == 1
        assert upstream[0].tracking_mode == TrackingMode.UPSTREAM

    async def test_list_excludes_excluded(
        self, tracker: TrackerService, db: Database
    ):
        """Excluded repos should not appear in default listing."""
        await tracker.discover_owned_repos("testuser")
        await tracker.exclude_repo("testuser/alpha")
        result = await tracker.list_tracked_repos()
        assert len(result) == 1
        assert result[0].full_name == "testuser/beta"


# ---------------------------------------------------------------------------
# detect_upstream_repos
# ---------------------------------------------------------------------------


class TestDetectUpstreamRepos:
    async def test_detect_finds_parent_repos(
        self, tracker: TrackerService, db: Database
    ):
        """detect_upstream_repos should find forked repos and track their parents."""
        result = await tracker.detect_upstream_repos("testuser")
        assert len(result) == 1
        assert result[0].full_name == "upstream-org/forked-lib"
        assert result[0].tracking_mode == TrackingMode.UPSTREAM

    async def test_detect_skips_already_tracked_parents(
        self, tracker: TrackerService, db: Database
    ):
        """If the parent is already tracked, detect should skip it."""
        await tracker.track_repo(
            "upstream-org", "forked-lib", mode=TrackingMode.UPSTREAM
        )
        result = await tracker.detect_upstream_repos("testuser")
        assert len(result) == 0

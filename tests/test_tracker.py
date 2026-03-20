# ABOUTME: Tests for the TrackerService that manages repo discovery and tracking.
# ABOUTME: Uses a StubGitProvider with canned data instead of real GitHub API calls.

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from forkhub.models import TrackingMode
from forkhub.services.tracker import TrackerService
from tests.stubs import StubGitProvider

if TYPE_CHECKING:
    from forkhub.database import Database

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def provider() -> StubGitProvider:
    return StubGitProvider.with_testuser_data()


@pytest.fixture
def tracker(db: Database, provider: StubGitProvider) -> TrackerService:
    return TrackerService(db=db, provider=provider)


# ---------------------------------------------------------------------------
# discover_owned_repos
# ---------------------------------------------------------------------------


class TestDiscoverOwnedRepos:
    async def test_discover_adds_new_repos(self, tracker: TrackerService, db: Database):
        """Discovering repos for a user should insert them as tracked repos."""
        result = await tracker.discover_owned_repos("testuser")
        # The stub has 3 repos for testuser, but only 2 are non-forks
        # discover_owned_repos tracks non-fork repos as 'owned'
        assert len(result) == 2
        assert all(r.tracking_mode == TrackingMode.OWNED for r in result)
        names = {r.full_name for r in result}
        assert names == {"testuser/alpha", "testuser/beta"}

    async def test_discover_skips_already_tracked(self, tracker: TrackerService, db: Database):
        """Second call to discover should not duplicate repos."""
        await tracker.discover_owned_repos("testuser")
        second = await tracker.discover_owned_repos("testuser")
        # Second call should return empty since they're already tracked
        assert len(second) == 0
        # Database should still have exactly 2
        all_repos = await db.list_tracked_repos()
        assert len(all_repos) == 2

    async def test_discover_respects_excluded_flag(self, tracker: TrackerService, db: Database):
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
    async def test_track_repo_adds_watched(self, tracker: TrackerService, db: Database):
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

    async def test_track_repo_custom_mode(self, tracker: TrackerService, db: Database):
        """Tracking with a custom mode should be honored."""
        result = await tracker.track_repo("testuser", "alpha", mode=TrackingMode.UPSTREAM)
        assert result.tracking_mode == TrackingMode.UPSTREAM

    async def test_track_repo_raises_on_duplicate(self, tracker: TrackerService, db: Database):
        """Tracking an already-tracked repo should raise ValueError."""
        await tracker.track_repo("testuser", "alpha")
        with pytest.raises(ValueError, match="already tracked"):
            await tracker.track_repo("testuser", "alpha")


# ---------------------------------------------------------------------------
# untrack_repo
# ---------------------------------------------------------------------------


class TestUntrackRepo:
    async def test_untrack_removes_repo(self, tracker: TrackerService, db: Database):
        """Untracking should remove the repo from the database."""
        await tracker.track_repo("testuser", "alpha")
        await tracker.untrack_repo("testuser", "alpha")
        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is None

    async def test_untrack_cascades_forks(self, tracker: TrackerService, db: Database):
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

    async def test_untrack_nonexistent_is_noop(self, tracker: TrackerService, db: Database):
        """Untracking a repo that isn't tracked should not raise."""
        await tracker.untrack_repo("nobody", "nothing")


# ---------------------------------------------------------------------------
# exclude / include
# ---------------------------------------------------------------------------


class TestExcludeInclude:
    async def test_exclude_sets_flag(self, tracker: TrackerService, db: Database):
        """Excluding a repo should set excluded=True."""
        await tracker.track_repo("testuser", "alpha")
        await tracker.exclude_repo("testuser/alpha")
        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is not None
        assert row["excluded"] == 1  # SQLite stores bool as int

    async def test_include_clears_flag(self, tracker: TrackerService, db: Database):
        """Including a previously excluded repo should set excluded=False."""
        await tracker.track_repo("testuser", "alpha")
        await tracker.exclude_repo("testuser/alpha")
        await tracker.include_repo("testuser/alpha")
        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is not None
        assert row["excluded"] == 0

    async def test_exclude_nonexistent_is_noop(self, tracker: TrackerService, db: Database):
        """Excluding a non-tracked repo should not raise."""
        await tracker.exclude_repo("nobody/nothing")

    async def test_include_nonexistent_is_noop(self, tracker: TrackerService, db: Database):
        """Including a non-tracked repo should not raise."""
        await tracker.include_repo("nobody/nothing")


# ---------------------------------------------------------------------------
# list_tracked_repos
# ---------------------------------------------------------------------------


class TestListTrackedRepos:
    async def test_list_all_non_excluded(self, tracker: TrackerService, db: Database):
        """Listing repos should return only non-excluded repos."""
        await tracker.discover_owned_repos("testuser")
        result = await tracker.list_tracked_repos()
        assert len(result) == 2

    async def test_list_filtered_by_mode(self, tracker: TrackerService, db: Database):
        """Listing with a mode filter should only return matching repos."""
        await tracker.discover_owned_repos("testuser")
        await tracker.track_repo("upstream-org", "forked-lib", mode=TrackingMode.UPSTREAM)
        owned = await tracker.list_tracked_repos(mode=TrackingMode.OWNED)
        upstream = await tracker.list_tracked_repos(mode=TrackingMode.UPSTREAM)
        assert len(owned) == 2
        assert len(upstream) == 1
        assert upstream[0].tracking_mode == TrackingMode.UPSTREAM

    async def test_list_excludes_excluded(self, tracker: TrackerService, db: Database):
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
    async def test_detect_finds_parent_repos(self, tracker: TrackerService, db: Database):
        """detect_upstream_repos should find forked repos and track their parents."""
        result = await tracker.detect_upstream_repos("testuser")
        assert len(result) == 1
        assert result[0].full_name == "upstream-org/forked-lib"
        assert result[0].tracking_mode == TrackingMode.UPSTREAM

    async def test_detect_skips_already_tracked_parents(
        self, tracker: TrackerService, db: Database
    ):
        """If the parent is already tracked, detect should skip it."""
        await tracker.track_repo("upstream-org", "forked-lib", mode=TrackingMode.UPSTREAM)
        result = await tracker.detect_upstream_repos("testuser")
        assert len(result) == 0

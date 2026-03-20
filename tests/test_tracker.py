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
# untrack_repo
# ---------------------------------------------------------------------------


class TestUntrackRepo:
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
    async def test_exclude_and_include_nonexistent_are_noops(
        self, tracker: TrackerService, db: Database
    ):
        """Excluding or including a non-tracked repo should not raise."""
        await tracker.exclude_repo("nobody/nothing")
        await tracker.include_repo("nobody/nothing")


# ---------------------------------------------------------------------------
# detect_upstream_repos
# ---------------------------------------------------------------------------


class TestDetectUpstreamRepos:
    async def test_detect_skips_already_tracked_parents(
        self, tracker: TrackerService, db: Database
    ):
        """If the parent is already tracked, detect should skip it."""
        await tracker.track_repo("upstream-org", "forked-lib", mode=TrackingMode.UPSTREAM)
        result = await tracker.detect_upstream_repos("testuser")
        assert len(result) == 0

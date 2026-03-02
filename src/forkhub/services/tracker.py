# ABOUTME: Tracker service for repo discovery and management.
# ABOUTME: Handles track/untrack/exclude/include and auto-discovery of owned repos.

from __future__ import annotations

from typing import TYPE_CHECKING

from forkhub.models import TrackedRepo, TrackingMode

if TYPE_CHECKING:
    from forkhub.database import Database
    from forkhub.interfaces import GitProvider


class TrackerService:
    """Manages which repositories are tracked by ForkHub.

    Provides methods to discover owned repos, manually track/untrack repos,
    exclude/include repos from syncing, and detect upstream repos for forks.
    """

    def __init__(self, db: Database, provider: GitProvider) -> None:
        self._db = db
        self._provider = provider

    async def discover_owned_repos(self, username: str) -> list[TrackedRepo]:
        """Fetch user repos via GitProvider and insert non-fork repos as 'owned'.

        Skips repos that are already tracked (including excluded ones).
        Returns the list of newly tracked repos.
        """
        repo_infos = await self._provider.get_user_repos(username)
        added: list[TrackedRepo] = []

        for info in repo_infos:
            # Only track non-fork repos as owned
            if info.is_fork:
                continue

            # Skip if already tracked (check includes excluded repos)
            existing = await self._db.get_tracked_repo_by_name(info.full_name)
            if existing is not None:
                continue

            repo = TrackedRepo(
                github_id=info.github_id,
                owner=info.owner,
                name=info.name,
                full_name=info.full_name,
                tracking_mode=TrackingMode.OWNED,
                default_branch=info.default_branch,
                description=info.description,
            )
            await self._db.insert_tracked_repo(_repo_to_dict(repo))
            added.append(repo)

        return added

    async def track_repo(
        self,
        owner: str,
        repo: str,
        mode: TrackingMode = TrackingMode.WATCHED,
        depth: int = 1,
    ) -> TrackedRepo:
        """Add a repo to tracking by fetching metadata from the provider.

        Raises ValueError if the repo is already tracked.
        """
        full_name = f"{owner}/{repo}"
        existing = await self._db.get_tracked_repo_by_name(full_name)
        if existing is not None:
            raise ValueError(f"Repository '{full_name}' is already tracked")

        info = await self._provider.get_repo(owner, repo)
        tracked = TrackedRepo(
            github_id=info.github_id,
            owner=info.owner,
            name=info.name,
            full_name=info.full_name,
            tracking_mode=mode,
            default_branch=info.default_branch,
            description=info.description,
            fork_depth=depth,
        )
        await self._db.insert_tracked_repo(_repo_to_dict(tracked))
        return tracked

    async def untrack_repo(self, owner: str, repo: str) -> None:
        """Remove a repo from tracking. Cascade-deletes associated data.

        No-op if the repo is not tracked.
        """
        full_name = f"{owner}/{repo}"
        existing = await self._db.get_tracked_repo_by_name(full_name)
        if existing is None:
            return
        await self._db.delete_tracked_repo(existing["id"])

    async def exclude_repo(self, repo_name: str) -> None:
        """Set the excluded flag on a tracked repo. No-op if not found."""
        existing = await self._db.get_tracked_repo_by_name(repo_name)
        if existing is None:
            return
        existing["excluded"] = True
        await self._db.update_tracked_repo(existing)

    async def include_repo(self, repo_name: str) -> None:
        """Clear the excluded flag on a tracked repo. No-op if not found."""
        existing = await self._db.get_tracked_repo_by_name(repo_name)
        if existing is None:
            return
        existing["excluded"] = False
        await self._db.update_tracked_repo(existing)

    async def list_tracked_repos(
        self,
        mode: TrackingMode | None = None,
        include_excluded: bool = False,
    ) -> list[TrackedRepo]:
        """Return tracked repos, optionally filtered by mode.

        Excluded repos are hidden by default.
        """
        mode_str = str(mode) if mode is not None else None
        rows = await self._db.list_tracked_repos(
            mode=mode_str, include_excluded=include_excluded
        )
        return [TrackedRepo(**row) for row in rows]

    async def detect_upstream_repos(self, username: str) -> list[TrackedRepo]:
        """Find repos the user has forked and track their parents as 'upstream'.

        Returns the list of newly tracked upstream repos.
        """
        repo_infos = await self._provider.get_user_repos(username)
        added: list[TrackedRepo] = []

        for info in repo_infos:
            if not info.is_fork or info.parent_full_name is None:
                continue

            # Skip if parent is already tracked
            existing = await self._db.get_tracked_repo_by_name(info.parent_full_name)
            if existing is not None:
                continue

            # Fetch parent repo metadata
            parts = info.parent_full_name.split("/")
            parent_owner, parent_name = parts[0], parts[1]
            parent_info = await self._provider.get_repo(parent_owner, parent_name)

            tracked = TrackedRepo(
                github_id=parent_info.github_id,
                owner=parent_info.owner,
                name=parent_info.name,
                full_name=parent_info.full_name,
                tracking_mode=TrackingMode.UPSTREAM,
                default_branch=parent_info.default_branch,
                description=parent_info.description,
            )
            await self._db.insert_tracked_repo(_repo_to_dict(tracked))
            added.append(tracked)

        return added


def _repo_to_dict(repo: TrackedRepo) -> dict:
    """Convert a TrackedRepo model to a dict suitable for database insertion."""
    d = repo.model_dump()
    d["created_at"] = repo.created_at.isoformat()
    d["last_synced_at"] = repo.last_synced_at.isoformat() if repo.last_synced_at else None
    return d

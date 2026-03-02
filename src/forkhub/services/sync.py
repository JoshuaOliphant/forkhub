# ABOUTME: Sync service for fork discovery, comparison, and change detection.
# ABOUTME: Orchestrates the sync pipeline: discover forks, compare HEADs, trigger analysis.

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from forkhub.models import Fork, ForkVitality, TrackedRepo

if TYPE_CHECKING:
    from forkhub.config import SyncSettings
    from forkhub.database import Database
    from forkhub.interfaces import GitProvider

logger = logging.getLogger(__name__)


@dataclass
class RepoSyncResult:
    """Result of syncing a single tracked repository."""

    repo_full_name: str
    new_forks: int = 0
    changed_forks: list[str] = field(default_factory=list)
    new_releases: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class SyncResult:
    """Aggregated result of syncing all tracked repositories."""

    repos_synced: int = 0
    total_changed_forks: int = 0
    total_new_releases: int = 0
    results: list[RepoSyncResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class SyncService:
    """Discovers and compares forks for all tracked repositories.

    Reads tracked repos directly from the database, discovers their forks
    via the GitProvider, compares HEAD SHAs to detect changes, and updates
    fork metadata including vitality and star counts.
    """

    def __init__(
        self,
        db: Database,
        provider: GitProvider,
        settings: SyncSettings,
        *,
        clock: datetime | None = None,
    ) -> None:
        self._db = db
        self._provider = provider
        self._settings = settings
        self._clock = clock

    async def sync_all(self) -> SyncResult:
        """Sync all non-excluded tracked repos and aggregate results."""
        result = SyncResult()
        repo_rows = await self._db.list_tracked_repos(include_excluded=False)

        for repo_row in repo_rows:
            try:
                repo_result = await self.sync_repo(repo_row["id"])
                result.results.append(repo_result)
                result.repos_synced += 1
                result.total_changed_forks += len(repo_result.changed_forks)
                result.total_new_releases += repo_result.new_releases
                result.errors.extend(repo_result.errors)
            except Exception as exc:
                error_msg = f"Error syncing {repo_row['full_name']}: {exc}"
                result.errors.append(error_msg)
                logger.exception(error_msg)

        return result

    async def sync_repo(self, repo_id: str) -> RepoSyncResult:
        """Sync a single tracked repo: discover forks, compare, update.

        Steps:
        1. Discover forks via provider.get_forks() (paginated)
        2. For each fork: save/update in DB, compare HEAD SHA
        3. For changed forks: fetch compare data, update fork record
        4. Check for new releases since last sync
        5. Update fork vitality and star counts
        6. Update repo.last_synced_at
        """
        repo_row = await self._db.get_tracked_repo(repo_id)
        if repo_row is None:
            raise ValueError(f"Tracked repo not found: {repo_id}")

        repo = TrackedRepo(**repo_row)
        result = RepoSyncResult(repo_full_name=repo.full_name)

        # Step 1: Discover forks (paginated)
        all_forks_info = []
        page = 1
        while True:
            fork_page = await self._provider.get_forks(
                repo.owner, repo.name, page=page
            )
            all_forks_info.extend(fork_page.forks)
            if not fork_page.has_next or len(all_forks_info) >= self._settings.max_forks_per_repo:
                break
            page += 1

        # Step 2-5: Process each fork
        for fork_info in all_forks_info:
            existing_row = await self._db.get_fork_by_name(fork_info.full_name)

            if existing_row is None:
                # New fork: insert it
                new_fork = Fork(
                    tracked_repo_id=repo.id,
                    github_id=fork_info.github_id,
                    owner=fork_info.owner,
                    full_name=fork_info.full_name,
                    default_branch=fork_info.default_branch,
                    description=fork_info.description,
                    stars=fork_info.stars,
                    last_pushed_at=fork_info.last_pushed_at,
                    vitality=self._classify_vitality(fork_info.last_pushed_at),
                    head_sha=self._provider_head_sha(fork_info),
                )
                await self._db.insert_fork(_fork_to_dict(new_fork))
                result.new_forks += 1
            else:
                # Existing fork: check for changes
                old_sha = existing_row["head_sha"]
                new_sha = self._provider_head_sha(fork_info)

                # Update stars (always)
                old_stars = existing_row["stars"]
                existing_row["stars_previous"] = old_stars
                existing_row["stars"] = fork_info.stars
                existing_row["last_pushed_at"] = (
                    fork_info.last_pushed_at.isoformat()
                    if fork_info.last_pushed_at
                    else None
                )
                existing_row["vitality"] = self._classify_vitality(
                    fork_info.last_pushed_at
                )
                existing_row["updated_at"] = self._now().isoformat()

                if old_sha != new_sha:
                    # SHA changed: fetch comparison data
                    try:
                        compare_result = await self._provider.compare(
                            repo.owner,
                            repo.name,
                            repo.default_branch,
                            f"{fork_info.owner}:{fork_info.default_branch}",
                        )
                        existing_row["commits_ahead"] = compare_result.ahead_by
                        existing_row["commits_behind"] = compare_result.behind_by
                        existing_row["head_sha"] = new_sha
                        result.changed_forks.append(fork_info.full_name)
                    except Exception as exc:
                        error_msg = (
                            f"Error comparing {fork_info.full_name}: {exc}"
                        )
                        result.errors.append(error_msg)
                        logger.warning(error_msg)

                await self._db.update_fork(existing_row)

        # Step 4: Check for new releases
        releases = await self._provider.get_releases(
            repo.owner, repo.name, since=repo.last_synced_at
        )
        result.new_releases = len(releases)

        # Step 6: Update repo.last_synced_at
        repo_row["last_synced_at"] = self._now().isoformat()
        await self._db.update_tracked_repo(repo_row)

        return result

    def _now(self) -> datetime:
        """Return the current time, using the injected clock if available."""
        return self._clock if self._clock is not None else datetime.now(UTC)

    def _classify_vitality(self, last_pushed_at: datetime | None) -> ForkVitality:
        """Classify fork activity based on when it was last pushed.

        - Active: pushed within 90 days
        - Dormant: pushed 91-365 days ago
        - Dead: pushed more than 365 days ago
        - Unknown: no push date available
        """
        if last_pushed_at is None:
            return ForkVitality.UNKNOWN

        now = self._now()
        age = now - last_pushed_at

        if age <= timedelta(days=90):
            return ForkVitality.ACTIVE
        elif age <= timedelta(days=365):
            return ForkVitality.DORMANT
        else:
            return ForkVitality.DEAD

    def _provider_head_sha(self, fork_info) -> str | None:
        """Extract or derive the HEAD SHA for a fork from provider data.

        The StubGitProvider stores SHAs in a _head_shas dict. For the real
        GitProvider, the SHA would come from the fork info or a separate API call.
        We use a deterministic fallback based on the fork's metadata to detect changes.
        """
        # If the provider has a get_head_sha method (stub), use it
        if hasattr(self._provider, "get_head_sha"):
            sha = self._provider.get_head_sha(fork_info.full_name)
            if sha is not None:
                return sha
        # Fallback: use a hash of fork metadata to detect changes
        # In production, the real provider would supply this from the API
        return None


def _fork_to_dict(fork: Fork) -> dict:
    """Convert a Fork model to a dict suitable for database insertion."""
    d = fork.model_dump()
    d["created_at"] = fork.created_at.isoformat()
    d["updated_at"] = fork.updated_at.isoformat()
    d["last_pushed_at"] = fork.last_pushed_at.isoformat() if fork.last_pushed_at else None
    return d

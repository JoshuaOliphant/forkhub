# ABOUTME: Public API entry point for the ForkHub library.
# ABOUTME: Exposes the ForkHub class as the main interface for consumers.

"""ForkHub — Monitor GitHub fork constellations with AI-powered analysis."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from forkhub.config import ForkHubSettings
    from forkhub.database import Database
    from forkhub.interfaces import EmbeddingProvider, GitProvider, NotificationBackend
    from forkhub.models import (
        BackfillResult,
        Cluster,
        DeliveryResult,
        Digest,
        Fork,
        TrackedRepo,
        TrackingMode,
    )
    from forkhub.services.sync import SyncResult

__version__ = "0.1.0"


class ForkHub:
    """Main entry point for the ForkHub library.

    Composes all services and exposes a clean async API.
    All providers are injectable via Protocol interfaces.
    """

    def __init__(
        self,
        settings: ForkHubSettings | None = None,
        git_provider: GitProvider | None = None,
        notification_backends: list[NotificationBackend] | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        db: Database | None = None,
    ) -> None:
        from forkhub.config import get_db_path, load_settings
        from forkhub.database import Database as _Database
        from forkhub.notifications.console import ConsoleBackend
        from forkhub.services.cluster import ClusterService
        from forkhub.services.digest import DigestService
        from forkhub.services.sync import SyncService
        from forkhub.services.tracker import TrackerService

        self._settings = settings or load_settings()
        self._db = db or _Database(get_db_path(self._settings))
        self._provider = git_provider or self._build_default_provider()
        self._backends = notification_backends or [ConsoleBackend()]
        self._embedding_provider = embedding_provider or self._build_default_embedding_provider()

        self._tracker = TrackerService(self._db, self._provider)
        self._sync = SyncService(self._db, self._provider, self._settings.sync)
        self._cluster = ClusterService(self._db, self._embedding_provider)
        self._digest = DigestService(self._db, self._backends)

    def _build_default_provider(self) -> GitProvider:
        """Build the default GitHubProvider using settings."""
        from forkhub.providers.github import GitHubProvider

        return GitHubProvider(self._settings.github.token)

    def _build_default_embedding_provider(self) -> EmbeddingProvider:
        """Build the default local embedding provider."""
        from forkhub.embeddings.local import LocalEmbeddingProvider

        return LocalEmbeddingProvider()

    async def __aenter__(self) -> ForkHub:
        await self._db.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._db.close()

    # --- Public API ---

    async def init(self, username: str) -> list[TrackedRepo]:
        """First-time setup: discover owned repos, detect upstreams."""
        owned = await self._tracker.discover_owned_repos(username)
        upstream = await self._tracker.detect_upstream_repos(username)
        return owned + upstream

    async def track(
        self,
        owner: str,
        repo: str,
        mode: TrackingMode | None = None,
        depth: int = 1,
    ) -> TrackedRepo:
        """Add a repository to tracking."""
        from forkhub.models import TrackingMode as _TrackingMode

        effective_mode = mode if mode is not None else _TrackingMode.WATCHED
        return await self._tracker.track_repo(owner, repo, mode=effective_mode, depth=depth)

    async def untrack(self, owner: str, repo: str) -> None:
        """Stop tracking a repository."""
        await self._tracker.untrack_repo(owner, repo)

    async def get_repos(self, mode: TrackingMode | None = None) -> list[TrackedRepo]:
        """List tracked repositories, optionally filtered by mode."""
        return await self._tracker.list_tracked_repos(mode=mode)

    async def get_forks(self, owner: str, repo: str, active_only: bool = False) -> list[Fork]:
        """Get forks for a tracked repository."""
        from forkhub.models import Fork as _Fork
        from forkhub.models import ForkVitality as _ForkVitality

        full_name = f"{owner}/{repo}"
        repo_row = await self._db.get_tracked_repo_by_name(full_name)
        if repo_row is None:
            raise ValueError(f"Repository {full_name} is not tracked")

        vitality = str(_ForkVitality.ACTIVE) if active_only else None
        fork_rows = await self._db.list_forks(repo_row["id"], vitality=vitality)
        return [_Fork(**row) for row in fork_rows]

    async def sync(self, repo: str | None = None) -> SyncResult:
        """Run sync pipeline: discover forks, compare changes."""
        from forkhub.services.sync import SyncResult as _SyncResult

        if repo:
            owner, name = repo.split("/", 1)
            full_name = f"{owner}/{name}"
            repo_row = await self._db.get_tracked_repo_by_name(full_name)
            if repo_row is None:
                raise ValueError(f"Repository {full_name} is not tracked")
            result = await self._sync.sync_repo(repo_row["id"])
            return _SyncResult(
                repos_synced=1,
                total_changed_forks=len(result.changed_forks),
                total_new_releases=result.new_releases,
                results=[result],
                errors=result.errors,
            )
        return await self._sync.sync_all()

    async def get_clusters(self, owner: str, repo: str, min_size: int = 2) -> list[Cluster]:
        """Get signal clusters for a repository."""
        full_name = f"{owner}/{repo}"
        repo_row = await self._db.get_tracked_repo_by_name(full_name)
        if repo_row is None:
            raise ValueError(f"Repository {full_name} is not tracked")
        return await self._cluster.get_clusters(repo_row["id"], min_size=min_size)

    async def generate_digest(
        self,
        since: datetime | None = None,
        repo: str | None = None,
    ) -> Digest:
        """Generate a digest from recent signals."""
        from forkhub.models import DigestConfig

        config = DigestConfig()
        if repo:
            owner, name = repo.split("/", 1)
            repo_row = await self._db.get_tracked_repo_by_name(f"{owner}/{name}")
            if repo_row:
                config = DigestConfig(tracked_repo_id=repo_row["id"])
        return await self._digest.generate_digest(config, since=since)

    async def deliver_digest(self, digest: Digest) -> list[DeliveryResult]:
        """Deliver a digest via configured backends."""
        return await self._digest.deliver_digest(digest)

    async def backfill(
        self,
        repo: str | None = None,
        *,
        since: datetime | None = None,
        dry_run: bool = False,
        repo_path: Path | None = None,
        min_significance: int = 5,
        max_attempts: int = 10,
        auto_fix_tests: bool = True,
        test_command: str = "uv run pytest -x --tb=short -q",
    ) -> BackfillResult:
        """Run the agentic backfill loop to cherry-pick valuable fork changes.

        Evaluates high-significance signals from fork analysis, attempts to
        apply their patches to the local repo, runs the test suite to score
        the result, and creates candidate branches for accepted patches.
        """
        from forkhub.services.backfill import BackfillService

        backfill_service = BackfillService(
            db=self._db,
            provider=self._provider,
            repo_path=repo_path,
            test_command=test_command,
            min_significance=min_significance,
            max_attempts=max_attempts,
            auto_fix_tests=auto_fix_tests,
        )

        if repo:
            owner, name = repo.split("/", 1)
            repo_row = await self._db.get_tracked_repo_by_name(f"{owner}/{name}")
            if repo_row is None:
                raise ValueError(f"Repository {repo} is not tracked")
            return await backfill_service.run_backfill(
                repo_row["id"], since=since, dry_run=dry_run
            )

        # Backfill all tracked repos
        from forkhub.models import BackfillResult as _BackfillResult

        combined = _BackfillResult()
        repos = await self._db.list_tracked_repos()
        for repo_row in repos:
            result = await backfill_service.run_backfill(
                repo_row["id"], since=since, dry_run=dry_run
            )
            combined.total_evaluated += result.total_evaluated
            combined.attempted += result.attempted
            combined.accepted += result.accepted
            combined.patch_failed += result.patch_failed
            combined.tests_failed += result.tests_failed
            combined.conflicts += result.conflicts
            combined.branches_created.extend(result.branches_created)
        return combined

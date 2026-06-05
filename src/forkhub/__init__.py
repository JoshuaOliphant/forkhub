# ABOUTME: Public API entry point for the ForkHub library.
# ABOUTME: Exposes the ForkHub class as the main interface for consumers.

"""ForkHub — Monitor GitHub fork constellations with AI-powered analysis."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from forkhub.config import ForkHubSettings
    from forkhub.database import Database
    from forkhub.interfaces import (
        Analyzer,
        EmbeddingProvider,
        GitProvider,
        NotificationBackend,
        TestFixer,
    )
    from forkhub.models import (
        BackfillAttempt as BackfillAttempt,
    )
    from forkhub.models import (
        BackfillResult,
        Cluster,
        DeliveryResult,
        Digest,
        Fork,
        TrackedRepo,
        TrackingMode,
    )
    from forkhub.models import (
        BackfillStatus as BackfillStatus,
    )
    from forkhub.services.sync import ReconcileResult, SyncResult

logger = logging.getLogger(__name__)

__version__ = "0.4.0"


def _build_default_embedding_provider() -> EmbeddingProvider:
    """Construct the default embedding provider (LocalEmbeddingProvider).

    Single source of truth so both `ForkHub.__init__` and the CLI pick
    up the same implementation when new providers are wired in later.
    """
    from forkhub.embeddings.local import LocalEmbeddingProvider

    return LocalEmbeddingProvider()


def _build_default_analyzer(
    db: Database,
    provider: GitProvider,
    settings: ForkHubSettings,
    embedding_provider: EmbeddingProvider | None = None,
) -> Analyzer | None:
    """Construct the default `ClaudeAnalyzer`, or return None when the
    `[claude]` optional extra is not installed.

    Single source of truth so both `ForkHub.__init__` and the CLI share
    the same construction and graceful-degradation behavior. Callers
    that already have an embedding provider can pass it in to avoid
    re-instantiating the default.
    """
    if embedding_provider is None:
        embedding_provider = _build_default_embedding_provider()

    try:
        from forkhub.agent.runner import ClaudeAnalyzer

        return ClaudeAnalyzer(
            db=db,
            provider=provider,
            embedding_provider=embedding_provider,
            settings=settings,
        )
    except ImportError:
        logger.info(
            "Analyzer skipped: [claude] extra not installed. "
            "Discovery will still run but no signals will be generated."
        )
        return None


def _build_default_test_fixer(settings: ForkHubSettings) -> TestFixer | None:
    """Construct the default `ClaudeTestFixer`, or return None when the
    `[claude]` optional extra is not installed.

    Single source of truth so both `ForkHub.backfill` and the CLI share
    the same construction and graceful-degradation behavior. Mirrors
    `_build_default_analyzer`: the test fixer runs on the cheaper digest
    model with a fraction of the analysis budget.
    """
    try:
        from forkhub.agent.test_fixer import ClaudeTestFixer

        return ClaudeTestFixer(
            model=settings.anthropic.digest_model,
            budget_usd=settings.anthropic.analysis_budget_usd / 5,
        )
    except ImportError:
        logger.info(
            "Test fixer skipped: [claude] extra not installed. "
            "Backfill will still run but failing tests won't be auto-fixed."
        )
        return None


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
        *,
        auto_analyze: bool = True,
        analyzer: Analyzer | None = None,
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
        self._backends: list[NotificationBackend] = (
            notification_backends if notification_backends is not None else [ConsoleBackend()]
        )
        self._embedding_provider = embedding_provider or self._build_default_embedding_provider()

        # Build the default analyzer via the shared factory when one
        # wasn't injected and `auto_analyze` is enabled.
        if analyzer is None and auto_analyze:
            analyzer = _build_default_analyzer(
                db=self._db,
                provider=self._provider,
                embedding_provider=self._embedding_provider,
                settings=self._settings,
            )
        self._analyzer: Analyzer | None = analyzer

        self._tracker = TrackerService(self._db, self._provider)
        self._sync = SyncService(
            self._db, self._provider, self._settings.sync, analyzer=self._analyzer
        )
        self._cluster = ClusterService(self._db, self._embedding_provider)
        self._digest = DigestService(self._db, self._backends)

    def _build_default_provider(self) -> GitProvider:
        """Build the default GitHubProvider using settings."""
        from forkhub.providers.github import GitHubProvider

        return GitHubProvider(self._settings.github.token)

    def _build_default_embedding_provider(self) -> EmbeddingProvider:
        """Build the default local embedding provider."""
        return _build_default_embedding_provider()

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
                total_signals_generated=result.signals_generated,
                results=[result],
                errors=result.errors,
            )
        return await self._sync.sync_all(
            username=self._settings.github.username or None,
            reconcile=True,
            tracker_service=self._tracker,
        )

    async def reconcile(self) -> ReconcileResult:
        """Health-check inaccessible repos and auto-discover new owned repos."""
        return await self._sync.reconcile(
            username=self._settings.github.username or None,
            tracker_service=self._tracker,
        )

    async def retry_repo(self, owner: str, repo: str) -> None:
        """Reset an inaccessible repo's sync_status back to ok for retry."""
        from forkhub.models import SyncStatus

        full_name = f"{owner}/{repo}"
        repo_row = await self._db.get_tracked_repo_by_name(full_name)
        if repo_row is None:
            raise ValueError(f"Repository {full_name} is not tracked")
        repo_row["sync_status"] = str(SyncStatus.OK)
        repo_row["last_sync_error"] = None
        await self._db.update_tracked_repo(repo_row)

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
        auto_fix_tests: bool = False,  # Enable when agentic test fixer is implemented
        test_command: str = "uv run pytest -x --tb=short -q",
    ) -> BackfillResult:
        """Run the agentic backfill loop to cherry-pick valuable fork changes.

        Evaluates high-significance signals from fork analysis, attempts to
        apply their patches to the local repo, runs the test suite to score
        the result, and creates candidate branches for accepted patches.
        """
        from forkhub.services.backfill import BackfillService

        # Build the test fixer via the shared factory when the caller opted
        # in. The factory owns graceful degradation for a missing [claude]
        # extra; BackfillService tolerates a None fixer (logs and skips).
        test_fixer = _build_default_test_fixer(self._settings) if auto_fix_tests else None

        backfill_service = BackfillService(
            db=self._db,
            provider=self._provider,
            repo_path=repo_path,
            test_command=test_command,
            min_significance=min_significance,
            max_attempts=max_attempts,
            auto_fix_tests=auto_fix_tests,
            test_fixer=test_fixer,
        )

        repo_id = None
        if repo:
            owner, name = repo.split("/", 1)
            repo_row = await self._db.get_tracked_repo_by_name(f"{owner}/{name}")
            if repo_row is None:
                raise ValueError(f"Repository {repo} is not tracked")
            repo_id = repo_row["id"]

        return await backfill_service.run_backfill_all(
            since=since, dry_run=dry_run, repo_id=repo_id
        )

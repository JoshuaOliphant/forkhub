# ABOUTME: Sync service for fork discovery, comparison, and change detection.
# ABOUTME: Orchestrates the sync pipeline: discover forks, compare HEADs, trigger analysis.

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from forkhub.models import Fork, ForkVitality, SyncStatus, TrackedRepo

if TYPE_CHECKING:
    from forkhub.config import SyncSettings
    from forkhub.database import Database
    from forkhub.interfaces import Analyzer, GitProvider
    from forkhub.models import ForkInfo
    from forkhub.services.tracker import TrackerService

logger = logging.getLogger(__name__)


@dataclass
class ReconcileResult:
    """Result of reconciling tracked repos against actual GitHub state."""

    repos_recovered: list[str] = field(default_factory=list)
    repos_still_inaccessible: list[str] = field(default_factory=list)
    new_repos_discovered: list[str] = field(default_factory=list)


@dataclass
class RepoSyncResult:
    """Result of syncing a single tracked repository."""

    repo_full_name: str
    new_forks: int = 0
    changed_forks: list[str] = field(default_factory=list)
    new_releases: int = 0
    signals_generated: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class SyncResult:
    """Aggregated result of syncing all tracked repositories."""

    repos_synced: int = 0
    total_changed_forks: int = 0
    total_new_releases: int = 0
    total_signals_generated: int = 0
    results: list[RepoSyncResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    reconcile: ReconcileResult | None = None


def _set_sync_status(
    row: dict,
    status: SyncStatus,
    error: str | None = None,
) -> None:
    """Set sync_status and last_sync_error together, maintaining their invariant."""
    row["sync_status"] = str(status)
    row["last_sync_error"] = error


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
        analyzer: Analyzer | None = None,
    ) -> None:
        self._db = db
        self._provider = provider
        self._settings = settings
        self._clock = clock
        self._analyzer = analyzer

    async def sync_all(
        self,
        username: str | None = None,
        reconcile: bool = True,
        tracker_service: TrackerService | None = None,
    ) -> SyncResult:
        """Sync all eligible tracked repos and aggregate results.

        Optionally runs reconciliation when username is provided.
        """
        result = SyncResult()

        # Run reconciliation if username is provided and reconcile is enabled
        if reconcile and username:
            try:
                result.reconcile = await self.reconcile(
                    username=username,
                    tracker_service=tracker_service,
                )
            except Exception as exc:
                logger.error("Reconciliation failed, proceeding with sync: %s", exc)
                result.errors.append(f"Reconciliation failed: {exc}")

        repo_rows = await self._db.list_tracked_repos(include_excluded=False)

        for repo_row in repo_rows:
            # Skip inaccessible repos — they require explicit reconciliation or retry
            if repo_row.get("sync_status") == str(SyncStatus.INACCESSIBLE):
                continue

            try:
                repo_result = await self.sync_repo(repo_row["id"])
                result.results.append(repo_result)
                result.repos_synced += 1
                result.total_changed_forks += len(repo_result.changed_forks)
                result.total_new_releases += repo_result.new_releases
                result.total_signals_generated += repo_result.signals_generated
                result.errors.extend(repo_result.errors)
            except Exception as exc:
                error_msg = f"Error syncing {repo_row['full_name']}: {exc}"
                result.errors.append(error_msg)
                logger.exception(error_msg)

        return result

    async def reconcile(
        self,
        username: str | None = None,
        tracker_service: TrackerService | None = None,
    ) -> ReconcileResult:
        """Reconcile tracked repos against actual GitHub state.

        1. Health-check repos marked inaccessible: try get_repo(), reset if accessible.
        2. Auto-discover new owned repos if both username and tracker_service are provided.
        """
        result = ReconcileResult()

        # Phase 1: Health-check inaccessible repos
        inaccessible_rows = await self._db.list_tracked_repos(
            sync_status=str(SyncStatus.INACCESSIBLE),
            include_excluded=True,
        )
        for row in inaccessible_rows:
            try:
                await self._provider.get_repo(row["owner"], row["name"])
                # Repo is accessible again — reset status
                _set_sync_status(row, SyncStatus.OK)
                await self._db.update_tracked_repo(row)
                result.repos_recovered.append(row["full_name"])
                logger.info("Repo %s is accessible again", row["full_name"])
            except Exception as exc:
                result.repos_still_inaccessible.append(row["full_name"])
                status = getattr(exc, "status_code", None)
                if status in (403, 404):
                    logger.debug("Repo %s still inaccessible (HTTP %s)", row["full_name"], status)
                else:
                    logger.warning(
                        "Unexpected error health-checking repo %s: %s",
                        row["full_name"],
                        exc,
                    )

        # Phase 2: Auto-discover new owned repos
        if username and tracker_service is not None:
            try:
                new_repos = await tracker_service.discover_owned_repos(username)
                result.new_repos_discovered = [r.full_name for r in new_repos]
            except Exception as exc:
                logger.error("Failed to discover owned repos for %s: %s", username, exc)

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
        try:
            while True:
                fork_page = await self._provider.get_forks(repo.owner, repo.name, page=page)
                all_forks_info.extend(fork_page.forks)
                at_limit = len(all_forks_info) >= self._settings.max_forks_per_repo
                if not fork_page.has_next or at_limit:
                    break
                page += 1
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status in (403, 404):
                _set_sync_status(repo_row, SyncStatus.INACCESSIBLE, str(exc))
                await self._db.update_tracked_repo(repo_row)
                logger.warning("Repo %s is inaccessible (HTTP %s)", repo.full_name, status)
                result.errors.append(f"Repo {repo.full_name} is inaccessible (HTTP {status})")
                return result
            else:
                _set_sync_status(repo_row, SyncStatus.ERROR, str(exc))
                await self._db.update_tracked_repo(repo_row)
                logger.warning("Repo %s sync error: %s", repo.full_name, exc)
                result.errors.append(f"Repo {repo.full_name} sync error: {exc}")
                return result

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
                )

                # Every newly discovered fork is compared and baselined on
                # first sight — regardless of vitality. The product's
                # canonical scenario is a dormant upstream whose forks are
                # diverged-but-quiet (their pushed_at never advances again),
                # so a vitality gate here made dead/dormant divergence
                # invisible forever. One compare + one head_sha fetch per
                # fork at discovery is ~2 calls/fork, well within the 4000/hr
                # budget. The head_sha baseline is what makes subsequent
                # syncs cheap (see the existing-fork branch below).
                try:
                    compare_result = await self._provider.compare(
                        repo.owner,
                        repo.name,
                        repo.default_branch,
                        f"{fork_info.owner}:{fork_info.default_branch}",
                    )
                    new_fork.commits_ahead = compare_result.ahead_by
                    new_fork.commits_behind = compare_result.behind_by
                    if compare_result.ahead_by > 0:
                        result.changed_forks.append(fork_info.full_name)
                except Exception as exc:
                    # Record to result.errors so callers can tell something
                    # failed, not just hope they're reading the warning log.
                    error_msg = f"Error comparing new fork {fork_info.full_name}: {exc}"
                    result.errors.append(error_msg)
                    logger.warning(error_msg)

                # Establish the head_sha baseline even if compare failed —
                # a populated baseline is what lets future syncs skip this
                # fork when nothing changed. A SHA fetch failure is tolerated
                # (None baseline retried next sync).
                new_fork.head_sha = await self._fetch_head_sha(fork_info)

                await self._db.insert_fork(_fork_to_dict(new_fork))
                result.new_forks += 1
            else:
                # Existing fork: check for changes.
                # NB: Read last_pushed_at / head_sha BEFORE overwriting below.
                changed = self._has_fork_changed(fork_info, existing_row)
                # A NULL stored head_sha means this fork has no baseline yet
                # (an earlier SHA fetch failed). Compare once to catch it up. A
                # row whose SHA fetch SUCCEEDS is populated and never
                # re-triggers this branch — zero extra calls on later syncs
                # (the /forks listing stays the only bulk call). A row whose
                # SHA fetch PERSISTENTLY FAILS stays NULL and keeps re-comparing
                # every sync (an accepted residual, see forkhub-lgh) — but it no
                # longer re-triggers the analyzer: the compare-success path
                # below only reports the fork as changed when there is real
                # divergence evidence.
                needs_baseline = existing_row.get("head_sha") is None

                # Update stars (always)
                old_stars = existing_row["stars"]
                existing_row["stars_previous"] = old_stars
                existing_row["stars"] = fork_info.stars
                existing_row["last_pushed_at"] = (
                    fork_info.last_pushed_at.isoformat() if fork_info.last_pushed_at else None
                )
                existing_row["vitality"] = self._classify_vitality(fork_info.last_pushed_at)
                existing_row["updated_at"] = self._now().isoformat()

                if changed or needs_baseline:
                    prior_sha = existing_row.get("head_sha")
                    prior_ahead = existing_row.get("commits_ahead")
                    try:
                        compare_result = await self._provider.compare(
                            repo.owner,
                            repo.name,
                            repo.default_branch,
                            f"{fork_info.owner}:{fork_info.default_branch}",
                        )
                        existing_row["commits_ahead"] = compare_result.ahead_by
                        existing_row["commits_behind"] = compare_result.behind_by
                    except Exception as exc:
                        error_msg = f"Error comparing {fork_info.full_name}: {exc}"
                        result.errors.append(error_msg)
                        logger.warning(error_msg)
                    else:
                        # Compare succeeded: refresh the head_sha baseline.
                        # A SHA fetch failure must not create a partial-state
                        # write, so head_sha is only overwritten when a real
                        # SHA comes back.
                        new_sha = await self._fetch_head_sha(fork_info)
                        if new_sha is not None:
                            existing_row["head_sha"] = new_sha
                            # The SHA is the authoritative change-detector:
                            # report only when it actually moved.
                            diverged = new_sha != prior_sha
                        else:
                            # SHA unavailable (fetch failed). A persistent
                            # failure keeps head_sha NULL, so this fork would
                            # re-enter the baseline branch every sync; gate on
                            # coarser divergence evidence (a real pushed_at
                            # change or a shift in commits_ahead vs the stored
                            # baseline) so it is not re-sent to the analyzer
                            # every sync. commits_ahead is persisted below, so
                            # the next sync compares against this run's value.
                            diverged = changed or compare_result.ahead_by != prior_ahead
                        if diverged:
                            result.changed_forks.append(fork_info.full_name)

                await self._db.update_fork(existing_row)

        # Step 4: Check for new releases
        releases = await self._provider.get_releases(
            repo.owner, repo.name, since=repo.last_synced_at
        )
        result.new_releases = len(releases)

        # Step 5: Run the analyzer on changed forks + new releases when
        # one is configured. Wrapped in try/except so analyzer failures
        # don't abort the sync — discovery data is valuable even without
        # classification. `CancelledError` is re-raised so Ctrl-C and
        # shutdown semantics stay intact.
        if self._analyzer is not None and (result.changed_forks or releases):
            # Build Fork models OUTSIDE the analyzer try/except so any
            # row→model conversion bug surfaces as a distinct error
            # instead of being attributed to the analyzer.
            changed_fork_models: list[Fork] = []
            for name in result.changed_forks:
                row = await self._db.get_fork_by_name(name)
                if row is not None:
                    changed_fork_models.append(_fork_from_row(row))

            try:
                signals = await self._analyzer.analyze(repo, changed_fork_models, releases)
                result.signals_generated = len(signals)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error_msg = (
                    f"Analyzer failed for {repo.full_name} "
                    f"({len(changed_fork_models)} forks, {len(releases)} releases): "
                    f"{type(exc).__name__}: {exc}"
                )
                logger.exception(error_msg)
                result.errors.append(error_msg)

        # Successful sync — clear any previous error state
        _set_sync_status(repo_row, SyncStatus.OK)

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

    def _has_fork_changed(self, fork_info: ForkInfo, existing_row: dict) -> bool:
        """Return True if the fork *may* have changed since the last sync.

        This is the cheap, zero-cost pre-filter: it compares last_pushed_at,
        which the GitHub /forks listing always returns and which advances when
        the branch head moves. It deliberately does NOT fetch a HEAD SHA — a
        per-fork SHA call on every sync would blow the API budget. The SHA is
        fetched only after we've decided to compare, and it serves as the
        authoritative confirmation of divergence (see sync_repo).

        Caller must read existing_row["last_pushed_at"] BEFORE overwriting it.
        """
        # Compare last_pushed_at strings. Both sides are ISO-format strings
        # produced by datetime.isoformat(), so string equality is safe.
        old_pushed = existing_row.get("last_pushed_at")
        new_pushed = fork_info.last_pushed_at.isoformat() if fork_info.last_pushed_at else None
        return old_pushed != new_pushed

    async def _fetch_head_sha(self, fork_info: ForkInfo) -> str | None:
        """Fetch the fork's HEAD SHA, returning None on any provider error.

        A SHA fetch failure must never abort the sync loop — discovery and
        compare data are valuable on their own, and a None baseline is simply
        retried on the next sync. `CancelledError` is BaseException in 3.12,
        so it still propagates past this broad catch (Ctrl-C / shutdown stay
        intact).
        """
        _, repo_name = fork_info.full_name.split("/", 1)
        try:
            return await self._provider.get_head_sha(
                fork_info.owner, repo_name, fork_info.default_branch
            )
        except Exception as exc:
            logger.warning("Failed to fetch head SHA for %s: %s", fork_info.full_name, exc)
            return None


def _fork_to_dict(fork: Fork) -> dict:
    """Convert a Fork model to a dict suitable for database insertion."""
    d = fork.model_dump()
    d["created_at"] = fork.created_at.isoformat()
    d["updated_at"] = fork.updated_at.isoformat()
    d["last_pushed_at"] = fork.last_pushed_at.isoformat() if fork.last_pushed_at else None
    return d


def _fork_from_row(row: dict) -> Fork:
    """Convert a database row dict back into a Fork model.

    Pydantic handles ISO datetime string coercion automatically, so the
    raw row can be unpacked directly. Extra keys are ignored by Pydantic
    v2 when the model's `extra` config is the default.
    """
    return Fork(**row)

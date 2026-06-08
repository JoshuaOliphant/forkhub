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
    from tests.stubs import StubGitProvider

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
            # forker2 is DORMANT yet diverged (the bullet regression: a
            # quiet fork that still carries real changes). It must be
            # compared on first discovery despite its vitality.
            "forker2/repo-a": CompareResult(
                ahead_by=2,
                behind_by=0,
                files=[],
                commits=[],
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
        # Call recording so tests can assert the API-budget property.
        self.compare_calls: list[str] = []
        self.head_sha_calls: list[str] = []

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
        self.compare_calls.append(fork_full)

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

    async def get_head_sha(self, owner: str, repo: str, branch: str) -> str:
        """Return the canned HEAD SHA for ``{owner}/{repo}``.

        Keyed by full_name so existing canned data stays valid. Raises when
        no SHA is configured so the sync loop's graceful-degradation path
        (return None, log a warning) is exercised.
        """
        fork_full_name = f"{owner}/{repo}"
        self.head_sha_calls.append(fork_full_name)
        if fork_full_name not in self._head_shas:
            from forkhub.providers.github import GitHubProviderError

            raise GitHubProviderError(404, f"No head SHA for {fork_full_name}")
        return self._head_shas[fork_full_name]


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


# ---------------------------------------------------------------------------
# Analyzer integration (forkhub-hgm)
# ---------------------------------------------------------------------------


class TestSyncAnalyzerIntegration:
    """SyncService must call the injected analyzer when forks change."""

    async def test_sync_invokes_analyzer_when_forks_change(
        self, db: Database, provider: SyncStubGitProvider, settings: SyncSettings
    ):
        """Analyzer.analyze is called once with the changed forks and its
        returned signal count is exposed on the result."""
        from forkhub.models import Signal, SignalCategory

        from .stubs import StubAnalyzer

        repo = await _insert_tracked_repo(db)
        # Pre-seed forker1 with a stale SHA so compare() fires
        await _insert_fork_in_db(
            db,
            tracked_repo_id=repo.id,
            github_id=5001,
            owner="forker1",
            full_name="forker1/repo-a",
            head_sha="stale-sha",
        )

        canned_signals = [
            Signal(
                tracked_repo_id=repo.id,
                fork_id=None,
                category=SignalCategory.FEATURE,
                summary="Added X",
                significance=7,
            ),
            Signal(
                tracked_repo_id=repo.id,
                fork_id=None,
                category=SignalCategory.FIX,
                summary="Fixed Y",
                significance=6,
            ),
        ]
        analyzer = StubAnalyzer(signals=canned_signals)

        sync_service = SyncService(
            db=db, provider=provider, settings=settings, clock=_NOW, analyzer=analyzer
        )
        result = await sync_service.sync_repo(repo.id)

        assert len(analyzer.calls) == 1
        call = analyzer.calls[0]
        assert call["repo_full_name"] == "owner/repo-a"
        assert "forker1/repo-a" in call["changed_fork_names"]
        # SyncStubGitProvider seeds two releases for owner/repo-a; both
        # must be passed through to the analyzer.
        assert call["release_count"] == 2
        # Two stub signals were returned → signals_generated == 2
        assert result.signals_generated == 2

    async def test_sync_skips_analyzer_when_no_changed_forks_or_releases(
        self, db: Database, settings: SyncSettings
    ):
        """If nothing diverged and there are no releases, analyzer is not called."""
        from .stubs import StubAnalyzer

        repo = await _insert_tracked_repo(db, owner="owner", name="repo-b", github_id=1002)

        # Pre-seed forker4 with the SHA the provider will report, so no
        # change is detected. repo-b has no releases in SyncStubGitProvider.
        await _insert_fork_in_db(
            db,
            tracked_repo_id=repo.id,
            github_id=6001,
            owner="forker4",
            full_name="forker4/repo-b",
            head_sha="new-sha-forker4",
        )

        analyzer = StubAnalyzer()
        sync_service = SyncService(
            db=db,
            provider=SyncStubGitProvider(),
            settings=settings,
            clock=_NOW,
            analyzer=analyzer,
        )
        result = await sync_service.sync_repo(repo.id)

        assert analyzer.calls == []
        assert result.signals_generated == 0

    async def test_sync_handles_analyzer_failure_gracefully(
        self, db: Database, provider: SyncStubGitProvider, settings: SyncSettings
    ):
        """Analyzer exceptions must not abort the sync — record an error."""
        from .stubs import StubAnalyzer

        repo = await _insert_tracked_repo(db)
        await _insert_fork_in_db(
            db,
            tracked_repo_id=repo.id,
            github_id=5001,
            owner="forker1",
            full_name="forker1/repo-a",
            head_sha="stale-sha",
        )

        analyzer = StubAnalyzer(raise_error=RuntimeError("LLM budget exhausted"))
        sync_service = SyncService(
            db=db, provider=provider, settings=settings, clock=_NOW, analyzer=analyzer
        )
        result = await sync_service.sync_repo(repo.id)

        assert result.signals_generated == 0
        assert any("Analyzer failed" in e for e in result.errors)
        assert any("LLM budget exhausted" in e for e in result.errors)

    async def test_sync_without_analyzer_is_noop_for_analysis(
        self, sync_service: SyncService, db: Database
    ):
        """SyncService constructed with analyzer=None (the default) must
        still complete normally — no signals generated, no errors."""
        repo = await _insert_tracked_repo(db)
        result = await sync_service.sync_repo(repo.id)

        assert result.signals_generated == 0

    async def test_sync_invokes_analyzer_for_releases_only_no_changed_forks(
        self, db: Database, settings: SyncSettings
    ):
        """When new releases exist but no forks diverged, the analyzer
        must still be called with an empty `changed_forks` list."""
        from forkhub.models import Signal, SignalCategory

        from .stubs import StubAnalyzer

        # Use owner/repo-a which has two canned releases in the stub.
        # Pre-seed forker1 with the provider's reported SHA so no fork
        # compare fires. Pre-seed forker2 and forker3 so they are not
        # new (would otherwise trigger new-fork compare on forker1
        # which would add it to changed_forks).
        provider = SyncStubGitProvider()
        repo = await _insert_tracked_repo(db)
        for github_id, owner, name, sha in [
            (5001, "forker1", "forker1/repo-a", "new-sha-forker1"),
            (5002, "forker2", "forker2/repo-a", "unchanged-sha-forker2"),
            (5003, "forker3", "forker3/repo-a", "new-sha-forker3"),
        ]:
            await _insert_fork_in_db(
                db,
                tracked_repo_id=repo.id,
                github_id=github_id,
                owner=owner,
                full_name=name,
                head_sha=sha,
            )

        analyzer = StubAnalyzer(
            signals=[
                Signal(
                    tracked_repo_id=repo.id,
                    category=SignalCategory.RELEASE,
                    summary="v2.0.0",
                    significance=8,
                )
            ]
        )
        sync_service = SyncService(
            db=db, provider=provider, settings=settings, clock=_NOW, analyzer=analyzer
        )
        result = await sync_service.sync_repo(repo.id)

        assert len(analyzer.calls) == 1
        call = analyzer.calls[0]
        assert call["changed_fork_names"] == []
        assert call["release_count"] == 2
        assert result.signals_generated == 1

    async def test_sync_passes_fully_hydrated_fork_models_to_analyzer(
        self, db: Database, provider: SyncStubGitProvider, settings: SyncSettings
    ):
        """`_fork_from_row` must return real Fork models with populated
        fields. A silent bug that dropped fields or mis-coerced the ISO
        datetime would slip past the name-only assertions in the happy-path
        test above."""
        from .stubs import StubAnalyzer

        repo = await _insert_tracked_repo(db)
        await _insert_fork_in_db(
            db,
            tracked_repo_id=repo.id,
            github_id=5001,
            owner="forker1",
            full_name="forker1/repo-a",
            head_sha="stale-sha",
            stars=15,
        )

        analyzer = StubAnalyzer()
        sync_service = SyncService(
            db=db, provider=provider, settings=settings, clock=_NOW, analyzer=analyzer
        )
        await sync_service.sync_repo(repo.id)

        assert len(analyzer.calls) == 1
        fork_models = analyzer.calls[0]["changed_forks"]
        # forker1 (existing, changed) plus forker2 (new dormant, ahead_by=2)
        # both diverge, so isolate forker1 for the hydration assertions.
        f = next(m for m in fork_models if m.full_name == "forker1/repo-a")
        assert f.head_sha == "new-sha-forker1"  # updated by sync
        assert f.commits_ahead == 5  # from canned CompareResult
        assert f.stars == 15

    async def test_sync_all_aggregates_signals_generated(
        self, db: Database, settings: SyncSettings
    ):
        """`SyncResult.total_signals_generated` must be the sum of
        per-repo `signals_generated` across all repos in `sync_all`."""
        from forkhub.models import Signal, SignalCategory

        from .stubs import StubAnalyzer

        repo_a = await _insert_tracked_repo(db, owner="owner", name="repo-a", github_id=1001)
        repo_b = await _insert_tracked_repo(db, owner="owner", name="repo-b", github_id=1002)
        # Pre-seed both repos' forks with stale SHAs so compare fires.
        await _insert_fork_in_db(
            db,
            tracked_repo_id=repo_a.id,
            github_id=5001,
            owner="forker1",
            full_name="forker1/repo-a",
            head_sha="stale-sha-1",
        )
        await _insert_fork_in_db(
            db,
            tracked_repo_id=repo_b.id,
            github_id=6001,
            owner="forker4",
            full_name="forker4/repo-b",
            head_sha="stale-sha-2",
        )

        # Stub returns 3 signals per call (2 repos × 3 = 6 total).
        canned = [
            Signal(
                tracked_repo_id=repo_a.id,
                category=SignalCategory.FEATURE,
                summary=f"Signal {i}",
                significance=5,
            )
            for i in range(3)
        ]
        analyzer = StubAnalyzer(signals=canned)

        sync_service = SyncService(
            db=db,
            provider=SyncStubGitProvider(),
            settings=settings,
            clock=_NOW,
            analyzer=analyzer,
        )
        result = await sync_service.sync_all(reconcile=False)

        assert result.repos_synced == 2
        assert len(analyzer.calls) == 2
        # StubAnalyzer returns the same canned list on every call, so
        # each per-repo result has signals_generated == 3 → total == 6.
        assert result.total_signals_generated == 6
        per_repo = [r.signals_generated for r in result.results]
        assert per_repo == [3, 3]


# ---------------------------------------------------------------------------
# New-fork compare-on-first-discovery fix (forkhub-0tf root cause)
# ---------------------------------------------------------------------------


class TestSyncNewForkCompare:
    """First-sync discovery compares EVERY newly discovered fork — regardless
    of vitality — so `changed_forks` reflects divergence immediately and quiet
    dormant/dead forks (the canonical dormant-upstream scenario) aren't
    invisible. Each new fork is also baselined with a head_sha."""

    async def test_new_active_fork_gets_compared_on_first_sync(
        self, sync_service: SyncService, db: Database
    ):
        """forker1 is brand-new + active + diverged (ahead_by=5) → must
        land in changed_forks, have commits_ahead persisted, and be
        baselined with a head_sha."""
        repo = await _insert_tracked_repo(db)
        result = await sync_service.sync_repo(repo.id)

        assert "forker1/repo-a" in result.changed_forks

        row = await db.get_fork_by_name("forker1/repo-a")
        assert row is not None
        assert row["commits_ahead"] == 5
        assert row["commits_behind"] == 2
        assert row["head_sha"] == "new-sha-forker1"

    async def test_new_dormant_fork_is_compared(
        self, sync_service: SyncService, db: Database, provider: SyncStubGitProvider
    ):
        """The bullet regression: a DORMANT fork that still carries divergence
        must be compared on first discovery (it used to be gated out by
        vitality). forker2 is dormant but ahead_by=2 → it must land in
        changed_forks with commits_ahead persisted."""
        repo = await _insert_tracked_repo(db)
        result = await sync_service.sync_repo(repo.id)

        assert "forker2/repo-a" in provider.compare_calls
        assert "forker2/repo-a" in result.changed_forks

        row = await db.get_fork_by_name("forker2/repo-a")
        assert row is not None
        assert row["commits_ahead"] == 2
        assert row["vitality"] == "dormant"

    async def test_new_dead_fork_is_compared(
        self, sync_service: SyncService, db: Database, provider: SyncStubGitProvider
    ):
        """A DEAD fork is also compared on first discovery. forker3 is dead
        with no canned divergence (ahead_by=0) → compared but not changed."""
        repo = await _insert_tracked_repo(db)
        result = await sync_service.sync_repo(repo.id)

        assert "forker3/repo-a" in provider.compare_calls
        assert "forker3/repo-a" not in result.changed_forks

        row = await db.get_fork_by_name("forker3/repo-a")
        assert row is not None
        assert row["vitality"] == "dead"

    async def test_new_active_fork_with_zero_ahead_not_marked_changed(
        self, db: Database, settings: SyncSettings
    ):
        """An active fork whose compare returns ahead_by=0 must NOT be
        added to changed_forks — nothing diverged."""
        provider = SyncStubGitProvider()
        # forker4/repo-b is active but SyncStubGitProvider has no canned
        # CompareResult for it → defaults to ahead_by=0, behind_by=0.
        repo = await _insert_tracked_repo(db, owner="owner", name="repo-b", github_id=1002)
        sync_service = SyncService(db=db, provider=provider, settings=settings, clock=_NOW)
        result = await sync_service.sync_repo(repo.id)

        assert "forker4/repo-b" not in result.changed_forks
        row = await db.get_fork_by_name("forker4/repo-b")
        assert row is not None
        assert row["commits_ahead"] == 0

    async def test_new_fork_compare_failure_logged_not_raised(
        self, db: Database, provider: SyncStubGitProvider, settings: SyncSettings
    ):
        """If provider.compare() raises during first-sync discovery, the
        fork must still be inserted and changed_forks stays empty for it."""
        provider._error_forks.add("forker1/repo-a")
        sync_service = SyncService(db=db, provider=provider, settings=settings, clock=_NOW)
        repo = await _insert_tracked_repo(db)
        result = await sync_service.sync_repo(repo.id)

        # Fork should still have been inserted
        row = await db.get_fork_by_name("forker1/repo-a")
        assert row is not None
        # But not counted as changed (compare failed)
        assert "forker1/repo-a" not in result.changed_forks


# ---------------------------------------------------------------------------
# last_pushed_at fallback change detection (forkhub-99c)
# ---------------------------------------------------------------------------


class TestLastPushedAtChangeDetection:
    """Verify last_pushed_at is the cheap pre-filter for existing baselined forks.

    `_has_fork_changed` compares last_pushed_at (free — the /forks listing always
    returns it) to decide whether to compare. The HEAD SHA is fetched only after
    that decision and confirms divergence. An already-baselined fork (head_sha set)
    whose pushed_at is unchanged costs ZERO extra calls — the API-budget property.
    """

    _OWNER = "testowner"
    _REPO = "repo-c"
    _FORK_GITHUB_ID = 8001
    _FORK_OWNER = "test-forker"
    _FORK_FULL = "test-forker/repo-c"
    _BASELINE_SHA = "baseline-sha-000"

    def _make_provider(
        self,
        last_pushed_at: datetime | None,
        head_shas: dict[str, str] | None = None,
    ) -> StubGitProvider:
        from .stubs import StubGitProvider

        fork_info = ForkInfo(
            github_id=self._FORK_GITHUB_ID,
            owner=self._FORK_OWNER,
            full_name=self._FORK_FULL,
            default_branch="main",
            description=None,
            stars=0,
            last_pushed_at=last_pushed_at,
            has_diverged=True,
            created_at=_NOW - timedelta(days=90),
        )
        return StubGitProvider(
            forks={f"{self._OWNER}/{self._REPO}": [fork_info]},
            head_shas=head_shas or {},
        )

    async def _insert_repo(self, db: Database) -> TrackedRepo:
        return await _insert_tracked_repo(db, owner=self._OWNER, name=self._REPO, github_id=9001)

    async def _insert_baselined_fork(
        self, db: Database, repo: TrackedRepo, last_pushed_at: datetime | None
    ) -> None:
        """Insert an already-baselined fork (head_sha populated)."""
        await _insert_fork_in_db(
            db,
            tracked_repo_id=repo.id,
            github_id=self._FORK_GITHUB_ID,
            owner=self._FORK_OWNER,
            full_name=self._FORK_FULL,
            head_sha=self._BASELINE_SHA,
            last_pushed_at=last_pushed_at,
        )

    async def test_same_pushed_at_skips_compare_and_costs_zero_calls(
        self, db: Database, settings: SyncSettings
    ):
        """An unchanged, already-baselined fork must not be compared and must
        not trigger a head_sha fetch — the API-budget property."""
        repo = await self._insert_repo(db)
        await self._insert_baselined_fork(db, repo, last_pushed_at=_ACTIVE_DATE)
        provider = self._make_provider(last_pushed_at=_ACTIVE_DATE)
        sync_service = SyncService(db=db, provider=provider, settings=settings, clock=_NOW)
        result = await sync_service.sync_repo(repo.id)

        assert result.changed_forks == []
        assert provider.compare_calls == []
        assert provider.head_sha_calls == []

    async def test_advanced_pushed_at_fires_compare(self, db: Database, settings: SyncSettings):
        """When pushed_at advances on a baselined fork, the fork is compared,
        the head_sha refreshes, and a new SHA marks it changed."""
        repo = await self._insert_repo(db)
        await self._insert_baselined_fork(db, repo, last_pushed_at=_ACTIVE_DATE - timedelta(days=7))
        provider = self._make_provider(
            last_pushed_at=_ACTIVE_DATE,
            head_shas={self._FORK_FULL: "advanced-sha-111"},
        )
        sync_service = SyncService(db=db, provider=provider, settings=settings, clock=_NOW)
        result = await sync_service.sync_repo(repo.id)

        assert self._FORK_FULL in result.changed_forks
        row = await db.get_fork_by_name(self._FORK_FULL)
        assert row is not None
        assert row["head_sha"] == "advanced-sha-111"

    async def test_null_head_sha_triggers_baseline_catchup(
        self, db: Database, settings: SyncSettings
    ):
        """A pre-existing fork with NULL head_sha (created before baselining)
        is compared once even though pushed_at is unchanged — the one-time
        baseline catch-up. The SHA gets populated."""
        repo = await self._insert_repo(db)
        await _insert_fork_in_db(
            db,
            tracked_repo_id=repo.id,
            github_id=self._FORK_GITHUB_ID,
            owner=self._FORK_OWNER,
            full_name=self._FORK_FULL,
            head_sha=None,  # legacy row, never baselined
            last_pushed_at=_ACTIVE_DATE,
        )
        provider = self._make_provider(
            last_pushed_at=_ACTIVE_DATE,  # unchanged
            head_shas={self._FORK_FULL: "catchup-sha-222"},
        )
        sync_service = SyncService(db=db, provider=provider, settings=settings, clock=_NOW)
        result = await sync_service.sync_repo(repo.id)

        # Compare fired despite unchanged pushed_at, because head_sha was NULL.
        assert [c["head"] for c in provider.compare_calls] == [f"{self._FORK_OWNER}:main"]
        row = await db.get_fork_by_name(self._FORK_FULL)
        assert row is not None
        assert row["head_sha"] == "catchup-sha-222"
        # The SHA differs from the (NULL) prior, so it counts as changed.
        assert self._FORK_FULL in result.changed_forks

    async def test_head_sha_fetch_error_keeps_fork_and_continues(
        self, db: Database, settings: SyncSettings
    ):
        """When get_head_sha raises during the baseline-catchup compare, the
        fork is still saved (head_sha stays None) and the sync continues."""
        repo = await self._insert_repo(db)
        await _insert_fork_in_db(
            db,
            tracked_repo_id=repo.id,
            github_id=self._FORK_GITHUB_ID,
            owner=self._FORK_OWNER,
            full_name=self._FORK_FULL,
            head_sha=None,
            last_pushed_at=_ACTIVE_DATE,
        )
        # No head_shas configured → StubGitProvider.get_head_sha raises.
        provider = self._make_provider(last_pushed_at=_ACTIVE_DATE)
        sync_service = SyncService(db=db, provider=provider, settings=settings, clock=_NOW)
        result = await sync_service.sync_repo(repo.id)

        # Provider error during SHA fetch must not abort the sync.
        row = await db.get_fork_by_name(self._FORK_FULL)
        assert row is not None
        assert row["head_sha"] is None  # fetch failed → no SHA written
        # SHA was None, so the catch-up still reports the fork as changed.
        assert self._FORK_FULL in result.changed_forks

    async def test_none_pushed_at_both_sides_skips_compare(
        self, db: Database, settings: SyncSettings
    ):
        """When both old and new pushed_at are None on a baselined fork, no
        compare fires (conserves budget)."""
        repo = await self._insert_repo(db)
        await self._insert_baselined_fork(db, repo, last_pushed_at=None)
        provider = self._make_provider(last_pushed_at=None)
        sync_service = SyncService(db=db, provider=provider, settings=settings, clock=_NOW)
        result = await sync_service.sync_repo(repo.id)

        assert result.changed_forks == []
        assert provider.compare_calls == []

    async def test_sha_provider_uses_sha_not_pushed_at(self, db: Database, settings: SyncSettings):
        """When pushed_at advances but the refreshed SHA matches the stored one,
        the compare fires (pushed_at advanced) but the fork is NOT reported as
        changed — the SHA is authoritative for divergence."""
        matching_sha = "sha-abc123"
        repo = await self._insert_repo(db)
        await _insert_fork_in_db(
            db,
            tracked_repo_id=repo.id,
            github_id=self._FORK_GITHUB_ID,
            owner=self._FORK_OWNER,
            full_name=self._FORK_FULL,
            head_sha=matching_sha,
            last_pushed_at=_ACTIVE_DATE - timedelta(days=7),  # stale, but SHA matches
        )
        # Provider reports newer pushed_at but the same SHA → no real change.
        provider = self._make_provider(
            last_pushed_at=_ACTIVE_DATE,
            head_shas={self._FORK_FULL: matching_sha},
        )
        sync_service = SyncService(db=db, provider=provider, settings=settings, clock=_NOW)
        result = await sync_service.sync_repo(repo.id)

        assert result.changed_forks == []
        # Compare DID fire (pushed_at advanced) — suppression is post-fetch.
        assert [c["head"] for c in provider.compare_calls] == [f"{self._FORK_OWNER}:main"]

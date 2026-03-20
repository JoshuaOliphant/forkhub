# ABOUTME: Unit tests for the ForkHub public API class.
# ABOUTME: Uses stub providers and in-memory SQLite to test all public methods.

from __future__ import annotations

import pytest

from forkhub.config import ForkHubSettings
from forkhub.database import Database
from forkhub.models import (
    Digest,
    TrackedRepo,
    TrackingMode,
)
from forkhub.services.sync import SyncResult
from tests.stubs import StubEmbeddingProvider, StubGitProvider, StubNotificationBackend

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def provider() -> StubGitProvider:
    return StubGitProvider.with_testuser_data()


@pytest.fixture
def settings() -> ForkHubSettings:
    return ForkHubSettings()


@pytest.fixture
def hub(
    db: Database,
    provider: StubGitProvider,
    backend: StubNotificationBackend,
    embedding_provider: StubEmbeddingProvider,
    settings: ForkHubSettings,
):
    """Build a ForkHub instance wired up with stubs, using an already-connected db."""
    from forkhub import ForkHub

    return ForkHub(
        settings=settings,
        git_provider=provider,
        notification_backends=[backend],
        embedding_provider=embedding_provider,
        db=db,
    )


# ---------------------------------------------------------------------------
# Construction tests
# ---------------------------------------------------------------------------


class TestForkHubConstruction:
    def test_construction_with_defaults_does_not_crash(self, settings: ForkHubSettings):
        """ForkHub should construct with default settings without raising."""
        from forkhub import ForkHub

        hub = ForkHub(settings=settings)
        assert hub is not None

    def test_construction_with_custom_providers(
        self,
        db: Database,
        provider: StubGitProvider,
        backend: StubNotificationBackend,
        embedding_provider: StubEmbeddingProvider,
        settings: ForkHubSettings,
    ):
        """ForkHub should accept custom injected providers."""
        from forkhub import ForkHub

        hub = ForkHub(
            settings=settings,
            git_provider=provider,
            notification_backends=[backend],
            embedding_provider=embedding_provider,
            db=db,
        )
        assert hub._provider is provider
        assert hub._backends == [backend]
        assert hub._embedding_provider is embedding_provider
        assert hub._db is db


# ---------------------------------------------------------------------------
# Async context manager
# ---------------------------------------------------------------------------


class TestAsyncContextManager:
    async def test_context_manager_opens_and_closes_db(self, settings: ForkHubSettings):
        """The async context manager should connect and close the DB."""
        from forkhub import ForkHub

        db = Database(":memory:")
        hub = ForkHub(settings=settings, db=db)
        async with hub as h:
            assert h is hub
            # DB should be connected (we can query it)
            tables = await db._table_names()
            assert "tracked_repos" in tables
        # After exit, db should be closed
        assert db._conn is None


# ---------------------------------------------------------------------------
# init()
# ---------------------------------------------------------------------------


class TestInit:
    async def test_init_discovers_repos(self, hub):
        """init() should discover owned and upstream repos."""
        result = await hub.init("testuser")
        # 2 owned (non-fork) repos + 1 upstream (parent of forked-lib)
        assert len(result) == 3
        names = {r.full_name for r in result}
        assert "testuser/alpha" in names
        assert "testuser/beta" in names
        assert "upstream-org/forked-lib" in names


# ---------------------------------------------------------------------------
# track()
# ---------------------------------------------------------------------------


class TestTrack:
    async def test_track_adds_repo(self, hub):
        """track() should add a repo and return TrackedRepo."""
        result = await hub.track("testuser", "alpha")
        assert isinstance(result, TrackedRepo)
        assert result.full_name == "testuser/alpha"
        assert result.tracking_mode == TrackingMode.WATCHED

    async def test_track_raises_on_duplicate(self, hub):
        """track() should raise ValueError on duplicate."""
        await hub.track("testuser", "alpha")
        with pytest.raises(ValueError, match="already tracked"):
            await hub.track("testuser", "alpha")


# ---------------------------------------------------------------------------
# untrack()
# ---------------------------------------------------------------------------


class TestUntrack:
    async def test_untrack_removes_repo(self, hub, db: Database):
        """untrack() should remove the repo from tracking."""
        await hub.track("testuser", "alpha")
        await hub.untrack("testuser", "alpha")
        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is None


# ---------------------------------------------------------------------------
# get_repos()
# ---------------------------------------------------------------------------


class TestGetRepos:
    async def test_get_repos_returns_list(self, hub):
        """get_repos() should return a list of tracked repos."""
        await hub.track("testuser", "alpha")
        await hub.track("testuser", "beta")
        repos = await hub.get_repos()
        assert len(repos) == 2

    async def test_get_repos_filters_by_mode(self, hub):
        """get_repos() should filter by tracking mode when specified."""
        await hub.track("testuser", "alpha", mode=TrackingMode.WATCHED)
        await hub.track("testuser", "beta", mode=TrackingMode.UPSTREAM)
        watched = await hub.get_repos(mode=TrackingMode.WATCHED)
        upstream = await hub.get_repos(mode=TrackingMode.UPSTREAM)
        assert len(watched) == 1
        assert watched[0].full_name == "testuser/alpha"
        assert len(upstream) == 1
        assert upstream[0].full_name == "testuser/beta"


# ---------------------------------------------------------------------------
# get_forks()
# ---------------------------------------------------------------------------


class TestGetForks:
    async def test_get_forks_returns_forks(self, hub, db: Database):
        """get_forks() should return forks for a tracked repo."""
        await hub.track("testuser", "alpha")
        # Sync to discover forks
        await hub.sync(repo="testuser/alpha")
        forks = await hub.get_forks("testuser", "alpha")
        assert len(forks) == 1
        assert forks[0].owner == "forker1"

    async def test_get_forks_raises_on_untracked_repo(self, hub):
        """get_forks() should raise ValueError for untracked repo."""
        with pytest.raises(ValueError, match="not tracked"):
            await hub.get_forks("nobody", "nothing")


# ---------------------------------------------------------------------------
# sync()
# ---------------------------------------------------------------------------


class TestSync:
    async def test_sync_runs_pipeline(self, hub):
        """sync() should run the sync pipeline and return SyncResult."""
        await hub.track("testuser", "alpha")
        result = await hub.sync()
        assert isinstance(result, SyncResult)
        assert result.repos_synced == 1

    async def test_sync_single_repo(self, hub):
        """sync(repo=...) should sync only the specified repo."""
        await hub.track("testuser", "alpha")
        await hub.track("testuser", "beta")
        result = await hub.sync(repo="testuser/alpha")
        assert isinstance(result, SyncResult)
        assert result.repos_synced == 1

    async def test_sync_raises_on_untracked_repo(self, hub):
        """sync(repo=...) should raise ValueError for untracked repo."""
        with pytest.raises(ValueError, match="not tracked"):
            await hub.sync(repo="nobody/nothing")


# ---------------------------------------------------------------------------
# get_clusters()
# ---------------------------------------------------------------------------


class TestGetClusters:
    async def test_get_clusters_returns_list(self, hub):
        """get_clusters() should return a (possibly empty) list of clusters."""
        await hub.track("testuser", "alpha")
        clusters = await hub.get_clusters("testuser", "alpha")
        assert isinstance(clusters, list)

    async def test_get_clusters_raises_on_untracked_repo(self, hub):
        """get_clusters() should raise ValueError for untracked repo."""
        with pytest.raises(ValueError, match="not tracked"):
            await hub.get_clusters("nobody", "nothing")


# ---------------------------------------------------------------------------
# generate_digest()
# ---------------------------------------------------------------------------


class TestGenerateDigest:
    async def test_generate_digest_returns_digest(self, hub, db: Database):
        """generate_digest() should return a Digest object."""
        await hub.track("testuser", "alpha")
        digest = await hub.generate_digest()
        assert isinstance(digest, Digest)
        assert digest.title  # title should not be empty

    async def test_generate_digest_for_specific_repo(self, hub, db: Database):
        """generate_digest(repo=...) should scope to a specific repo."""
        await hub.track("testuser", "alpha")
        digest = await hub.generate_digest(repo="testuser/alpha")
        assert isinstance(digest, Digest)


# ---------------------------------------------------------------------------
# deliver_digest()
# ---------------------------------------------------------------------------


class TestDeliverDigest:
    async def test_deliver_digest_returns_results(
        self, hub, backend: StubNotificationBackend, db: Database
    ):
        """deliver_digest() should deliver via backends and return results."""
        await hub.track("testuser", "alpha")
        digest = await hub.generate_digest()
        results = await hub.deliver_digest(digest)
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].backend_name == "stub"
        assert len(backend.delivered) == 1


# ---------------------------------------------------------------------------
# reconcile()
# ---------------------------------------------------------------------------


class TestReconcile:
    async def test_sync_triggers_reconciliation(self, hub):
        """sync() should trigger reconciliation."""
        await hub.track("testuser", "alpha")
        result = await hub.sync()
        assert isinstance(result, SyncResult)

    async def test_reconcile_standalone(self, hub, db: Database):
        """reconcile() as standalone method should work."""
        from forkhub.services.sync import ReconcileResult

        await hub.track("testuser", "alpha")
        result = await hub.reconcile()
        assert isinstance(result, ReconcileResult)


# ---------------------------------------------------------------------------
# retry_repo()
# ---------------------------------------------------------------------------


class TestRetryRepo:
    async def test_retry_repo_resets_inaccessible(self, hub, db: Database):
        """retry_repo() should reset sync_status back to 'ok'."""
        await hub.track("testuser", "alpha")
        # Mark as inaccessible
        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is not None
        row["sync_status"] = "inaccessible"
        row["last_sync_error"] = "404 Not Found"
        await db.update_tracked_repo(row)

        await hub.retry_repo("testuser", "alpha")
        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is not None
        assert row["sync_status"] == "ok"
        assert row["last_sync_error"] is None

    async def test_retry_repo_resets_error_status(self, hub, db: Database):
        """retry_repo() should also work on repos with 'error' status."""
        await hub.track("testuser", "alpha")
        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is not None
        row["sync_status"] = "error"
        row["last_sync_error"] = "500 Server Error"
        await db.update_tracked_repo(row)

        await hub.retry_repo("testuser", "alpha")
        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is not None
        assert row["sync_status"] == "ok"
        assert row["last_sync_error"] is None

    async def test_retry_repo_raises_on_untracked(self, hub):
        """retry_repo() should raise ValueError for untracked repo."""
        with pytest.raises(ValueError, match="not tracked"):
            await hub.retry_repo("nobody", "nothing")

# ABOUTME: Unit tests for the ForkHub public API class.
# ABOUTME: Uses stub providers and in-memory SQLite to test all public methods.

from __future__ import annotations

import pytest

from forkhub.config import ForkHubSettings
from forkhub.database import Database
from forkhub.models import Digest
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
# Untracked repo validation
# ---------------------------------------------------------------------------


class TestUntrackedRepoValidation:
    async def test_methods_raise_on_untracked_repo(self, hub):
        """All repo-scoped methods should raise ValueError for untracked repos."""
        with pytest.raises(ValueError, match="not tracked"):
            await hub.get_forks("nobody", "nothing")
        with pytest.raises(ValueError, match="not tracked"):
            await hub.sync(repo="nobody/nothing")
        with pytest.raises(ValueError, match="not tracked"):
            await hub.get_clusters("nobody", "nothing")
        with pytest.raises(ValueError, match="not tracked"):
            await hub.retry_repo("nobody", "nothing")


# ---------------------------------------------------------------------------
# Public API method smoke tests
# ---------------------------------------------------------------------------


class TestPublicAPIMethods:
    async def test_clusters_digest_and_reconcile(self, hub, db: Database):
        """get_clusters, generate_digest, and reconcile should work on tracked repos."""
        from forkhub.services.sync import ReconcileResult

        await hub.track("testuser", "alpha")

        # get_clusters
        clusters = await hub.get_clusters("testuser", "alpha")
        assert isinstance(clusters, list)

        # generate_digest
        digest = await hub.generate_digest(repo="testuser/alpha")
        assert isinstance(digest, Digest)

        # reconcile
        result = await hub.reconcile()
        assert isinstance(result, ReconcileResult)

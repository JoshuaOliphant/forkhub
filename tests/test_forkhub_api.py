# ABOUTME: Unit tests for the ForkHub public API class.
# ABOUTME: Uses stub providers and in-memory SQLite to test all public methods.

from __future__ import annotations

import pytest

from forkhub.config import ForkHubSettings
from forkhub.database import Database
from forkhub.models import Digest
from tests.stubs import (
    StubEmbeddingProvider,
    StubGitProvider,
    StubNotificationBackend,
    make_cluster,
    make_cluster_member,
    make_fork,
    make_signal,
    make_tracked_repo,
)

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


# ---------------------------------------------------------------------------
# Signal + cluster-membership accessors (web data path)
# ---------------------------------------------------------------------------


class TestSignalAndClusterAccessors:
    async def test_get_signals_returns_repo_signals(self, hub, db: Database):
        """get_signals returns the repo's signals, decoding files_involved JSON."""
        repo = make_tracked_repo()
        await db.insert_tracked_repo(repo)
        fork = make_fork(repo["id"])
        await db.insert_fork(fork)
        await db.insert_signal(make_signal(fork["id"], repo["id"]))
        # A signal with empty files_involved exercises the falsy-decode branch.
        await db.insert_signal(make_signal(fork["id"], repo["id"], files_involved=""))

        owner, name = repo["full_name"].split("/")
        signals = await hub.get_signals(owner, name)

        assert len(signals) == 2
        files = {tuple(s.files_involved) for s in signals}
        assert ("src/gpu.py", "src/train.py") in files
        assert () in files  # the empty-files signal decoded to []

    async def test_get_signals_untracked_raises(self, hub):
        with pytest.raises(ValueError, match="not tracked"):
            await hub.get_signals("nobody", "nothing")

    async def test_get_cluster_members_maps_clusters_to_fork_ids(self, hub, db: Database):
        """get_cluster_members maps each cluster id to its member fork ids."""
        repo = make_tracked_repo()
        await db.insert_tracked_repo(repo)
        f1 = make_fork(repo["id"], github_id=111, full_name="alice/linux")
        f2 = make_fork(repo["id"], github_id=222, full_name="bob/linux")
        await db.insert_fork(f1)
        await db.insert_fork(f2)
        s1 = make_signal(f1["id"], repo["id"])
        s2 = make_signal(f2["id"], repo["id"])
        await db.insert_signal(s1)
        await db.insert_signal(s2)
        cluster = make_cluster(repo["id"])
        await db.insert_cluster(cluster)
        await db.add_cluster_member(make_cluster_member(cluster["id"], s1["id"], f1["id"]))
        await db.add_cluster_member(make_cluster_member(cluster["id"], s2["id"], f2["id"]))

        owner, name = repo["full_name"].split("/")
        members = await hub.get_cluster_members(owner, name)

        assert set(members) == {cluster["id"]}
        assert set(members[cluster["id"]]) == {f1["id"], f2["id"]}

    async def test_get_cluster_members_untracked_raises(self, hub):
        with pytest.raises(ValueError, match="not tracked"):
            await hub.get_cluster_members("nobody", "nothing")

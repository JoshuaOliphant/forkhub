# ABOUTME: Unit tests for the ForkHub public API class.
# ABOUTME: Uses stub providers and in-memory SQLite to test all public methods.

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from forkhub.config import ForkHubSettings
from forkhub.database import Database
from forkhub.models import (
    CommitInfo,
    CompareResult,
    DeliveryResult,
    Digest,
    ForkInfo,
    ForkPage,
    RateLimitInfo,
    Release,
    RepoInfo,
    TrackedRepo,
    TrackingMode,
)
from forkhub.services.sync import SyncResult

# ---------------------------------------------------------------------------
# Time constants
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, tzinfo=UTC)
_ACTIVE_DATE = _NOW - timedelta(days=30)


# ---------------------------------------------------------------------------
# Stub providers — real classes satisfying Protocol interfaces
# ---------------------------------------------------------------------------


class StubGitProvider:
    """Stub implementation of GitProvider with canned data for ForkHub API tests."""

    def __init__(self) -> None:
        self.user_repos: dict[str, list[RepoInfo]] = {
            "testuser": [
                RepoInfo(
                    github_id=1001,
                    owner="testuser",
                    name="alpha",
                    full_name="testuser/alpha",
                    default_branch="main",
                    description="Alpha project",
                    is_fork=False,
                    parent_full_name=None,
                    stars=10,
                    forks_count=3,
                    last_pushed_at=_NOW,
                ),
                RepoInfo(
                    github_id=1002,
                    owner="testuser",
                    name="beta",
                    full_name="testuser/beta",
                    default_branch="main",
                    description="Beta project",
                    is_fork=False,
                    parent_full_name=None,
                    stars=5,
                    forks_count=1,
                    last_pushed_at=_NOW,
                ),
                RepoInfo(
                    github_id=1003,
                    owner="testuser",
                    name="forked-lib",
                    full_name="testuser/forked-lib",
                    default_branch="main",
                    description="A forked library",
                    is_fork=True,
                    parent_full_name="upstream-org/forked-lib",
                    stars=0,
                    forks_count=0,
                    last_pushed_at=_NOW,
                ),
            ],
        }
        self.repos: dict[str, RepoInfo] = {
            "testuser/alpha": self.user_repos["testuser"][0],
            "testuser/beta": self.user_repos["testuser"][1],
            "testuser/forked-lib": self.user_repos["testuser"][2],
            "upstream-org/forked-lib": RepoInfo(
                github_id=2001,
                owner="upstream-org",
                name="forked-lib",
                full_name="upstream-org/forked-lib",
                default_branch="main",
                description="The original library",
                is_fork=False,
                parent_full_name=None,
                stars=500,
                forks_count=50,
                last_pushed_at=_NOW,
            ),
        }
        self._forks: dict[str, list[ForkInfo]] = {
            "testuser/alpha": [
                ForkInfo(
                    github_id=5001,
                    owner="forker1",
                    full_name="forker1/alpha",
                    default_branch="main",
                    description="Forker 1's copy",
                    stars=15,
                    last_pushed_at=_ACTIVE_DATE,
                    has_diverged=True,
                    created_at=_NOW - timedelta(days=60),
                ),
            ],
        }
        self._head_shas: dict[str, str] = {
            "forker1/alpha": "sha-forker1",
        }

    async def get_user_repos(self, username: str) -> list[RepoInfo]:
        return self.user_repos.get(username, [])

    async def get_repo(self, owner: str, repo: str) -> RepoInfo:
        full_name = f"{owner}/{repo}"
        if full_name not in self.repos:
            raise ValueError(f"Repo not found: {full_name}")
        return self.repos[full_name]

    async def get_forks(self, owner: str, repo: str, *, page: int = 1) -> ForkPage:
        full_name = f"{owner}/{repo}"
        forks = self._forks.get(full_name, [])
        return ForkPage(forks=forks, total_count=len(forks), page=1, has_next=False)

    async def compare(self, owner: str, repo: str, base: str, head: str) -> CompareResult:
        return CompareResult(ahead_by=3, behind_by=1, files=[], commits=[])

    async def get_releases(
        self, owner: str, repo: str, *, since: datetime | None = None
    ) -> list[Release]:
        return []

    async def get_commit_messages(
        self, owner: str, repo: str, *, since: str | None = None
    ) -> list[CommitInfo]:
        return []

    async def get_file_diff(self, owner: str, repo: str, base: str, head: str, path: str) -> str:
        return ""

    async def get_rate_limit(self) -> RateLimitInfo:
        return RateLimitInfo(limit=5000, remaining=4999, reset_at=_NOW)

    def get_head_sha(self, fork_full_name: str) -> str | None:
        return self._head_shas.get(fork_full_name)


class StubNotificationBackend:
    """Deterministic notification backend for testing."""

    def __init__(self, name: str = "stub") -> None:
        self._name = name
        self.delivered: list[Digest] = []

    async def deliver(self, digest: Digest) -> DeliveryResult:
        self.delivered.append(digest)
        return DeliveryResult(
            backend_name=self._name,
            success=True,
            error=None,
            delivered_at=datetime.now(UTC),
        )

    def backend_name(self) -> str:
        return self._name


class StubEmbeddingProvider:
    """Deterministic embedding provider for testing."""

    def __init__(self, dims: int = 8) -> None:
        self._dims = dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            vec = [0.0] * self._dims
            for ch in text:
                idx = ord(ch) % self._dims
                vec[idx] += 1.0
            mag = sum(v * v for v in vec) ** 0.5
            if mag > 0:
                vec = [v / mag for v in vec]
            results.append(vec)
        return results

    def dimensions(self) -> int:
        return self._dims


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    """Provide an in-memory Database connected and schema-created."""
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def provider() -> StubGitProvider:
    return StubGitProvider()


@pytest.fixture
def backend() -> StubNotificationBackend:
    return StubNotificationBackend()


@pytest.fixture
def embedding_provider() -> StubEmbeddingProvider:
    return StubEmbeddingProvider()


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

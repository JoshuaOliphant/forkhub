# ABOUTME: Integration tests for the full ForkHub pipeline.
# ABOUTME: Tests end-to-end flows using real in-memory SQLite and stub providers.

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
    TrackingMode,
)
from forkhub.services.sync import SyncResult

# ---------------------------------------------------------------------------
# Time constants
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, tzinfo=UTC)
_ACTIVE_DATE = _NOW - timedelta(days=30)
_DORMANT_DATE = _NOW - timedelta(days=200)


# ---------------------------------------------------------------------------
# Stub providers for integration testing
# ---------------------------------------------------------------------------


class IntegrationStubGitProvider:
    """Stub provider with multiple repos and forks for integration testing."""

    def __init__(self) -> None:
        self.user_repos: dict[str, list[RepoInfo]] = {
            "alice": [
                RepoInfo(
                    github_id=1001,
                    owner="alice",
                    name="web-framework",
                    full_name="alice/web-framework",
                    default_branch="main",
                    description="A web framework",
                    is_fork=False,
                    parent_full_name=None,
                    stars=100,
                    forks_count=5,
                    last_pushed_at=_NOW,
                ),
                RepoInfo(
                    github_id=1002,
                    owner="alice",
                    name="cli-tool",
                    full_name="alice/cli-tool",
                    default_branch="main",
                    description="A CLI tool",
                    is_fork=False,
                    parent_full_name=None,
                    stars=50,
                    forks_count=2,
                    last_pushed_at=_NOW,
                ),
                RepoInfo(
                    github_id=1003,
                    owner="alice",
                    name="upstream-fork",
                    full_name="alice/upstream-fork",
                    default_branch="main",
                    description="Alice's fork of upstream",
                    is_fork=True,
                    parent_full_name="upstream/original",
                    stars=0,
                    forks_count=0,
                    last_pushed_at=_NOW,
                ),
            ],
        }
        self.repos: dict[str, RepoInfo] = {}
        for repos_list in self.user_repos.values():
            for repo in repos_list:
                self.repos[repo.full_name] = repo
        self.repos["upstream/original"] = RepoInfo(
            github_id=3001,
            owner="upstream",
            name="original",
            full_name="upstream/original",
            default_branch="main",
            description="The upstream original",
            is_fork=False,
            parent_full_name=None,
            stars=1000,
            forks_count=100,
            last_pushed_at=_NOW,
        )

        self._forks: dict[str, list[ForkInfo]] = {
            "alice/web-framework": [
                ForkInfo(
                    github_id=5001,
                    owner="bob",
                    full_name="bob/web-framework",
                    default_branch="main",
                    description="Bob's fork",
                    stars=15,
                    last_pushed_at=_ACTIVE_DATE,
                    has_diverged=True,
                    created_at=_NOW - timedelta(days=60),
                ),
                ForkInfo(
                    github_id=5002,
                    owner="charlie",
                    full_name="charlie/web-framework",
                    default_branch="main",
                    description="Charlie's fork",
                    stars=3,
                    last_pushed_at=_DORMANT_DATE,
                    has_diverged=False,
                    created_at=_NOW - timedelta(days=300),
                ),
            ],
            "alice/cli-tool": [
                ForkInfo(
                    github_id=6001,
                    owner="diana",
                    full_name="diana/cli-tool",
                    default_branch="main",
                    description="Diana's fork",
                    stars=7,
                    last_pushed_at=_ACTIVE_DATE,
                    has_diverged=True,
                    created_at=_NOW - timedelta(days=10),
                ),
            ],
        }
        self._head_shas: dict[str, str] = {}
        self._call_log: list[str] = []

    async def get_user_repos(self, username: str) -> list[RepoInfo]:
        self._call_log.append(f"get_user_repos({username})")
        return self.user_repos.get(username, [])

    async def get_repo(self, owner: str, repo: str) -> RepoInfo:
        full_name = f"{owner}/{repo}"
        self._call_log.append(f"get_repo({full_name})")
        if full_name not in self.repos:
            raise ValueError(f"Repo not found: {full_name}")
        return self.repos[full_name]

    async def get_forks(self, owner: str, repo: str, *, page: int = 1) -> ForkPage:
        full_name = f"{owner}/{repo}"
        self._call_log.append(f"get_forks({full_name})")
        forks = self._forks.get(full_name, [])
        return ForkPage(forks=forks, total_count=len(forks), page=1, has_next=False)

    async def compare(self, owner: str, repo: str, base: str, head: str) -> CompareResult:
        self._call_log.append(f"compare({owner}/{repo})")
        return CompareResult(ahead_by=5, behind_by=2, files=[], commits=[])

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


class IntegrationStubNotificationBackend:
    """Records delivered digests for assertion in integration tests."""

    def __init__(self, name: str = "integration-stub") -> None:
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


class IntegrationStubEmbeddingProvider:
    """Deterministic embeddings for integration testing."""

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
def provider() -> IntegrationStubGitProvider:
    return IntegrationStubGitProvider()


@pytest.fixture
def backend() -> IntegrationStubNotificationBackend:
    return IntegrationStubNotificationBackend()


@pytest.fixture
def embedding_provider() -> IntegrationStubEmbeddingProvider:
    return IntegrationStubEmbeddingProvider()


@pytest.fixture
def settings() -> ForkHubSettings:
    return ForkHubSettings()


@pytest.fixture
def hub(
    db: Database,
    provider: IntegrationStubGitProvider,
    backend: IntegrationStubNotificationBackend,
    embedding_provider: IntegrationStubEmbeddingProvider,
    settings: ForkHubSettings,
):
    """Build a ForkHub instance wired with stubs and in-memory SQLite."""
    from forkhub import ForkHub

    return ForkHub(
        settings=settings,
        git_provider=provider,
        notification_backends=[backend],
        embedding_provider=embedding_provider,
        db=db,
    )


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestFullLifecycle:
    async def test_init_track_sync_forks_digest_deliver(
        self,
        hub,
        backend: IntegrationStubNotificationBackend,
        db: Database,
    ):
        """Full lifecycle: init -> track -> sync -> get_forks -> digest -> deliver."""
        # Step 1: Init discovers repos
        discovered = await hub.init("alice")
        assert len(discovered) >= 2
        owned_names = {r.full_name for r in discovered if r.tracking_mode == TrackingMode.OWNED}
        assert "alice/web-framework" in owned_names
        assert "alice/cli-tool" in owned_names

        # Step 2: Sync all tracked repos
        sync_result = await hub.sync()
        assert isinstance(sync_result, SyncResult)
        assert sync_result.repos_synced >= 2

        # Step 3: Get forks for a tracked repo
        forks = await hub.get_forks("alice", "web-framework")
        assert len(forks) == 2
        fork_owners = {f["owner"] if isinstance(f, dict) else f.owner for f in forks}
        assert "bob" in fork_owners
        assert "charlie" in fork_owners

        # Step 4: Generate a digest
        digest = await hub.generate_digest()
        assert isinstance(digest, Digest)
        assert digest.title  # should have a title

        # Step 5: Deliver the digest
        results = await hub.deliver_digest(digest)
        assert len(results) == 1
        assert results[0].success is True
        assert len(backend.delivered) == 1


@pytest.mark.integration
class TestCustomProviderInjection:
    async def test_custom_providers_are_used(
        self,
        db: Database,
        settings: ForkHubSettings,
    ):
        """Custom injected providers should be used throughout the pipeline."""
        from forkhub import ForkHub

        custom_provider = IntegrationStubGitProvider()
        custom_backend = IntegrationStubNotificationBackend(name="custom")
        custom_embeddings = IntegrationStubEmbeddingProvider()

        hub = ForkHub(
            settings=settings,
            git_provider=custom_provider,
            notification_backends=[custom_backend],
            embedding_provider=custom_embeddings,
            db=db,
        )

        # Track and sync to exercise the provider
        await hub.track("alice", "web-framework")
        await hub.sync(repo="alice/web-framework")

        # The provider's call_log should show it was used
        assert any("get_forks" in call for call in custom_provider._call_log)

        # Generate and deliver digest to exercise the backend
        digest = await hub.generate_digest()
        await hub.deliver_digest(digest)
        assert len(custom_backend.delivered) == 1
        assert custom_backend.delivered[0].id == digest.id


@pytest.mark.integration
class TestEmptySync:
    async def test_sync_with_no_forks_changed(
        self,
        hub,
        db: Database,
    ):
        """Sync when no forks have changed should return empty results."""
        # Track a repo that has no forks configured in the stub
        await hub.track("upstream", "original")
        result = await hub.sync(repo="upstream/original")
        assert isinstance(result, SyncResult)
        assert result.repos_synced == 1
        # No forks for upstream/original, so no changed forks
        assert result.total_changed_forks == 0


@pytest.mark.integration
class TestMultipleRepos:
    async def test_track_multiple_repos_sync_all(
        self,
        hub,
        db: Database,
    ):
        """Track multiple repos, sync all, and verify aggregated results."""
        await hub.track("alice", "web-framework")
        await hub.track("alice", "cli-tool")

        # Sync all
        result = await hub.sync()
        assert result.repos_synced == 2
        assert len(result.results) == 2

        # Verify repos are listed
        repos = await hub.get_repos()
        assert len(repos) == 2
        names = {r.full_name for r in repos}
        assert names == {"alice/web-framework", "alice/cli-tool"}

        # Verify forks per repo
        web_forks = await hub.get_forks("alice", "web-framework")
        cli_forks = await hub.get_forks("alice", "cli-tool")
        assert len(web_forks) == 2
        assert len(cli_forks) == 1

    async def test_untrack_one_of_multiple(
        self,
        hub,
        db: Database,
    ):
        """Untracking one repo should not affect others."""
        await hub.track("alice", "web-framework")
        await hub.track("alice", "cli-tool")

        await hub.untrack("alice", "web-framework")

        repos = await hub.get_repos()
        assert len(repos) == 1
        assert repos[0].full_name == "alice/cli-tool"

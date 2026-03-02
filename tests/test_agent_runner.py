# ABOUTME: Tests for the AnalysisRunner orchestration layer.
# ABOUTME: Covers prompt building, batching logic, and options configuration.

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from forkhub.config import ForkHubSettings
from forkhub.database import Database
from forkhub.models import (
    CommitInfo,
    CompareResult,
    Fork,
    ForkPage,
    RateLimitInfo,
    Release,
    RepoInfo,
    TrackedRepo,
)

# ---------------------------------------------------------------------------
# Stub providers
# ---------------------------------------------------------------------------


class StubGitProvider:
    """Stub GitProvider that satisfies the protocol without making real API calls."""

    async def get_user_repos(self, username: str) -> list[RepoInfo]:
        return []

    async def get_forks(self, owner: str, repo: str, *, page: int = 1) -> ForkPage:
        return ForkPage(forks=[], total_count=0, page=page, has_next=False)

    async def compare(self, owner: str, repo: str, base: str, head: str) -> CompareResult:
        return CompareResult(ahead_by=0, behind_by=0, files=[], commits=[])

    async def get_releases(
        self, owner: str, repo: str, *, since: datetime | None = None
    ) -> list[Release]:
        return []

    async def get_repo(self, owner: str, repo: str) -> RepoInfo:
        return RepoInfo(
            github_id=1,
            owner=owner,
            name=repo,
            full_name=f"{owner}/{repo}",
            default_branch="main",
            description=None,
            is_fork=False,
            parent_full_name=None,
            stars=0,
            forks_count=0,
            last_pushed_at=None,
        )

    async def get_commit_messages(
        self, owner: str, repo: str, *, since: str | None = None
    ) -> list[CommitInfo]:
        return []

    async def get_file_diff(self, owner: str, repo: str, base: str, head: str, path: str) -> str:
        return ""

    async def get_rate_limit(self) -> RateLimitInfo:
        return RateLimitInfo(limit=5000, remaining=5000, reset_at=datetime.now(tz=UTC))


class StubEmbeddingProvider:
    """Stub EmbeddingProvider that satisfies the protocol without loading models."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 384 for _ in texts]

    def dimensions(self) -> int:
        return 384


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tracked_repo(**overrides) -> TrackedRepo:
    """Create a TrackedRepo model for testing."""
    defaults = {
        "github_id": 12345,
        "owner": "torvalds",
        "name": "linux",
        "full_name": "torvalds/linux",
        "tracking_mode": "owned",
        "default_branch": "main",
        "description": "Linux kernel source tree",
    }
    defaults.update(overrides)
    return TrackedRepo(**defaults)


def _make_fork(tracked_repo_id: str, owner: str = "gregkh", **overrides) -> Fork:
    """Create a Fork model for testing."""
    defaults = {
        "tracked_repo_id": tracked_repo_id,
        "github_id": 67890,
        "owner": owner,
        "full_name": f"{owner}/linux",
        "default_branch": "main",
        "commits_ahead": 5,
        "commits_behind": 2,
        "head_sha": "abc123",
    }
    defaults.update(overrides)
    return Fork(**defaults)


def _make_release(**overrides) -> Release:
    """Create a Release model for testing."""
    defaults = {
        "tag": "v6.8",
        "name": "Linux 6.8",
        "body": "Major kernel release with performance improvements",
        "published_at": datetime.now(tz=UTC),
        "is_prerelease": False,
    }
    defaults.update(overrides)
    return Release(**defaults)


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
def embedding_provider() -> StubEmbeddingProvider:
    return StubEmbeddingProvider()


@pytest.fixture
def settings() -> ForkHubSettings:
    return ForkHubSettings()


@pytest.fixture
def runner(db, provider, embedding_provider, settings):
    from forkhub.agent.runner import AnalysisRunner

    return AnalysisRunner(
        db=db,
        provider=provider,
        embedding_provider=embedding_provider,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Coordinator prompt tests
# ---------------------------------------------------------------------------


class TestBuildCoordinatorPrompt:
    def test_includes_repo_name(self, runner):
        """The coordinator prompt should include the tracked repo's full name."""
        repo = _make_tracked_repo()
        forks = [_make_fork(repo.id)]
        releases: list[Release] = []

        prompt = runner._build_coordinator_prompt(repo, forks, releases)

        assert "torvalds/linux" in prompt

    def test_includes_fork_names(self, runner):
        """The coordinator prompt should list each changed fork's owner/name."""
        repo = _make_tracked_repo()
        fork1 = _make_fork(repo.id, owner="alice", github_id=100, full_name="alice/linux")
        fork2 = _make_fork(repo.id, owner="bob", github_id=200, full_name="bob/linux")

        prompt = runner._build_coordinator_prompt(repo, [fork1, fork2], [])

        assert "alice/linux" in prompt
        assert "bob/linux" in prompt

    def test_includes_commits_ahead(self, runner):
        """The prompt should include commits-ahead count for each fork."""
        repo = _make_tracked_repo()
        fork = _make_fork(repo.id, commits_ahead=42)

        prompt = runner._build_coordinator_prompt(repo, [fork], [])

        assert "42" in prompt

    def test_includes_release_info(self, runner):
        """The prompt should include new release tags when present."""
        repo = _make_tracked_repo()
        release = _make_release(tag="v6.8", name="Linux 6.8")

        prompt = runner._build_coordinator_prompt(repo, [], [release])

        assert "v6.8" in prompt

    def test_includes_release_body_summary(self, runner):
        """The prompt should include release body content."""
        repo = _make_tracked_repo()
        release = _make_release(body="Major performance improvements and security fixes")

        prompt = runner._build_coordinator_prompt(repo, [], [release])

        assert "performance improvements" in prompt.lower() or "Major" in prompt

    def test_empty_forks_and_releases(self, runner):
        """Prompt should be valid even with no forks or releases."""
        repo = _make_tracked_repo()

        prompt = runner._build_coordinator_prompt(repo, [], [])

        assert "torvalds/linux" in prompt
        # Should still be a valid prompt string
        assert len(prompt) > 0

    def test_includes_description_when_available(self, runner):
        """The prompt should include the repo description if present."""
        repo = _make_tracked_repo(description="Linux kernel source tree")

        prompt = runner._build_coordinator_prompt(repo, [], [])

        assert "Linux kernel source tree" in prompt


# ---------------------------------------------------------------------------
# Batching tests
# ---------------------------------------------------------------------------


class TestBatching:
    def test_small_batch_produces_one_batch(self, runner):
        """Fewer than 30 forks should result in a single batch."""
        repo = _make_tracked_repo()
        forks = [
            _make_fork(repo.id, owner=f"user{i}", github_id=i, full_name=f"user{i}/linux")
            for i in range(20)
        ]

        batches = runner._create_batches(forks)

        assert len(batches) == 1
        assert len(batches[0]) == 20

    def test_exactly_30_forks_produces_one_batch(self, runner):
        """Exactly 30 forks should fit in a single batch."""
        repo = _make_tracked_repo()
        forks = [
            _make_fork(repo.id, owner=f"user{i}", github_id=i, full_name=f"user{i}/linux")
            for i in range(30)
        ]

        batches = runner._create_batches(forks)

        assert len(batches) == 1

    def test_60_forks_produce_two_batches(self, runner):
        """60 forks should be split into 2 batches of 30."""
        repo = _make_tracked_repo()
        forks = [
            _make_fork(repo.id, owner=f"user{i}", github_id=i, full_name=f"user{i}/linux")
            for i in range(60)
        ]

        batches = runner._create_batches(forks)

        assert len(batches) == 2
        assert len(batches[0]) == 30
        assert len(batches[1]) == 30

    def test_31_forks_produce_two_batches(self, runner):
        """31 forks should be split into 2 batches (30 + 1)."""
        repo = _make_tracked_repo()
        forks = [
            _make_fork(repo.id, owner=f"user{i}", github_id=i, full_name=f"user{i}/linux")
            for i in range(31)
        ]

        batches = runner._create_batches(forks)

        assert len(batches) == 2
        assert len(batches[0]) == 30
        assert len(batches[1]) == 1

    def test_batches_preserve_all_forks(self, runner):
        """All forks should be present across all batches."""
        repo = _make_tracked_repo()
        forks = [
            _make_fork(repo.id, owner=f"user{i}", github_id=i, full_name=f"user{i}/linux")
            for i in range(75)
        ]

        batches = runner._create_batches(forks)

        total_forks = sum(len(batch) for batch in batches)
        assert total_forks == 75

    def test_empty_forks_produce_empty_batches(self, runner):
        """Empty fork list should produce no batches."""
        batches = runner._create_batches([])

        assert len(batches) == 0


# ---------------------------------------------------------------------------
# Options configuration tests
# ---------------------------------------------------------------------------


class TestOptionsConfiguration:
    def test_budget_from_settings(self, runner, settings):
        """Options should use the budget from settings."""
        options = runner._build_options(system_prompt="test", mcp_server=None)

        assert options.max_budget_usd == settings.anthropic.analysis_budget_usd

    def test_model_from_settings(self, runner, settings):
        """Options should use the model from settings."""
        options = runner._build_options(system_prompt="test", mcp_server=None)

        assert options.model == settings.anthropic.model

    def test_bypass_permissions_mode(self, runner):
        """Options should use bypassPermissions mode for automated analysis."""
        options = runner._build_options(system_prompt="test", mcp_server=None)

        assert options.permission_mode == "bypassPermissions"

    def test_max_turns_set(self, runner):
        """Options should have a max_turns limit to prevent runaway sessions."""
        options = runner._build_options(system_prompt="test", mcp_server=None)

        assert options.max_turns is not None
        assert options.max_turns > 0

    def test_agents_include_diff_analyst(self, runner):
        """Options should include the diff-analyst subagent."""
        options = runner._build_options(system_prompt="test", mcp_server=None)

        assert "diff-analyst" in options.agents

    def test_hooks_include_cost_tracker(self, runner):
        """Options should include the cost tracker PostToolUse hook."""
        options = runner._build_options(system_prompt="test", mcp_server=None)

        assert "PostToolUse" in options.hooks
        assert len(options.hooks["PostToolUse"]) > 0

    def test_hooks_include_rate_limit_guard(self, runner):
        """Options should include the rate limit guard PreToolUse hook."""
        options = runner._build_options(system_prompt="test", mcp_server=None)

        assert "PreToolUse" in options.hooks
        assert len(options.hooks["PreToolUse"]) > 0


# ---------------------------------------------------------------------------
# Integration test placeholder (requires ANTHROPIC_API_KEY)
# ---------------------------------------------------------------------------


class TestAnalyzeRepoIntegration:
    @pytest.mark.integration
    async def test_analyze_repo_runs_session(self, runner, db):
        """Full integration test that runs an actual agent session.

        Requires ANTHROPIC_API_KEY to be set. Skipped in CI unless
        explicitly enabled with -m integration.
        """
        # This would actually call the Agent SDK, so we skip in unit tests
        pytest.skip("Requires ANTHROPIC_API_KEY and live API access")

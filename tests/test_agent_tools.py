# ABOUTME: Tests for the Agent SDK custom tools used by the analysis agent.
# ABOUTME: Uses stub providers with canned data, calls tool.handler() directly.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from forkhub.database import Database
from forkhub.models import (
    CommitInfo,
    CompareResult,
    FileChange,
    Fork,
    ForkInfo,
    ForkPage,
    ForkVitality,
    RateLimitInfo,
    Release,
    RepoInfo,
    TrackedRepo,
    TrackingMode,
)

# ---------------------------------------------------------------------------
# Time constants
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, tzinfo=UTC)
_RECENT = _NOW - timedelta(days=10)
_OLD = _NOW - timedelta(days=200)


# ---------------------------------------------------------------------------
# StubGitProvider — canned fork/compare/release data
# ---------------------------------------------------------------------------


class StubGitProvider:
    """Stub GitProvider for agent tool testing."""

    def __init__(self) -> None:
        self._forks: dict[str, list[ForkInfo]] = {
            "owner/repo": [
                ForkInfo(
                    github_id=5001,
                    owner="alice",
                    full_name="alice/repo",
                    default_branch="main",
                    description="Alice's fork",
                    stars=20,
                    last_pushed_at=_RECENT,
                    has_diverged=True,
                    created_at=_NOW - timedelta(days=60),
                ),
                ForkInfo(
                    github_id=5002,
                    owner="bob",
                    full_name="bob/repo",
                    default_branch="main",
                    description="Bob's dormant fork",
                    stars=2,
                    last_pushed_at=_OLD,
                    has_diverged=False,
                    created_at=_NOW - timedelta(days=300),
                ),
            ],
        }
        self._compare_results: dict[str, CompareResult] = {
            "alice/repo": CompareResult(
                ahead_by=8,
                behind_by=3,
                files=[
                    FileChange(
                        filename="src/feature.py",
                        status="added",
                        additions=50,
                        deletions=0,
                        patch="+ feature code",
                    ),
                    FileChange(
                        filename="README.md",
                        status="modified",
                        additions=5,
                        deletions=2,
                        patch="updated readme",
                    ),
                ],
                commits=[
                    CommitInfo(
                        sha="aaa111",
                        message="Add cool feature",
                        author="alice",
                        authored_at=_RECENT,
                    ),
                    CommitInfo(
                        sha="aaa222",
                        message="Fix typo",
                        author="alice",
                        authored_at=_RECENT,
                    ),
                ],
            ),
        }
        self._commit_messages: dict[str, list[CommitInfo]] = {
            "alice/repo": [
                CommitInfo(
                    sha="aaa111",
                    message="Add cool feature",
                    author="alice",
                    authored_at=_RECENT,
                ),
            ],
        }
        self._file_diffs: dict[str, str] = {
            "alice/repo::src/feature.py": (
                "--- a/src/feature.py\n"
                "+++ b/src/feature.py\n"
                "@@ -0,0 +1,10 @@\n"
                "+def cool_feature():\n"
                '+    return "cool"'
            ),
        }
        self._releases: dict[str, list[Release]] = {
            "owner/repo": [
                Release(
                    tag="v2.0.0",
                    name="Version 2.0",
                    body="Major release",
                    published_at=_NOW - timedelta(days=1),
                    is_prerelease=False,
                ),
                Release(
                    tag="v1.0.0",
                    name="Version 1.0",
                    body="Initial release",
                    published_at=_NOW - timedelta(days=100),
                    is_prerelease=False,
                ),
            ],
        }
        self._error_on_compare: set[str] = set()

    async def get_user_repos(self, username: str) -> list[RepoInfo]:
        return []

    async def get_repo(self, owner: str, repo: str) -> RepoInfo:
        full_name = f"{owner}/{repo}"
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
        forks = self._forks.get(full_name, [])
        return ForkPage(
            forks=forks,
            total_count=len(forks),
            page=page,
            has_next=False,
        )

    async def compare(self, owner: str, repo: str, base: str, head: str) -> CompareResult:
        fork_owner = head.split(":")[0]
        fork_full = f"{fork_owner}/{repo}"
        if fork_full in self._error_on_compare:
            raise RuntimeError(f"API error for {fork_full}")
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
        full_name = f"{owner}/{repo}"
        return self._commit_messages.get(full_name, [])

    async def get_file_diff(self, owner: str, repo: str, base: str, head: str, path: str) -> str:
        fork_owner = head.split(":")[0]
        key = f"{fork_owner}/{repo}::{path}"
        if key in self._file_diffs:
            return self._file_diffs[key]
        return ""

    async def get_rate_limit(self) -> RateLimitInfo:
        return RateLimitInfo(limit=5000, remaining=4999, reset_at=_NOW)


# ---------------------------------------------------------------------------
# StubEmbeddingProvider — returns deterministic embeddings
# ---------------------------------------------------------------------------


class StubEmbeddingProvider:
    """Stub EmbeddingProvider that returns fixed-dimension vectors."""

    def __init__(self, dims: int = 4) -> None:
        self._dims = dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Return a simple hash-based embedding for each text
        result = []
        for text in texts:
            h = hash(text) % 1000
            vec = [(h + i) / 1000.0 for i in range(self._dims)]
            result.append(vec)
        return result

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
def embedding_provider() -> StubEmbeddingProvider:
    return StubEmbeddingProvider()


@pytest.fixture
def tools(db: Database, provider: StubGitProvider, embedding_provider: StubEmbeddingProvider):
    """Create the tools list via the factory function."""
    from forkhub.agent.tools import create_tools

    return create_tools(
        db=db,
        provider=provider,
        embedding_provider=embedding_provider,
        clock=_NOW,
    )


def _find_tool(tools, name: str):
    """Helper to find a tool by name from the tools list."""
    for t in tools:
        if t.name == name:
            return t
    raise KeyError(f"Tool {name!r} not found in {[t.name for t in tools]}")


async def _insert_tracked_repo(db: Database) -> TrackedRepo:
    """Insert the standard test tracked repo into the database."""
    repo = TrackedRepo(
        github_id=1001,
        owner="owner",
        name="repo",
        full_name="owner/repo",
        tracking_mode=TrackingMode.WATCHED,
        default_branch="main",
    )
    d = repo.model_dump()
    d["created_at"] = repo.created_at.isoformat()
    d["last_synced_at"] = repo.last_synced_at.isoformat() if repo.last_synced_at else None
    await db.insert_tracked_repo(d)
    return repo


async def _insert_fork(
    db: Database,
    tracked_repo_id: str,
    github_id: int = 5001,
    owner: str = "alice",
    full_name: str = "alice/repo",
    stars: int = 20,
    stars_previous: int = 10,
    vitality: ForkVitality = ForkVitality.ACTIVE,
    head_sha: str = "abc123",
    commits_ahead: int = 8,
    commits_behind: int = 3,
) -> Fork:
    """Insert a fork into the database."""
    fork = Fork(
        tracked_repo_id=tracked_repo_id,
        github_id=github_id,
        owner=owner,
        full_name=full_name,
        default_branch="main",
        stars=stars,
        stars_previous=stars_previous,
        vitality=vitality,
        head_sha=head_sha,
        commits_ahead=commits_ahead,
        commits_behind=commits_behind,
        last_pushed_at=_RECENT,
    )
    d = fork.model_dump()
    d["created_at"] = fork.created_at.isoformat()
    d["updated_at"] = fork.updated_at.isoformat()
    d["last_pushed_at"] = fork.last_pushed_at.isoformat() if fork.last_pushed_at else None
    await db.insert_fork(d)
    return fork


# ===========================================================================
# list_forks
# ===========================================================================


class TestListForks:
    async def test_returns_paginated_forks(self, tools, db):
        """list_forks should return forks from the provider."""
        await _insert_tracked_repo(db)
        t = _find_tool(tools, "list_forks")
        result = await t.handler(
            {
                "owner": "owner",
                "repo": "repo",
                "page": 1,
                "only_active": False,
            }
        )
        assert "is_error" not in result or not result.get("is_error")
        text = result["content"][0]["text"]
        data = json.loads(text)
        assert data["page"] == 1
        assert len(data["forks"]) == 2
        assert data["forks"][0]["full_name"] == "alice/repo"

    async def test_only_active_filtering(self, tools, db):
        """list_forks with only_active=True should filter to active forks from DB."""
        repo = await _insert_tracked_repo(db)
        # Insert an active fork and a dormant fork in DB
        await _insert_fork(
            db,
            repo.id,
            github_id=5001,
            owner="alice",
            full_name="alice/repo",
            vitality=ForkVitality.ACTIVE,
        )
        await _insert_fork(
            db,
            repo.id,
            github_id=5002,
            owner="bob",
            full_name="bob/repo",
            vitality=ForkVitality.DORMANT,
            stars=2,
            stars_previous=0,
        )
        t = _find_tool(tools, "list_forks")
        result = await t.handler({"owner": "owner", "repo": "repo", "page": 1, "only_active": True})
        text = result["content"][0]["text"]
        data = json.loads(text)
        # Only the active fork should be returned
        assert len(data["forks"]) == 1
        assert data["forks"][0]["full_name"] == "alice/repo"


# ===========================================================================
# get_fork_summary
# ===========================================================================


class TestGetForkSummary:
    async def test_returns_composite_summary(self, tools, db):
        """get_fork_summary should return fork data + compare + commit info."""
        repo = await _insert_tracked_repo(db)
        await _insert_fork(db, repo.id)
        t = _find_tool(tools, "get_fork_summary")
        result = await t.handler({"fork_full_name": "alice/repo"})
        assert not result.get("is_error", False)
        text = result["content"][0]["text"]
        data = json.loads(text)
        assert data["full_name"] == "alice/repo"
        assert data["commits_ahead"] == 8
        assert data["commits_behind"] == 3
        assert "files_changed" in data
        assert "recent_commits" in data
        assert data["stars"] == 20
        assert data["vitality"] == "active"

    async def test_fork_not_found(self, tools, db):
        """get_fork_summary should return error when fork not in DB."""
        t = _find_tool(tools, "get_fork_summary")
        result = await t.handler({"fork_full_name": "nobody/nothing"})
        assert result.get("is_error") is True
        assert "not found" in result["content"][0]["text"].lower()


# ===========================================================================
# get_file_diff
# ===========================================================================


class TestGetFileDiff:
    async def test_returns_diff_string(self, tools, db):
        """get_file_diff should return the patch text for a specific file."""
        repo = await _insert_tracked_repo(db)
        await _insert_fork(db, repo.id)
        t = _find_tool(tools, "get_file_diff")
        result = await t.handler({"fork_full_name": "alice/repo", "file_path": "src/feature.py"})
        assert not result.get("is_error", False)
        text = result["content"][0]["text"]
        data = json.loads(text)
        assert "diff" in data
        assert "cool_feature" in data["diff"]

    async def test_fork_not_found_error(self, tools, db):
        """get_file_diff should return error when fork not in DB."""
        t = _find_tool(tools, "get_file_diff")
        result = await t.handler({"fork_full_name": "nobody/nothing", "file_path": "foo.py"})
        assert result.get("is_error") is True


# ===========================================================================
# get_releases
# ===========================================================================


class TestGetReleases:
    async def test_returns_filtered_releases(self, tools):
        """get_releases should return releases filtered by since_days."""
        t = _find_tool(tools, "get_releases")
        result = await t.handler({"owner": "owner", "repo": "repo", "since_days": 30})
        assert not result.get("is_error", False)
        text = result["content"][0]["text"]
        data = json.loads(text)
        # Only v2.0.0 is within 30 days, v1.0.0 is 100 days old
        assert len(data["releases"]) == 1
        assert data["releases"][0]["tag"] == "v2.0.0"

    async def test_returns_all_releases_with_large_since(self, tools):
        """get_releases with large since_days should return all releases."""
        t = _find_tool(tools, "get_releases")
        result = await t.handler({"owner": "owner", "repo": "repo", "since_days": 365})
        text = result["content"][0]["text"]
        data = json.loads(text)
        assert len(data["releases"]) == 2


# ===========================================================================
# get_fork_stars
# ===========================================================================


class TestGetForkStars:
    async def test_returns_star_data_with_velocity(self, tools, db):
        """get_fork_stars should return stars, stars_previous, and velocity."""
        repo = await _insert_tracked_repo(db)
        await _insert_fork(db, repo.id, stars=20, stars_previous=10)
        t = _find_tool(tools, "get_fork_stars")
        result = await t.handler({"fork_full_name": "alice/repo"})
        assert not result.get("is_error", False)
        text = result["content"][0]["text"]
        data = json.loads(text)
        assert data["stars"] == 20
        assert data["stars_previous"] == 10
        assert data["velocity"] == 10

    async def test_fork_not_found_error(self, tools, db):
        """get_fork_stars should return error when fork not in DB."""
        t = _find_tool(tools, "get_fork_stars")
        result = await t.handler({"fork_full_name": "nobody/nothing"})
        assert result.get("is_error") is True


# ===========================================================================
# store_signal
# ===========================================================================


class TestStoreSignal:
    async def test_persists_signal_and_returns_id(self, tools, db):
        """store_signal should insert a signal row and return its ID."""
        repo = await _insert_tracked_repo(db)
        await _insert_fork(db, repo.id)
        t = _find_tool(tools, "store_signal")
        result = await t.handler(
            {
                "fork_full_name": "alice/repo",
                "category": "feature",
                "summary": "Adds a cool feature",
                "significance": 7,
                "files_involved": ["src/feature.py"],
                "detail": "This fork adds a really cool feature.",
            }
        )
        assert not result.get("is_error", False)
        text = result["content"][0]["text"]
        data = json.loads(text)
        assert "signal_id" in data
        # Verify signal is in the DB
        signals = await db.list_signals(repo.id)
        assert len(signals) == 1
        assert signals[0]["category"] == "feature"
        assert signals[0]["summary"] == "Adds a cool feature"
        assert signals[0]["significance"] == 7

    async def test_rejects_invalid_category(self, tools, db):
        """store_signal should return error for an invalid category."""
        repo = await _insert_tracked_repo(db)
        await _insert_fork(db, repo.id)
        t = _find_tool(tools, "store_signal")
        result = await t.handler(
            {
                "fork_full_name": "alice/repo",
                "category": "invalid_category",
                "summary": "Bad signal",
                "significance": 5,
                "files_involved": [],
                "detail": "",
            }
        )
        assert result.get("is_error") is True
        assert "invalid" in result["content"][0]["text"].lower()

    async def test_fork_not_found_error(self, tools, db):
        """store_signal should return error when fork not in DB."""
        t = _find_tool(tools, "store_signal")
        result = await t.handler(
            {
                "fork_full_name": "nobody/nothing",
                "category": "feature",
                "summary": "Some signal",
                "significance": 5,
                "files_involved": [],
                "detail": "",
            }
        )
        assert result.get("is_error") is True


# ===========================================================================
# search_similar_signals
# ===========================================================================


class TestSearchSimilarSignals:
    async def test_returns_results(self, tools, db):
        """search_similar_signals should return results (may be empty without vec)."""
        repo = await _insert_tracked_repo(db)
        t = _find_tool(tools, "search_similar_signals")
        result = await t.handler(
            {
                "summary_text": "cool feature addition",
                "repo_id": repo.id,
                "limit": 5,
            }
        )
        assert not result.get("is_error", False)
        text = result["content"][0]["text"]
        data = json.loads(text)
        assert "similar_signals" in data
        # Without sqlite-vec, should return empty list
        assert isinstance(data["similar_signals"], list)


# ===========================================================================
# Error handling
# ===========================================================================


class TestToolErrorHandling:
    async def test_list_forks_handles_provider_error(self, db, embedding_provider):
        """list_forks should return error dict when provider raises."""
        from forkhub.agent.tools import create_tools

        class BrokenProvider(StubGitProvider):
            async def get_forks(self, owner, repo, *, page=1):
                raise RuntimeError("Connection failed")

        broken = BrokenProvider()
        broken_tools = create_tools(db=db, provider=broken, embedding_provider=embedding_provider)
        t = _find_tool(broken_tools, "list_forks")
        result = await t.handler({"owner": "x", "repo": "y", "page": 1, "only_active": False})
        assert result.get("is_error") is True
        assert "error" in result["content"][0]["text"].lower()

    async def test_get_file_diff_handles_provider_error(self, db, embedding_provider):
        """get_file_diff should return error dict when provider raises."""
        from forkhub.agent.tools import create_tools

        class BrokenDiffProvider(StubGitProvider):
            async def get_file_diff(self, owner, repo, base, head, path):
                raise RuntimeError("Diff failed")

        repo = await _insert_tracked_repo(db)
        await _insert_fork(db, repo.id)

        broken = BrokenDiffProvider()
        broken_tools = create_tools(db=db, provider=broken, embedding_provider=embedding_provider)
        t = _find_tool(broken_tools, "get_file_diff")
        result = await t.handler({"fork_full_name": "alice/repo", "file_path": "src/feature.py"})
        assert result.get("is_error") is True

    async def test_store_signal_handles_db_error(self, tools, db, provider, embedding_provider):
        """store_signal should return error dict if DB insertion fails."""
        # Close the DB to trigger an error
        await db.close()
        from forkhub.agent.tools import create_tools

        # Recreate tools with the closed DB to trigger errors
        broken_tools = create_tools(db=db, provider=provider, embedding_provider=embedding_provider)
        t = _find_tool(broken_tools, "store_signal")
        result = await t.handler(
            {
                "fork_full_name": "alice/repo",
                "category": "feature",
                "summary": "test",
                "significance": 5,
                "files_involved": [],
                "detail": "",
            }
        )
        assert result.get("is_error") is True


# ===========================================================================
# Tool list completeness
# ===========================================================================


class TestToolCompleteness:
    def test_all_seven_tools_created(self, tools):
        """create_tools should return exactly 7 tools with the expected names."""
        names = {t.name for t in tools}
        expected = {
            "list_forks",
            "get_fork_summary",
            "get_file_diff",
            "get_releases",
            "get_fork_stars",
            "store_signal",
            "search_similar_signals",
        }
        assert names == expected
        assert len(tools) == 7

# ABOUTME: Tests for the GitHub API provider (GitHubProvider).
# ABOUTME: Uses respx to mock httpx calls made by githubkit under the hood.
from __future__ import annotations

from datetime import UTC, datetime

import pytest
import respx
from httpx import Response

from forkhub.interfaces import GitProvider
from forkhub.models import (
    CommitInfo,
    CompareResult,
    FileChange,
    ForkInfo,
    ForkPage,
    RateLimitInfo,
    Release,
    RepoInfo,
)
from forkhub.providers.github import GitHubProvider, GitHubProviderError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def provider() -> GitHubProvider:
    """Create a GitHubProvider with a test token."""
    return GitHubProvider(token="test-token-abc123")


@pytest.fixture
def mock_github():
    """Set up respx to mock GitHub API calls."""
    with respx.mock(base_url="https://api.github.com") as mock:
        yield mock


# ---------------------------------------------------------------------------
# Helpers: JSON response factories
# ---------------------------------------------------------------------------


def _repo_json(
    *,
    repo_id: int = 1001,
    owner: str = "octocat",
    name: str = "hello-world",
    default_branch: str = "main",
    description: str = "A test repo",
    fork: bool = False,
    parent_full_name: str | None = None,
    stargazers_count: int = 42,
    forks_count: int = 5,
    pushed_at: str = "2025-06-01T12:00:00Z",
) -> dict:
    """Build a minimal GitHub repo JSON object."""
    result = {
        "id": repo_id,
        "owner": {"login": owner},
        "name": name,
        "full_name": f"{owner}/{name}",
        "default_branch": default_branch,
        "description": description,
        "fork": fork,
        "stargazers_count": stargazers_count,
        "forks_count": forks_count,
        "pushed_at": pushed_at,
    }
    if parent_full_name:
        parent_owner, parent_name = parent_full_name.split("/")
        result["parent"] = {
            "full_name": parent_full_name,
            "owner": {"login": parent_owner},
            "name": parent_name,
        }
    return result


def _fork_json(
    *,
    fork_id: int = 2001,
    owner: str = "contributor",
    name: str = "hello-world",
    default_branch: str = "main",
    description: str = "A fork",
    stargazers_count: int = 3,
    pushed_at: str = "2025-07-15T08:30:00Z",
    created_at: str = "2025-01-10T00:00:00Z",
) -> dict:
    """Build a minimal GitHub fork JSON object."""
    return {
        "id": fork_id,
        "owner": {"login": owner},
        "name": name,
        "full_name": f"{owner}/{name}",
        "default_branch": default_branch,
        "description": description,
        "fork": True,
        "stargazers_count": stargazers_count,
        "forks_count": 0,
        "pushed_at": pushed_at,
        "created_at": created_at,
    }


def _commit_json(
    *,
    sha: str = "abc123def456",
    message: str = "fix: resolve edge case",
    author_login: str = "dev",
    authored_at: str = "2025-07-20T10:00:00Z",
) -> dict:
    """Build a minimal GitHub commit JSON object."""
    return {
        "sha": sha,
        "commit": {
            "message": message,
            "author": {
                "name": author_login,
                "date": authored_at,
            },
        },
        "author": {"login": author_login},
    }


def _file_change_json(
    *,
    filename: str = "src/main.py",
    status: str = "modified",
    additions: int = 10,
    deletions: int = 3,
    patch: str = "@@ -1,5 +1,7 @@\n-old\n+new",
) -> dict:
    """Build a minimal GitHub file change JSON object."""
    return {
        "filename": filename,
        "status": status,
        "additions": additions,
        "deletions": deletions,
        "patch": patch,
    }


def _release_json(
    *,
    tag_name: str = "v1.0.0",
    name: str = "Release 1.0.0",
    body: str = "First stable release",
    published_at: str = "2025-06-15T00:00:00Z",
    prerelease: bool = False,
) -> dict:
    """Build a minimal GitHub release JSON object."""
    return {
        "tag_name": tag_name,
        "name": name,
        "body": body,
        "published_at": published_at,
        "prerelease": prerelease,
    }


# ===========================================================================
# Test: Protocol conformance
# ===========================================================================


class TestProtocolConformance:
    """GitHubProvider must satisfy the GitProvider protocol."""

    def test_is_instance_of_git_provider(self) -> None:
        provider = GitHubProvider(token="test")
        assert isinstance(provider, GitProvider)


# ===========================================================================
# Test: get_user_repos
# ===========================================================================


class TestGetUserRepos:
    """Tests for GitHubProvider.get_user_repos."""

    async def test_returns_list_of_repo_info(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/users/octocat/repos").mock(
            return_value=Response(
                200,
                json=[
                    _repo_json(repo_id=1, owner="octocat", name="repo-a", stargazers_count=10),
                    _repo_json(repo_id=2, owner="octocat", name="repo-b", stargazers_count=20),
                ],
            ),
        )

        repos = await provider.get_user_repos("octocat")

        assert len(repos) == 2
        assert all(isinstance(r, RepoInfo) for r in repos)
        assert repos[0].name == "repo-a"
        assert repos[0].owner == "octocat"
        assert repos[0].stars == 10
        assert repos[1].name == "repo-b"
        assert repos[1].stars == 20

    async def test_maps_fork_fields(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/users/someone/repos").mock(
            return_value=Response(
                200,
                json=[
                    _repo_json(
                        repo_id=5,
                        owner="someone",
                        name="forked-lib",
                        fork=True,
                        parent_full_name="upstream/forked-lib",
                    ),
                ],
            ),
        )

        repos = await provider.get_user_repos("someone")

        assert len(repos) == 1
        assert repos[0].is_fork is True
        assert repos[0].parent_full_name == "upstream/forked-lib"

    async def test_empty_repos(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/users/nobody/repos").mock(
            return_value=Response(200, json=[]),
        )

        repos = await provider.get_user_repos("nobody")
        assert repos == []


# ===========================================================================
# Test: get_repo
# ===========================================================================


class TestGetRepo:
    """Tests for GitHubProvider.get_repo."""

    async def test_returns_repo_info(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/repos/octocat/hello-world").mock(
            return_value=Response(
                200,
                json=_repo_json(
                    repo_id=42,
                    owner="octocat",
                    name="hello-world",
                    description="My first repo",
                    stargazers_count=100,
                    forks_count=25,
                ),
            ),
        )

        repo = await provider.get_repo("octocat", "hello-world")

        assert isinstance(repo, RepoInfo)
        assert repo.github_id == 42
        assert repo.owner == "octocat"
        assert repo.name == "hello-world"
        assert repo.full_name == "octocat/hello-world"
        assert repo.description == "My first repo"
        assert repo.stars == 100
        assert repo.forks_count == 25
        assert repo.default_branch == "main"
        assert repo.is_fork is False

    async def test_repo_not_found_raises(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/repos/ghost/nope").mock(
            return_value=Response(404, json={"message": "Not Found"}),
        )

        with pytest.raises(GitHubProviderError):
            await provider.get_repo("ghost", "nope")


# ===========================================================================
# Test: get_forks
# ===========================================================================


class TestGetForks:
    """Tests for GitHubProvider.get_forks."""

    async def test_returns_fork_page(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/repos/octocat/hello-world/forks").mock(
            return_value=Response(
                200,
                json=[
                    _fork_json(fork_id=100, owner="alice"),
                    _fork_json(fork_id=101, owner="bob"),
                ],
                headers={"Link": ""},
            ),
        )

        page = await provider.get_forks("octocat", "hello-world")

        assert isinstance(page, ForkPage)
        assert len(page.forks) == 2
        assert all(isinstance(f, ForkInfo) for f in page.forks)
        assert page.forks[0].owner == "alice"
        assert page.forks[1].owner == "bob"
        assert page.page == 1

    async def test_fork_pagination_has_next(self, provider: GitHubProvider, mock_github) -> None:
        # GitHub signals "next page" via a Link header
        forks_data = [_fork_json(fork_id=i, owner=f"user{i}") for i in range(30)]
        mock_github.get("/repos/octocat/hello-world/forks").mock(
            return_value=Response(
                200,
                json=forks_data,
                headers={
                    "Link": (
                        "<https://api.github.com/repos/octocat/hello-world/"
                        'forks?page=2>; rel="next"'
                    )
                },
            ),
        )

        page = await provider.get_forks("octocat", "hello-world", page=1)

        assert page.has_next is True
        assert len(page.forks) == 30

    async def test_fork_pagination_no_next(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/repos/octocat/hello-world/forks").mock(
            return_value=Response(
                200,
                json=[_fork_json(fork_id=200, owner="solo")],
                headers={},
            ),
        )

        page = await provider.get_forks("octocat", "hello-world", page=1)

        assert page.has_next is False
        assert page.total_count == 1


# ===========================================================================
# Test: compare
# ===========================================================================


class TestCompare:
    """Tests for GitHubProvider.compare."""

    async def test_returns_compare_result(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/repos/octocat/hello-world/compare/main...feature").mock(
            return_value=Response(
                200,
                json={
                    "ahead_by": 3,
                    "behind_by": 1,
                    "files": [
                        _file_change_json(filename="README.md", status="modified"),
                        _file_change_json(filename="new_file.py", status="added"),
                    ],
                    "commits": [
                        _commit_json(sha="aaa111", message="feat: add widget"),
                        _commit_json(sha="bbb222", message="fix: typo"),
                        _commit_json(sha="ccc333", message="docs: update readme"),
                    ],
                },
            ),
        )

        result = await provider.compare("octocat", "hello-world", "main", "feature")

        assert isinstance(result, CompareResult)
        assert result.ahead_by == 3
        assert result.behind_by == 1
        assert len(result.files) == 2
        assert all(isinstance(f, FileChange) for f in result.files)
        assert result.files[0].filename == "README.md"
        assert result.files[1].filename == "new_file.py"
        assert len(result.commits) == 3
        assert all(isinstance(c, CommitInfo) for c in result.commits)
        assert result.commits[0].sha == "aaa111"
        assert result.commits[0].message == "feat: add widget"

    async def test_compare_no_changes(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/repos/octocat/hello-world/compare/main...main").mock(
            return_value=Response(
                200,
                json={
                    "ahead_by": 0,
                    "behind_by": 0,
                    "files": [],
                    "commits": [],
                },
            ),
        )

        result = await provider.compare("octocat", "hello-world", "main", "main")

        assert result.ahead_by == 0
        assert result.behind_by == 0
        assert result.files == []
        assert result.commits == []


# ===========================================================================
# Test: get_releases
# ===========================================================================


class TestGetReleases:
    """Tests for GitHubProvider.get_releases."""

    async def test_returns_releases(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/repos/octocat/hello-world/releases").mock(
            return_value=Response(
                200,
                json=[
                    _release_json(tag_name="v2.0.0", published_at="2025-08-01T00:00:00Z"),
                    _release_json(
                        tag_name="v1.0.0-beta",
                        prerelease=True,
                        published_at="2025-06-01T00:00:00Z",
                    ),
                ],
            ),
        )

        releases = await provider.get_releases("octocat", "hello-world")

        assert len(releases) == 2
        assert all(isinstance(r, Release) for r in releases)
        assert releases[0].tag == "v2.0.0"
        assert releases[0].is_prerelease is False
        assert releases[1].tag == "v1.0.0-beta"
        assert releases[1].is_prerelease is True

    async def test_filters_by_since(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/repos/octocat/hello-world/releases").mock(
            return_value=Response(
                200,
                json=[
                    _release_json(
                        tag_name="v2.0.0",
                        published_at="2025-08-01T00:00:00Z",
                    ),
                    _release_json(
                        tag_name="v1.0.0",
                        published_at="2025-01-01T00:00:00Z",
                    ),
                ],
            ),
        )

        since = datetime(2025, 6, 1, tzinfo=UTC)
        releases = await provider.get_releases("octocat", "hello-world", since=since)

        # Only v2.0.0 is after the since cutoff
        assert len(releases) == 1
        assert releases[0].tag == "v2.0.0"

    async def test_no_releases(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/repos/octocat/hello-world/releases").mock(
            return_value=Response(200, json=[]),
        )

        releases = await provider.get_releases("octocat", "hello-world")
        assert releases == []


# ===========================================================================
# Test: get_commit_messages
# ===========================================================================


class TestGetCommitMessages:
    """Tests for GitHubProvider.get_commit_messages."""

    async def test_returns_commit_info_list(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/repos/octocat/hello-world/commits").mock(
            return_value=Response(
                200,
                json=[
                    _commit_json(sha="aaa", message="feat: new feature", author_login="alice"),
                    _commit_json(sha="bbb", message="fix: bug fix", author_login="bob"),
                ],
            ),
        )

        commits = await provider.get_commit_messages("octocat", "hello-world")

        assert len(commits) == 2
        assert all(isinstance(c, CommitInfo) for c in commits)
        assert commits[0].sha == "aaa"
        assert commits[0].message == "feat: new feature"
        assert commits[0].author == "alice"
        assert commits[1].sha == "bbb"

    async def test_passes_since_param(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/repos/octocat/hello-world/commits").mock(
            return_value=Response(
                200,
                json=[_commit_json(sha="recent", message="latest")],
            ),
        )

        commits = await provider.get_commit_messages(
            "octocat", "hello-world", since="2025-07-01T00:00:00Z"
        )

        assert len(commits) == 1
        assert commits[0].sha == "recent"


# ===========================================================================
# Test: get_file_diff
# ===========================================================================


class TestGetFileDiff:
    """Tests for GitHubProvider.get_file_diff."""

    async def test_returns_patch_for_specific_file(
        self, provider: GitHubProvider, mock_github
    ) -> None:
        target_patch = "@@ -1,3 +1,5 @@\n-old line\n+new line\n+added line"
        mock_github.get("/repos/octocat/hello-world/compare/abc...def").mock(
            return_value=Response(
                200,
                json={
                    "ahead_by": 1,
                    "behind_by": 0,
                    "files": [
                        _file_change_json(
                            filename="src/main.py",
                            patch=target_patch,
                        ),
                        _file_change_json(
                            filename="README.md",
                            patch="@@ different patch",
                        ),
                    ],
                    "commits": [],
                },
            ),
        )

        diff = await provider.get_file_diff("octocat", "hello-world", "abc", "def", "src/main.py")

        assert diff == target_patch

    async def test_returns_empty_when_file_not_in_diff(
        self, provider: GitHubProvider, mock_github
    ) -> None:
        mock_github.get("/repos/octocat/hello-world/compare/abc...def").mock(
            return_value=Response(
                200,
                json={
                    "ahead_by": 1,
                    "behind_by": 0,
                    "files": [
                        _file_change_json(filename="other.py"),
                    ],
                    "commits": [],
                },
            ),
        )

        diff = await provider.get_file_diff(
            "octocat", "hello-world", "abc", "def", "nonexistent.py"
        )

        assert diff == ""


# ===========================================================================
# Test: get_rate_limit
# ===========================================================================


class TestGetRateLimit:
    """Tests for GitHubProvider.get_rate_limit."""

    async def test_returns_rate_limit_info(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/rate_limit").mock(
            return_value=Response(
                200,
                json={
                    "resources": {
                        "core": {
                            "limit": 5000,
                            "remaining": 4999,
                            "reset": 1750000000,
                        }
                    }
                },
            ),
        )

        info = await provider.get_rate_limit()

        assert isinstance(info, RateLimitInfo)
        assert info.limit == 5000
        assert info.remaining == 4999
        assert isinstance(info.reset_at, datetime)


# ===========================================================================
# Test: Error handling
# ===========================================================================


class TestErrorHandling:
    """Tests for error responses from the GitHub API."""

    async def test_404_raises_exception(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/repos/ghost/missing").mock(
            return_value=Response(404, json={"message": "Not Found"}),
        )

        with pytest.raises(GitHubProviderError):
            await provider.get_repo("ghost", "missing")

    async def test_rate_limit_exceeded_raises(self, provider: GitHubProvider, mock_github) -> None:
        mock_github.get("/repos/octocat/hello-world").mock(
            return_value=Response(
                403,
                json={"message": "API rate limit exceeded"},
                headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1750000000"},
            ),
        )

        with pytest.raises(GitHubProviderError):
            await provider.get_repo("octocat", "hello-world")

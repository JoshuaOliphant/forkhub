# ABOUTME: Tests for the GitHub API provider (GitHubProvider).
# ABOUTME: Uses respx to mock httpx calls made by githubkit under the hood.
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import respx
from httpx import Response

from forkhub.models import (
    CommitInfo,
    CompareResult,
    FileChange,
    RateLimitInfo,
    RepoInfo,
)
from forkhub.providers.github import GitHubProvider

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
) -> dict[str, Any]:
    """Build a minimal GitHub repo JSON object."""
    result: dict[str, Any] = {
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

    pass


# ===========================================================================
# Test: get_user_repos
# ===========================================================================


class TestGetUserRepos:
    """Tests for GitHubProvider.get_user_repos."""

    pass


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


# ===========================================================================
# Test: get_forks
# ===========================================================================


class TestGetForks:
    """Tests for GitHubProvider.get_forks."""

    pass


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


# ===========================================================================
# Test: get_releases
# ===========================================================================


class TestGetReleases:
    """Tests for GitHubProvider.get_releases."""

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


# ===========================================================================
# Test: get_commit_messages
# ===========================================================================


class TestGetCommitMessages:
    """Tests for GitHubProvider.get_commit_messages."""

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

    async def test_returns_patch_and_empty_for_missing_file(
        self, provider: GitHubProvider, mock_github
    ) -> None:
        target_patch = "@@ -1,3 +1,5 @@\n-old line\n+new line\n+added line"
        compare_json = {
            "ahead_by": 1,
            "behind_by": 0,
            "files": [
                _file_change_json(filename="src/main.py", patch=target_patch),
                _file_change_json(filename="README.md", patch="@@ different patch"),
            ],
            "commits": [],
        }
        mock_github.get("/repos/octocat/hello-world/compare/abc...def").mock(
            return_value=Response(200, json=compare_json),
        )

        # Matching file returns its patch wrapped in git apply-able headers
        diff = await provider.get_file_diff("octocat", "hello-world", "abc", "def", "src/main.py")
        assert diff == (
            "diff --git a/src/main.py b/src/main.py\n"
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            f"{target_patch}\n"
        )

        # Non-matching file returns empty string
        diff = await provider.get_file_diff(
            "octocat", "hello-world", "abc", "def", "nonexistent.py"
        )
        assert diff == ""

    async def test_reconstructs_added_removed_and_rename_headers(
        self, provider: GitHubProvider, mock_github
    ) -> None:
        added_patch = "@@ -0,0 +1,2 @@\n+line one\n+line two"
        removed_patch = "@@ -1,2 +0,0 @@\n-gone one\n-gone two"
        rename_patch = "@@ -1 +1 @@\n-old\n+new"
        copy_patch = "@@ -1 +1,2 @@\n base\n+extra"
        compare_json = {
            "ahead_by": 1,
            "behind_by": 0,
            "files": [
                _file_change_json(filename="new.py", status="added", patch=added_patch),
                _file_change_json(filename="dead.py", status="removed", patch=removed_patch),
                {
                    "filename": "renamed.py",
                    "status": "renamed",
                    "previous_filename": "orig.py",
                    "additions": 1,
                    "deletions": 1,
                    "patch": rename_patch,
                },
                {
                    "filename": "copy.py",
                    "status": "copied",
                    "previous_filename": "source.py",
                    "additions": 1,
                    "deletions": 0,
                    "patch": copy_patch,
                },
                # Binary / pure-rename files arrive with no patch field.
                {"filename": "logo.png", "status": "modified", "additions": 0, "deletions": 0},
            ],
            "commits": [],
        }
        mock_github.get("/repos/octocat/hello-world/compare/abc...def").mock(
            return_value=Response(200, json=compare_json),
        )

        added = await provider.get_file_diff("octocat", "hello-world", "abc", "def", "new.py")
        assert added == (
            "diff --git a/new.py b/new.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/new.py\n"
            f"{added_patch}\n"
        )

        removed = await provider.get_file_diff("octocat", "hello-world", "abc", "def", "dead.py")
        assert removed == (
            "diff --git a/dead.py b/dead.py\n"
            "deleted file mode 100644\n"
            "--- a/dead.py\n"
            "+++ /dev/null\n"
            f"{removed_patch}\n"
        )

        renamed = await provider.get_file_diff("octocat", "hello-world", "abc", "def", "renamed.py")
        assert renamed == (
            "diff --git a/orig.py b/renamed.py\n"
            "rename from orig.py\n"
            "rename to renamed.py\n"
            "--- a/orig.py\n"
            "+++ b/renamed.py\n"
            f"{rename_patch}\n"
        )

        copied = await provider.get_file_diff("octocat", "hello-world", "abc", "def", "copy.py")
        assert copied == (
            "diff --git a/source.py b/copy.py\n"
            "copy from source.py\n"
            "copy to copy.py\n"
            "--- a/source.py\n"
            "+++ b/copy.py\n"
            f"{copy_patch}\n"
        )

        # File with no patch (binary) yields an empty string, not a header-only diff.
        binary = await provider.get_file_diff("octocat", "hello-world", "abc", "def", "logo.png")
        assert binary == ""

    async def test_reconstructed_diff_applies_with_git(
        self, provider: GitHubProvider, mock_github, tmp_path
    ) -> None:
        """The reconstructed diff must satisfy ``git apply`` on a real repo.

        Guards against regressions where GitHub's header-less ``patch`` field
        is returned verbatim (which ``git apply`` rejects).
        """
        import subprocess

        def _run(*args: str, **kw):
            return subprocess.run(args, cwd=tmp_path, check=True, capture_output=True, **kw)

        _run("git", "init")
        _run("git", "config", "user.email", "test@test.com")
        _run("git", "config", "user.name", "Test")
        _run("git", "config", "commit.gpgsign", "false")
        (tmp_path / "cache.py").write_text("old line\nkeep\n")
        _run("git", "add", ".")
        _run("git", "commit", "-m", "init")

        # Hunk-only body, exactly as the compare API returns it.
        patch = "@@ -1,2 +1,2 @@\n-old line\n+new line\n keep"
        compare_json = {
            "ahead_by": 1,
            "behind_by": 0,
            "files": [_file_change_json(filename="cache.py", patch=patch)],
            "commits": [],
        }
        mock_github.get("/repos/octocat/hello-world/compare/abc...def").mock(
            return_value=Response(200, json=compare_json),
        )

        diff = await provider.get_file_diff("octocat", "hello-world", "abc", "def", "cache.py")

        # Actually apply (not just --check) and verify the resulting contents, so
        # an applyable-but-semantically-wrong reconstruction can't pass silently.
        applied = subprocess.run(
            ["git", "apply", "-"],
            cwd=tmp_path,
            input=diff.encode(),
            capture_output=True,
        )
        assert applied.returncode == 0, applied.stderr.decode()
        assert (tmp_path / "cache.py").read_text() == "new line\nkeep\n"


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

    pass

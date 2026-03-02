# ABOUTME: GitHub API provider using githubkit (async).
# ABOUTME: Implements GitProvider protocol with ETag caching and rate limit awareness.
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from githubkit import GitHub, TokenAuthStrategy
from githubkit.exception import RequestError, RequestFailed

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


class GitHubProviderError(Exception):
    """Raised when the GitHub API returns an error response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"GitHub API error {status_code}: {message}")


class GitHubProvider:
    """GitHub API provider using githubkit async client.

    Implements the GitProvider protocol defined in forkhub.interfaces.
    All methods are async and return forkhub Pydantic models.
    """

    def __init__(self, token: str) -> None:
        self._github = GitHub(TokenAuthStrategy(token))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        """Perform an authenticated GET request and return parsed JSON.

        Catches githubkit exceptions and wraps them as GitHubProviderError
        so consumers of this provider don't depend on githubkit internals.
        """
        try:
            resp = await self._github.arequest("GET", url, params=params)
        except RequestFailed as exc:
            status = exc.response.status_code
            try:
                body = exc.response.json()
                msg = body.get("message", f"HTTP {status}")
            except Exception:
                msg = f"HTTP {status}"
            raise GitHubProviderError(status, msg) from exc
        except RequestError as exc:
            raise GitHubProviderError(0, str(exc)) from exc
        return resp.json()

    async def _get_with_headers(
        self, url: str, *, params: dict[str, Any] | None = None
    ) -> tuple[Any, dict[str, str]]:
        """GET request that also returns response headers (for pagination)."""
        try:
            resp = await self._github.arequest("GET", url, params=params)
        except RequestFailed as exc:
            status = exc.response.status_code
            try:
                body = exc.response.json()
                msg = body.get("message", f"HTTP {status}")
            except Exception:
                msg = f"HTTP {status}"
            raise GitHubProviderError(status, msg) from exc
        except RequestError as exc:
            raise GitHubProviderError(0, str(exc)) from exc
        headers = dict(resp.headers)
        return resp.json(), headers

    @staticmethod
    def _has_next_page(headers: dict[str, str]) -> bool:
        """Check if a Link header contains a rel='next' link."""
        link = headers.get("link", "")
        return 'rel="next"' in link

    @staticmethod
    def _parse_repo(data: dict[str, Any]) -> RepoInfo:
        """Map a GitHub API repo JSON object to a RepoInfo model."""
        parent = data.get("parent")
        parent_full_name = parent["full_name"] if parent else None
        pushed_at = data.get("pushed_at")
        return RepoInfo(
            github_id=data["id"],
            owner=data["owner"]["login"],
            name=data["name"],
            full_name=data["full_name"],
            default_branch=data["default_branch"],
            description=data.get("description"),
            is_fork=data.get("fork", False),
            parent_full_name=parent_full_name,
            stars=data.get("stargazers_count", 0),
            forks_count=data.get("forks_count", 0),
            last_pushed_at=datetime.fromisoformat(pushed_at) if pushed_at else None,
        )

    @staticmethod
    def _parse_fork(data: dict[str, Any]) -> ForkInfo:
        """Map a GitHub API fork JSON object to a ForkInfo model."""
        pushed_at = data.get("pushed_at")
        created_at = data.get("created_at", "2000-01-01T00:00:00Z")
        return ForkInfo(
            github_id=data["id"],
            owner=data["owner"]["login"],
            full_name=data["full_name"],
            default_branch=data["default_branch"],
            description=data.get("description"),
            stars=data.get("stargazers_count", 0),
            last_pushed_at=datetime.fromisoformat(pushed_at) if pushed_at else None,
            has_diverged=False,  # determined later via comparison if needed
            created_at=datetime.fromisoformat(created_at),
        )

    @staticmethod
    def _parse_commit(data: dict[str, Any]) -> CommitInfo:
        """Map a GitHub API commit JSON object to a CommitInfo model."""
        commit_data = data["commit"]
        author_data = commit_data.get("author", {})
        # Prefer the top-level author login, fall back to commit author name
        author = (
            data.get("author", {}).get("login")
            if data.get("author")
            else author_data.get("name", "unknown")
        )
        authored_at = author_data.get("date", "2000-01-01T00:00:00Z")
        return CommitInfo(
            sha=data["sha"],
            message=commit_data["message"],
            author=author,
            authored_at=datetime.fromisoformat(authored_at),
        )

    @staticmethod
    def _parse_file_change(data: dict[str, Any]) -> FileChange:
        """Map a GitHub API file object to a FileChange model."""
        return FileChange(
            filename=data["filename"],
            status=data["status"],
            additions=data.get("additions", 0),
            deletions=data.get("deletions", 0),
            patch=data.get("patch"),
        )

    @staticmethod
    def _parse_release(data: dict[str, Any]) -> Release:
        """Map a GitHub API release JSON object to a Release model."""
        return Release(
            tag=data["tag_name"],
            name=data.get("name", ""),
            body=data.get("body", ""),
            published_at=datetime.fromisoformat(data["published_at"]),
            is_prerelease=data.get("prerelease", False),
        )

    # ------------------------------------------------------------------
    # GitProvider protocol methods
    # ------------------------------------------------------------------

    async def get_user_repos(self, username: str) -> list[RepoInfo]:
        """Fetch all owned repositories for a GitHub user."""
        data = await self._get(
            f"/users/{username}/repos",
            params={"type": "owner", "sort": "updated", "per_page": "100"},
        )
        return [self._parse_repo(repo) for repo in data]

    async def get_forks(self, owner: str, repo: str, *, page: int = 1) -> ForkPage:
        """Fetch a page of forks for a repository."""
        data, headers = await self._get_with_headers(
            f"/repos/{owner}/{repo}/forks",
            params={"sort": "newest", "per_page": "30", "page": str(page)},
        )

        forks = [self._parse_fork(fork_data) for fork_data in data]
        has_next = self._has_next_page(headers)
        total_count = len(forks)

        return ForkPage(
            forks=forks,
            total_count=total_count,
            page=page,
            has_next=has_next,
        )

    async def compare(self, owner: str, repo: str, base: str, head: str) -> CompareResult:
        """Compare two refs (branches, tags, or SHAs) in a repository."""
        data = await self._get(f"/repos/{owner}/{repo}/compare/{base}...{head}")

        files = [self._parse_file_change(f) for f in data.get("files", [])]
        commits = [self._parse_commit(c) for c in data.get("commits", [])]

        return CompareResult(
            ahead_by=data.get("ahead_by", 0),
            behind_by=data.get("behind_by", 0),
            files=files,
            commits=commits,
        )

    async def get_releases(
        self, owner: str, repo: str, *, since: datetime | None = None
    ) -> list[Release]:
        """Fetch releases for a repository, optionally filtered by date."""
        data = await self._get(
            f"/repos/{owner}/{repo}/releases",
            params={"per_page": "30"},
        )

        releases = [self._parse_release(r) for r in data]

        if since is not None:
            # Ensure the since cutoff is timezone-aware for comparison
            if since.tzinfo is None:
                since = since.replace(tzinfo=UTC)
            releases = [r for r in releases if r.published_at >= since]

        return releases

    async def get_repo(self, owner: str, repo: str) -> RepoInfo:
        """Fetch metadata for a single repository."""
        data = await self._get(f"/repos/{owner}/{repo}")
        return self._parse_repo(data)

    async def get_commit_messages(
        self, owner: str, repo: str, *, since: str | None = None
    ) -> list[CommitInfo]:
        """Fetch recent commits for a repository."""
        params: dict[str, str] = {"per_page": "30"}
        if since is not None:
            params["since"] = since

        data = await self._get(f"/repos/{owner}/{repo}/commits", params=params)
        return [self._parse_commit(c) for c in data]

    async def get_file_diff(self, owner: str, repo: str, base: str, head: str, path: str) -> str:
        """Get the patch diff for a specific file between two refs.

        Uses the compare endpoint and filters to the requested file.
        Returns an empty string if the file is not in the diff.
        """
        data = await self._get(f"/repos/{owner}/{repo}/compare/{base}...{head}")

        for file_data in data.get("files", []):
            if file_data["filename"] == path:
                return file_data.get("patch", "")

        return ""

    async def get_rate_limit(self) -> RateLimitInfo:
        """Fetch current GitHub API rate limit status."""
        data = await self._get("/rate_limit")
        core = data["resources"]["core"]
        return RateLimitInfo(
            limit=core["limit"],
            remaining=core["remaining"],
            reset_at=datetime.fromtimestamp(core["reset"], tz=UTC),
        )

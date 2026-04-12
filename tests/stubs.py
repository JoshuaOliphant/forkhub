# ABOUTME: Shared test stubs and factory helpers for all ForkHub test files.
# ABOUTME: Single source of truth for stub providers and DB dict factories.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from forkhub.models import (
    CommitInfo,
    CompareResult,
    DeliveryResult,
    Digest,
    FixSuggestion,
    Fork,
    ForkInfo,
    ForkPage,
    RateLimitInfo,
    Release,
    RepoInfo,
    Signal,
    TrackedRepo,
)

# ---------------------------------------------------------------------------
# Time constants used across tests
# ---------------------------------------------------------------------------

STUB_NOW = datetime(2025, 6, 1, tzinfo=UTC)
STUB_ACTIVE_DATE = STUB_NOW - timedelta(days=30)

# ---------------------------------------------------------------------------
# Factory helpers for database dicts
# ---------------------------------------------------------------------------


def make_id() -> str:
    return str(uuid4())


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def make_tracked_repo(**overrides: object) -> dict:
    defaults: dict = {
        "id": make_id(),
        "github_id": 123456,
        "owner": "torvalds",
        "name": "linux",
        "full_name": "torvalds/linux",
        "tracking_mode": "active",
        "default_branch": "main",
        "description": "Linux kernel source tree",
        "fork_depth": 1,
        "excluded": False,
        "webhook_id": None,
        "sync_status": "ok",
        "last_sync_error": None,
        "last_synced_at": None,
        "created_at": now_iso(),
    }
    defaults.update(overrides)
    return defaults


def make_fork(tracked_repo_id: str, **overrides: object) -> dict:
    defaults: dict = {
        "id": make_id(),
        "tracked_repo_id": tracked_repo_id,
        "github_id": 789012,
        "owner": "gregkh",
        "full_name": "gregkh/linux",
        "default_branch": "main",
        "description": "Greg KH's linux fork",
        "vitality": "active",
        "stars": 42,
        "stars_previous": 40,
        "parent_fork_id": None,
        "depth": 1,
        "last_pushed_at": now_iso(),
        "commits_ahead": 10,
        "commits_behind": 5,
        "head_sha": "abc123def456",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    defaults.update(overrides)
    return defaults


def make_signal(fork_id: str, tracked_repo_id: str, **overrides: object) -> dict:
    defaults: dict = {
        "id": make_id(),
        "fork_id": fork_id,
        "tracked_repo_id": tracked_repo_id,
        "category": "feature",
        "summary": "Added GPU support",
        "detail": "Implements CUDA acceleration for training loop",
        "files_involved": json.dumps(["src/gpu.py", "src/train.py"]),
        "significance": 7,
        "embedding": None,
        "is_upstream": False,
        "release_tag": None,
        "created_at": now_iso(),
    }
    defaults.update(overrides)
    return defaults


def make_cluster(tracked_repo_id: str, **overrides: object) -> dict:
    defaults: dict = {
        "id": make_id(),
        "tracked_repo_id": tracked_repo_id,
        "label": "GPU acceleration",
        "description": "Multiple forks adding GPU support",
        "files_pattern": json.dumps(["src/gpu*.py"]),
        "fork_count": 3,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    defaults.update(overrides)
    return defaults


def make_cluster_member(cluster_id: str, signal_id: str, fork_id: str) -> dict:
    return {
        "cluster_id": cluster_id,
        "signal_id": signal_id,
        "fork_id": fork_id,
    }


def make_digest_config(tracked_repo_id: str | None = None, **overrides: object) -> dict:
    defaults: dict = {
        "id": make_id(),
        "tracked_repo_id": tracked_repo_id,
        "frequency": "weekly",
        "day_of_week": 1,
        "time_of_day": "09:00",
        "min_significance": 5,
        "categories": None,
        "file_patterns": None,
        "backends": json.dumps(["console"]),
        "created_at": now_iso(),
    }
    defaults.update(overrides)
    return defaults


def make_digest(config_id: str, **overrides: object) -> dict:
    defaults: dict = {
        "id": make_id(),
        "config_id": config_id,
        "title": "Weekly Fork Digest",
        "body": "Here are this week's interesting forks...",
        "signal_ids": json.dumps([make_id(), make_id()]),
        "delivered_at": None,
        "created_at": now_iso(),
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Canned test data for the "testuser" scenario
# ---------------------------------------------------------------------------


def _testuser_repos() -> dict[str, list[RepoInfo]]:
    return {
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
                last_pushed_at=STUB_NOW,
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
                last_pushed_at=STUB_NOW,
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
                last_pushed_at=STUB_NOW,
            ),
        ],
    }


def _testuser_repo_lookup() -> dict[str, RepoInfo]:
    user_repos = _testuser_repos()
    return {
        "testuser/alpha": user_repos["testuser"][0],
        "testuser/beta": user_repos["testuser"][1],
        "testuser/forked-lib": user_repos["testuser"][2],
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
            last_pushed_at=STUB_NOW,
        ),
    }


# ---------------------------------------------------------------------------
# StubGitProvider — composable superset of all test variants
# ---------------------------------------------------------------------------


class StubGitProvider:
    """Shared stub GitProvider with configurable data.

    Satisfies the GitProvider protocol. Supports:
    - Canned user repos and repo lookup via constructor dicts
    - Configurable rate limit and rate limit errors (for hook tests)
    - Configurable fork data and head SHAs
    """

    def __init__(
        self,
        *,
        user_repos: dict[str, list[RepoInfo]] | None = None,
        repos: dict[str, RepoInfo] | None = None,
        forks: dict[str, list[ForkInfo]] | None = None,
        head_shas: dict[str, str] | None = None,
        rate_limit_remaining: int = 5000,
    ) -> None:
        self.user_repos: dict[str, list[RepoInfo]] = user_repos or {}
        self.repos: dict[str, RepoInfo] = repos or {}
        self._forks: dict[str, list[ForkInfo]] = forks or {}
        self._head_shas: dict[str, str] = head_shas or {}
        self._file_diffs: dict[str, str] = {}
        self._error_files: set[str] = set()
        self._rate_limit = RateLimitInfo(
            limit=5000,
            remaining=rate_limit_remaining,
            reset_at=STUB_NOW,
        )
        self._raise_on_rate_limit = False

    @classmethod
    def with_testuser_data(cls) -> StubGitProvider:
        """Create a provider pre-loaded with the standard testuser scenario."""
        return cls(
            user_repos=_testuser_repos(),
            repos=_testuser_repo_lookup(),
            forks={
                "testuser/alpha": [
                    ForkInfo(
                        github_id=5001,
                        owner="forker1",
                        full_name="forker1/alpha",
                        default_branch="main",
                        description="Forker 1's copy",
                        stars=15,
                        last_pushed_at=STUB_ACTIVE_DATE,
                        has_diverged=True,
                        created_at=STUB_NOW - timedelta(days=60),
                    ),
                ],
            },
            head_shas={"forker1/alpha": "sha-forker1"},
        )

    def set_rate_limit(self, remaining: int) -> None:
        """Update the remaining rate limit for subsequent calls."""
        self._rate_limit = RateLimitInfo(
            limit=self._rate_limit.limit,
            remaining=remaining,
            reset_at=datetime.now(tz=UTC),
        )

    def set_rate_limit_error(self) -> None:
        """Configure get_rate_limit to raise an exception."""
        self._raise_on_rate_limit = True

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
        return CompareResult(ahead_by=0, behind_by=0, files=[], commits=[])

    async def get_releases(
        self,
        owner: str,
        repo: str,
        *,
        since: datetime | None = None,
    ) -> list[Release]:
        return []

    async def get_commit_messages(
        self,
        owner: str,
        repo: str,
        *,
        since: str | None = None,
    ) -> list[CommitInfo]:
        return []

    def set_file_diff(self, fork_owner: str, filepath: str, diff: str) -> None:
        """Register a canned diff response for a fork/file combination."""
        key = f"{fork_owner}:{filepath}"
        self._file_diffs[key] = diff

    async def get_file_diff(
        self,
        owner: str,
        repo: str,
        base: str,
        head: str,
        path: str,
    ) -> str:
        # Extract fork owner from head param (format: "fork_owner:branch")
        fork_owner = head.split(":")[0]
        key = f"{fork_owner}:{path}"
        if path in self._error_files:
            raise RuntimeError(f"Simulated error fetching {path}")
        return self._file_diffs.get(key, "")

    async def get_rate_limit(self) -> RateLimitInfo:
        if self._raise_on_rate_limit:
            raise ConnectionError("Rate limit check failed")
        return self._rate_limit

    def get_head_sha(self, fork_full_name: str) -> str | None:
        return self._head_shas.get(fork_full_name)


# ---------------------------------------------------------------------------
# StubNotificationBackend — superset with optional failure
# ---------------------------------------------------------------------------


class StubNotificationBackend:
    """Deterministic notification backend for testing."""

    def __init__(self, name: str = "stub", should_fail: bool = False) -> None:
        self._name = name
        self._should_fail = should_fail
        self.delivered: list[Digest] = []

    async def deliver(self, digest: Digest) -> DeliveryResult:
        self.delivered.append(digest)
        if self._should_fail:
            return DeliveryResult(
                backend_name=self._name,
                success=False,
                error="Simulated delivery failure",
                delivered_at=datetime.now(UTC),
            )
        return DeliveryResult(
            backend_name=self._name,
            success=True,
            error=None,
            delivered_at=datetime.now(UTC),
        )

    def backend_name(self) -> str:
        return self._name


# ---------------------------------------------------------------------------
# StubEmbeddingProvider — deterministic char-frequency embeddings
# ---------------------------------------------------------------------------


class StubEmbeddingProvider:
    """Deterministic embedding provider using char-frequency hashing."""

    def __init__(self, dims: int = 8) -> None:
        self._dims = dims
        self.call_count = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.call_count += 1
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


# ── Test Fixer Stub ──────────────────────────────────────────


class StubTestFixer:
    """Real stub conforming to the TestFixer protocol.

    Provides a sequence of canned FixSuggestion responses and records
    call inputs so tests can assert what was passed to the fixer.
    """

    def __init__(self, suggestions: list[FixSuggestion] | None = None) -> None:
        self._suggestions = suggestions or []
        self._call_count = 0
        self.calls: list[dict] = []

    async def suggest_fixes(
        self,
        test_output: str,
        patch_summary: str,
        files_patched: list[str],
        test_file_contents: dict[str, str],
    ) -> FixSuggestion:
        self.calls.append(
            {
                "test_output": test_output,
                "patch_summary": patch_summary,
                "files_patched": files_patched,
                "test_file_contents": test_file_contents,
            }
        )
        if self._call_count < len(self._suggestions):
            result = self._suggestions[self._call_count]
            self._call_count += 1
            return result
        return FixSuggestion(reasoning="No more canned responses", should_reject=True)


# ── Analyzer Stub ────────────────────────────────────────────


class StubAnalyzer:
    """Real stub conforming to the Analyzer protocol.

    Returns canned Signal responses and records call inputs so tests
    can assert what was passed to the analyzer. Set `raise_error` to
    make analyze() raise an exception for failure-path testing.
    """

    def __init__(
        self,
        signals: list[Signal] | None = None,
        *,
        raise_error: Exception | None = None,
    ) -> None:
        self._signals = signals or []
        self._raise_error = raise_error
        self.calls: list[dict] = []

    async def analyze(
        self,
        repo: TrackedRepo,
        changed_forks: list[Fork],
        new_releases: list[Release],
    ) -> list[Signal]:
        self.calls.append(
            {
                "repo_full_name": repo.full_name,
                "changed_fork_names": [f.full_name for f in changed_forks],
                "changed_forks": list(changed_forks),
                "release_count": len(new_releases),
                "releases": list(new_releases),
            }
        )
        if self._raise_error is not None:
            raise self._raise_error
        return list(self._signals)

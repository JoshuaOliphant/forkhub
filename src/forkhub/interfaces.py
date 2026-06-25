# ABOUTME: Protocol definitions for ForkHub's plugin system.
# ABOUTME: GitProvider, NotificationBackend, EmbeddingProvider, TestFixer, Analyzer.
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import subprocess
    from collections.abc import Sequence
    from datetime import datetime

    from forkhub.models import (
        CommitInfo,
        CompareResult,
        DeliveryResult,
        Digest,
        FixSuggestion,
        Fork,
        ForkPage,
        RateLimitInfo,
        Release,
        RepoInfo,
        Signal,
        TrackedRepo,
    )


class ProviderError(Exception):
    """Provider-agnostic error for Git hosting API/network failures.

    Implementations of :class:`GitProvider` should raise this (or a subclass)
    for provider or API failures — e.g. a deleted fork's repo returning 404 —
    so callers can catch failures without importing a concrete provider module.
    """


@runtime_checkable
class GitProvider(Protocol):
    """Interface for fetching repository and fork data from a Git hosting service."""

    async def get_user_repos(self, username: str) -> list[RepoInfo]: ...

    async def get_forks(self, owner: str, repo: str, *, page: int = 1) -> ForkPage: ...

    async def compare(self, owner: str, repo: str, base: str, head: str) -> CompareResult: ...

    async def get_releases(
        self, owner: str, repo: str, *, since: datetime | None = None
    ) -> list[Release]: ...

    async def get_repo(self, owner: str, repo: str) -> RepoInfo: ...

    async def get_commit_messages(
        self, owner: str, repo: str, *, since: str | None = None
    ) -> list[CommitInfo]: ...

    async def get_file_diff(
        self, owner: str, repo: str, base: str, head: str, path: str
    ) -> str: ...

    async def get_head_sha(self, owner: str, repo: str, branch: str) -> str: ...

    async def get_rate_limit(self) -> RateLimitInfo: ...


@runtime_checkable
class NotificationBackend(Protocol):
    """Interface for delivering digest notifications to users."""

    async def deliver(self, digest: Digest) -> DeliveryResult: ...

    def backend_name(self) -> str: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Interface for generating text embeddings used in cluster detection."""

    async def embed(self, texts: list[str]) -> list[list[float]]: ...

    def dimensions(self) -> int: ...


@runtime_checkable
class TestFixer(Protocol):
    """Interface for suggesting test file edits when backfill tests fail.

    Implementations can use any LLM provider (Claude, OpenAI, local models),
    a rule-based approach, or anything else. The BackfillService calls
    suggest_fixes and is responsible for validating and applying the results.
    """

    async def suggest_fixes(
        self,
        test_output: str,
        patch_summary: str,
        files_patched: list[str],
        test_file_contents: dict[str, str],
    ) -> FixSuggestion: ...


@runtime_checkable
class Analyzer(Protocol):
    """Interface for analyzing fork changes and generating signals.

    Implementations can use any LLM provider (Claude, OpenAI, local
    models), a rule-based approach, or anything else. SyncService calls
    `analyze` with the forks that have diverged since the last sync and
    the new upstream releases, and expects a list of `Signal` objects
    back. How those signals get built or persisted is implementation-
    defined — callers should treat the returned list as authoritative.
    """

    async def analyze(
        self,
        repo: TrackedRepo,
        changed_forks: list[Fork],
        new_releases: list[Release],
    ) -> list[Signal]: ...


@runtime_checkable
class GitRepoProtocol(Protocol):
    """Interface for running git/subprocess operations in a working-copy directory."""

    async def run(
        self, args: Sequence[str], *, stdin_data: bytes | None = None, timeout: int = 120
    ) -> subprocess.CompletedProcess: ...

    async def git(self, *args: str) -> str: ...

    async def head_branch(self) -> subprocess.CompletedProcess: ...

    async def verify_branch(self, name: str) -> subprocess.CompletedProcess: ...

    async def branch_exists(self, name: str) -> bool: ...

    async def apply_3way(self, patch: bytes) -> subprocess.CompletedProcess: ...

    async def reset_hard(self) -> subprocess.CompletedProcess: ...

    async def create_branch(self, name: str) -> None: ...

    async def checkout(self, ref: str) -> None: ...

    async def stage(self, paths: Sequence[str]) -> None: ...

    async def commit(self, message: str) -> None: ...

    async def delete_branch(self, name: str) -> None: ...

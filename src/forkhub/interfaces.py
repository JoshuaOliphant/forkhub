# ABOUTME: Protocol definitions for ForkHub's plugin system.
# ABOUTME: Defines GitProvider, NotificationBackend, and EmbeddingProvider interfaces.
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

    from forkhub.models import (
        CommitInfo,
        CompareResult,
        DeliveryResult,
        Digest,
        ForkPage,
        RateLimitInfo,
        Release,
        RepoInfo,
    )


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

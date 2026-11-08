# ABOUTME: Read the dedicated MCP cache through an asynchronous SQL query function.
# ABOUTME: Preserve the SQLite reader's validation, missing-data states, and provenance.

from __future__ import annotations

from typing import TYPE_CHECKING

from forkhub.mcp_cache_contract import (
    RELATIONSHIP_EDGES_SQL,
    RELATIONSHIP_SNAPSHOT_SQL,
    SIGNALS_SQL,
    TRACKED_REPOSITORIES_SQL,
    TRACKED_REPOSITORY_SQL,
    normalize_username,
    relationships_result,
    signals_result,
    tracked_repositories_result,
    validate_limit,
    validate_repository,
    validate_signal_query,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class D1Queries:
    def __init__(self, query: Callable[[str, tuple], Awaitable[list[dict]]], username: str) -> None:
        self._query = query
        self._user = normalize_username(username)

    async def list_tracked_repositories(self, limit: int = 20) -> dict:
        validate_limit(limit)
        rows = await self._query(TRACKED_REPOSITORIES_SQL, (limit + 1,))
        return tracked_repositories_result(rows, limit)

    async def get_cached_relationships(self, repository: str) -> dict:
        validate_repository(repository)
        rows = await self._query(RELATIONSHIP_SNAPSHOT_SQL, (self._user, repository))
        row = rows[0] if rows else None
        edges = (
            await self._query(RELATIONSHIP_EDGES_SQL, (self._user, row["focus_github_id"]))
            if row is not None
            else []
        )
        return relationships_result(repository, row, edges)

    async def list_cached_signals(
        self, repository: str, min_significance: int = 5, limit: int = 20
    ) -> dict:
        validate_signal_query(repository, min_significance, limit)
        tracked = await self._query(TRACKED_REPOSITORY_SQL, (repository,))
        rows = (
            await self._query(SIGNALS_SQL, (tracked[0]["id"], min_significance, limit + 1))
            if tracked
            else None
        )
        return signals_result(repository, rows, limit)

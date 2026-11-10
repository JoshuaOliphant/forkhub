# ABOUTME: Read the dedicated ForkHub MCP cache through read-only SQLite connections.
# ABOUTME: Never creates databases, scans GitHub, or invokes AI providers.

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

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


class PreviewQueries:
    """Personal development-only SQL reader; not multi-tenant authorization."""

    def __init__(self, database_path: str | Path, username: str) -> None:
        path = Path(database_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"ForkHub database does not exist: {path}")
        self._user = normalize_username(username)
        self._uri = path.as_uri() + "?mode=ro"

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def list_tracked_repositories(self, limit: int = 20) -> dict:
        validate_limit(limit)
        with closing(self._connect()) as conn:
            rows = conn.execute(TRACKED_REPOSITORIES_SQL, (limit + 1,)).fetchall()
        return tracked_repositories_result([dict(row) for row in rows], limit)

    def get_cached_relationships(self, repository: str) -> dict:
        validate_repository(repository)
        with closing(self._connect()) as conn:
            row = conn.execute(RELATIONSHIP_SNAPSHOT_SQL, (self._user, repository)).fetchone()
            edges = (
                conn.execute(
                    RELATIONSHIP_EDGES_SQL, (self._user, row["focus_github_id"])
                ).fetchall()
                if row is not None
                else []
            )
        return relationships_result(
            repository, dict(row) if row is not None else None, [dict(edge) for edge in edges]
        )

    def list_cached_signals(
        self, repository: str, min_significance: int = 5, limit: int = 20
    ) -> dict:
        validate_signal_query(repository, min_significance, limit)
        with closing(self._connect()) as conn:
            tracked = conn.execute(TRACKED_REPOSITORY_SQL, (repository,)).fetchone()
            rows = (
                conn.execute(SIGNALS_SQL, (tracked["id"], min_significance, limit + 1)).fetchall()
                if tracked is not None
                else None
            )
        return signals_result(
            repository,
            [dict(row) for row in rows] if rows is not None else None,
            limit,
            dict(tracked) if tracked is not None else None,
        )

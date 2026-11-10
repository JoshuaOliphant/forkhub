# ABOUTME: Export a consistent dedicated ForkHub cache into a minimal D1 SQL import.
# ABOUTME: Preserve only MCP-visible fields and create a private import file without overwriting.

from __future__ import annotations

import math
import os
import sqlite3
from contextlib import closing
from importlib.resources import files
from pathlib import Path

_COLUMNS = {
    "tracked_repos": (
        "id",
        "full_name",
        "tracking_mode",
        "last_synced_at",
        "sync_status",
        "excluded",
    ),
    "signals": (
        "id",
        "tracked_repo_id",
        "summary",
        "detail",
        "category",
        "significance",
        "created_at",
        "files_involved",
        "evidence",
    ),
    "relationship_snapshots": (
        "username",
        "focus_github_id",
        "focus_repo",
        "upstream_repo",
        "complete",
        "pages_scanned",
        "updated_at",
        "last_attempt_at",
        "last_attempt_complete",
        "last_attempt_pages_scanned",
        "last_complete_at",
    ),
    "repository_relationships": (
        "id",
        "username",
        "focus_github_id",
        "direction",
        "source_github_id",
        "source_repo",
        "target_repo",
        "is_user_repository",
    ),
}


def _literal(value: object) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        if "\x00" in value:
            return "CAST(X'" + value.encode("utf-8").hex() + "' AS TEXT)"
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, int):
        if not -(2**53 - 1) <= value <= 2**53 - 1:
            raise ValueError("Cache integer exceeds D1's exact JavaScript integer range")
        return str(value)
    if isinstance(value, float) and math.isfinite(value):
        return repr(value)
    raise ValueError("MCP cache columns must contain finite numbers, text, or NULL")


def export_cache(
    source: str | Path,
    destination: str | Path,
    username: str,
    *,
    confirm_single_user: bool = False,
) -> dict[str, int]:
    if not confirm_single_user:
        raise ValueError("Confirm this is one user's dedicated cache before exporting")
    username = username.strip().casefold()
    if not username:
        raise ValueError("GitHub username is required")
    source_path = Path(source).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError("ForkHub source cache does not exist")
    statements = [files("forkhub").joinpath("mcp_cache_schema.sql").read_text(encoding="utf-8")]
    counts = {}
    with closing(sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("BEGIN")
        for table, columns in _COLUMNS.items():
            selected = [
                "rowid" if table == "repository_relationships" and c == "id" else c for c in columns
            ]
            condition = (
                " WHERE username = ?"
                if table in ("relationship_snapshots", "repository_relationships")
                else ""
            )
            parameters = (username,) if condition else ()
            rows = connection.execute(
                f"SELECT {', '.join(selected)} FROM {table}{condition} ORDER BY rowid", parameters
            ).fetchall()
            counts[table] = len(rows)
            for row in rows:
                values = ", ".join(_literal(value) for value in row)
                statement = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({values});\n"
                if len(statement.encode("utf-8")) > 100_000:
                    raise ValueError(f"D1 SQL statement exceeds 100000 bytes for table {table}")
                statements.append(statement)
    descriptor = os.open(Path(destination), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write("\n".join(statements))
    return counts

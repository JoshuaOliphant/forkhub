# ABOUTME: Local-only, SQLite read-only query contract for the MCP experiment.
# ABOUTME: Never creates databases, scans GitHub, or invokes AI providers.

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path


class PreviewQueries:
    """Personal development-only SQL reader; not multi-tenant authorization."""

    def __init__(self, database_path: str | Path, username: str) -> None:
        path = Path(database_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"ForkHub database does not exist: {path}")
        if not username.strip():
            raise ValueError("FORKHUB_MCP_USER must be configured")
        self._uri = path.as_uri() + "?mode=ro"
        self._user = username.strip().casefold()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def list_tracked_repositories(self, limit: int = 20) -> dict:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT full_name, tracking_mode, last_synced_at, sync_status "
                "FROM tracked_repos WHERE excluded = 0 ORDER BY full_name LIMIT ?",
                (limit + 1,),
            ).fetchall()
        return {
            "repositories": [
                {
                    "name": row["full_name"],
                    "mode": row["tracking_mode"],
                    "last_synced_at": row["last_synced_at"],
                    "sync_status": row["sync_status"],
                }
                for row in rows[:limit]
            ],
            "returned": min(len(rows), limit),
            "truncated": len(rows) > limit,
            "source": "forkhub_cache",
        }

    def get_cached_relationships(self, repository: str) -> dict:
        self._validate_repo(repository)
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT focus_github_id, focus_repo, upstream_repo, complete, pages_scanned, "
                "updated_at, last_attempt_at, last_attempt_complete, "
                "last_attempt_pages_scanned, last_complete_at "
                "FROM relationship_snapshots "
                "WHERE username = ? AND focus_repo = ? COLLATE NOCASE",
                (self._user, repository),
            ).fetchone()
            if row is None:
                return {
                    "repository": repository,
                    "status": "not_scanned",
                    "message": "No cached relationship snapshot. Run local discovery first.",
                }
            edges = conn.execute(
                "SELECT direction, source_github_id, source_repo, target_repo, "
                "is_user_repository FROM repository_relationships "
                "WHERE username = ? AND focus_github_id = ? ORDER BY rowid",
                (self._user, row["focus_github_id"]),
            ).fetchall()
        complete = bool(row["complete"])
        last_attempt_complete = (
            bool(row["last_attempt_complete"])
            if row["last_attempt_complete"] is not None
            else complete
        )
        last_attempt_at = row["last_attempt_at"] or row["updated_at"]
        last_complete_at = row["last_complete_at"] or (
            row["updated_at"] if complete else None
        )
        preserved = complete and not last_attempt_complete
        return {
            "repository": repository,
            "status": "cached",
            "last_attempt_complete": last_attempt_complete,
            "last_attempt_at": last_attempt_at,
            "last_attempt_pages_scanned": (
                row["last_attempt_pages_scanned"]
                if row["last_attempt_pages_scanned"] is not None
                else row["pages_scanned"]
            ),
            "last_complete_at": last_complete_at,
            "preserved_complete_snapshot": preserved,
            "snapshot": {
                "focus_github_id": row["focus_github_id"],
                "focus_repo": row["focus_repo"],
                "upstream_repo": row["upstream_repo"],
                "complete": complete,
                "pages_scanned": row["pages_scanned"],
                "relationships": [
                    {
                        "direction": edge["direction"],
                        "github_id": edge["source_github_id"],
                        "source_repo": edge["source_repo"],
                        "target_repo": edge["target_repo"],
                        "is_user_repository": bool(edge["is_user_repository"]),
                    }
                    for edge in edges
                ],
            },
            "warning": (
                "Latest scan was incomplete. Showing the last complete snapshot; "
                "its relationships may now be stale."
                if preserved
                else (
                    "Incomplete fork coverage; results must not be presented as exhaustive."
                    if not complete
                    else None
                )
            ),
        }

    def list_cached_signals(
        self, repository: str, min_significance: int = 5, limit: int = 20
    ) -> dict:
        self._validate_repo(repository)
        if not 1 <= min_significance <= 10:
            raise ValueError("min_significance must be between 1 and 10")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        with closing(self._connect()) as conn:
            tracked = conn.execute(
                "SELECT id FROM tracked_repos WHERE full_name = ? COLLATE NOCASE AND excluded = 0",
                (repository,),
            ).fetchone()
            if tracked is None:
                return {
                    "repository": repository,
                    "status": "not_tracked",
                    "signals": [],
                    "message": "Repository is not tracked by ForkHub.",
                }
            rows = conn.execute(
                "SELECT id, summary, detail, category, significance, created_at, "
                "files_involved FROM signals "
                "WHERE tracked_repo_id = ? AND significance >= ? "
                "ORDER BY significance DESC, created_at DESC, id LIMIT ?",
                (tracked["id"], min_significance, limit + 1),
            ).fetchall()
        return {
            "repository": repository,
            "status": "cached",
            "signals": [
                {
                    "id": row["id"],
                    "summary": row["summary"],
                    "detail": row["detail"],
                    "category": row["category"],
                    "significance": row["significance"],
                    "created_at": row["created_at"],
                    "files_involved": json.loads(row["files_involved"]),
                    "interpretation_is_model_generated": True,
                    "verified_against_immutable_sha_evidence": False,
                }
                for row in rows[:limit]
            ],
            "truncated": len(rows) > limit,
            "source": "forkhub_cache",
            "warning": (
                "Existing model interpretations, not independently verified. "
                "SHA-level provenance is not yet available in this preview."
            ),
        }

    @staticmethod
    def _validate_repo(repository: str) -> None:
        if repository.count("/") != 1 or not all(repository.split("/")):
            raise ValueError("Repository must be owner/name")

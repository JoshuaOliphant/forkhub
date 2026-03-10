# ABOUTME: SQLite + sqlite-vec database layer for ForkHub.
# ABOUTME: Handles schema creation, CRUD operations, and vector similarity queries.

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aiosqlite

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tracked_repos (
    id TEXT PRIMARY KEY,
    github_id INTEGER UNIQUE NOT NULL,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    full_name TEXT NOT NULL,
    tracking_mode TEXT NOT NULL,
    default_branch TEXT NOT NULL DEFAULT 'main',
    description TEXT,
    fork_depth INTEGER NOT NULL DEFAULT 1,
    excluded BOOLEAN NOT NULL DEFAULT 0,
    webhook_id INTEGER,
    last_synced_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(owner, name)
);

CREATE TABLE IF NOT EXISTS forks (
    id TEXT PRIMARY KEY,
    tracked_repo_id TEXT NOT NULL REFERENCES tracked_repos(id) ON DELETE CASCADE,
    github_id INTEGER UNIQUE NOT NULL,
    owner TEXT NOT NULL,
    full_name TEXT NOT NULL,
    default_branch TEXT NOT NULL DEFAULT 'main',
    description TEXT,
    vitality TEXT NOT NULL DEFAULT 'unknown',
    stars INTEGER NOT NULL DEFAULT 0,
    stars_previous INTEGER NOT NULL DEFAULT 0,
    parent_fork_id TEXT REFERENCES forks(id),
    depth INTEGER NOT NULL DEFAULT 1,
    last_pushed_at TEXT,
    commits_ahead INTEGER DEFAULT 0,
    commits_behind INTEGER DEFAULT 0,
    head_sha TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_forks_repo ON forks(tracked_repo_id);
CREATE INDEX IF NOT EXISTS idx_forks_vitality ON forks(vitality);
CREATE INDEX IF NOT EXISTS idx_forks_stars ON forks(stars);

CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    fork_id TEXT REFERENCES forks(id) ON DELETE CASCADE,
    tracked_repo_id TEXT NOT NULL REFERENCES tracked_repos(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail TEXT,
    files_involved TEXT NOT NULL DEFAULT '[]',
    significance INTEGER NOT NULL DEFAULT 5,
    embedding BLOB,
    is_upstream BOOLEAN NOT NULL DEFAULT 0,
    release_tag TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_signals_repo ON signals(tracked_repo_id);
CREATE INDEX IF NOT EXISTS idx_signals_category ON signals(category);
CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_at);

CREATE TABLE IF NOT EXISTS clusters (
    id TEXT PRIMARY KEY,
    tracked_repo_id TEXT NOT NULL REFERENCES tracked_repos(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    description TEXT NOT NULL,
    files_pattern TEXT NOT NULL DEFAULT '[]',
    fork_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cluster_members (
    cluster_id TEXT NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    signal_id TEXT NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    fork_id TEXT NOT NULL REFERENCES forks(id) ON DELETE CASCADE,
    PRIMARY KEY (cluster_id, signal_id)
);

CREATE TABLE IF NOT EXISTS digest_configs (
    id TEXT PRIMARY KEY,
    tracked_repo_id TEXT REFERENCES tracked_repos(id) ON DELETE CASCADE,
    frequency TEXT NOT NULL DEFAULT 'weekly',
    day_of_week INTEGER,
    time_of_day TEXT DEFAULT '09:00',
    min_significance INTEGER NOT NULL DEFAULT 5,
    categories TEXT,
    file_patterns TEXT,
    backends TEXT NOT NULL DEFAULT '["console"]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS digests (
    id TEXT PRIMARY KEY,
    config_id TEXT REFERENCES digest_configs(id),
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    signal_ids TEXT NOT NULL DEFAULT '[]',
    delivered_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS annotations (
    id TEXT PRIMARY KEY,
    fork_id TEXT UNIQUE NOT NULL REFERENCES forks(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS backfill_attempts (
    id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    fork_id TEXT NOT NULL REFERENCES forks(id) ON DELETE CASCADE,
    tracked_repo_id TEXT NOT NULL REFERENCES tracked_repos(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    branch_name TEXT,
    patch_summary TEXT,
    test_output TEXT,
    error TEXT,
    files_patched TEXT NOT NULL DEFAULT '[]',
    score REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_backfill_signal ON backfill_attempts(signal_id);
CREATE INDEX IF NOT EXISTS idx_backfill_status ON backfill_attempts(status);
CREATE INDEX IF NOT EXISTS idx_backfill_repo ON backfill_attempts(tracked_repo_id);
"""


def _row_to_dict(cursor: aiosqlite.Cursor, row: aiosqlite.Row) -> dict[str, Any]:
    """Convert a sqlite Row into a plain dict using column names."""
    cols = [desc[0] for desc in cursor.description]
    return dict(zip(cols, row, strict=True))


class Database:
    """Async SQLite database for ForkHub storage.

    Uses aiosqlite for async access and optionally loads sqlite-vec
    for vector similarity operations.  All CRUD methods accept and
    return plain dicts.
    """

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None
        self.vec_enabled: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open connection, enable WAL + foreign keys, create schema."""
        if self._conn is not None:
            return
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = _row_to_dict  # type: ignore[assignment]
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._create_schema()
        await self._load_sqlite_vec()

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def __aenter__(self) -> Database:
        await self.connect()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _db(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._conn

    async def _create_schema(self) -> None:
        await self._db.executescript(_SCHEMA_SQL)

    async def _load_sqlite_vec(self) -> None:
        """Try to load the sqlite-vec extension for vector similarity."""
        try:
            import sqlite_vec  # noqa: F401

            await self._db.enable_load_extension(True)
            await self._db.load_extension(sqlite_vec.loadable_path())
            await self._db.enable_load_extension(False)
            self.vec_enabled = True
        except Exception:
            self.vec_enabled = False

    async def _table_names(self) -> list[str]:
        """Return all table names in the database (for testing)."""
        cursor = await self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        rows = await cursor.fetchall()
        return [row["name"] for row in rows]

    async def _get_pragma(self, name: str) -> Any:
        """Query a PRAGMA value (for testing)."""
        cursor = await self._db.execute(f"PRAGMA {name}")
        row = await cursor.fetchone()
        if row is None:
            return None
        # PRAGMA results come back as dicts with the pragma name as key
        return next(iter(row.values()))

    # ------------------------------------------------------------------
    # TrackedRepo CRUD
    # ------------------------------------------------------------------

    async def insert_tracked_repo(self, repo: dict[str, Any]) -> None:
        await self._db.execute(
            """
            INSERT INTO tracked_repos
                (id, github_id, owner, name, full_name, tracking_mode,
                 default_branch, description, fork_depth, excluded,
                 webhook_id, last_synced_at, created_at)
            VALUES
                (:id, :github_id, :owner, :name, :full_name, :tracking_mode,
                 :default_branch, :description, :fork_depth, :excluded,
                 :webhook_id, :last_synced_at, :created_at)
            """,
            repo,
        )
        await self._db.commit()

    async def get_tracked_repo(self, repo_id: str) -> dict[str, Any] | None:
        cursor = await self._db.execute("SELECT * FROM tracked_repos WHERE id = ?", (repo_id,))
        return await cursor.fetchone()

    async def get_tracked_repo_by_name(self, full_name: str) -> dict[str, Any] | None:
        cursor = await self._db.execute(
            "SELECT * FROM tracked_repos WHERE full_name = ?", (full_name,)
        )
        return await cursor.fetchone()

    async def list_tracked_repos(
        self,
        mode: str | None = None,
        include_excluded: bool = False,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if not include_excluded:
            clauses.append("excluded = 0")

        if mode is not None:
            clauses.append("tracking_mode = ?")
            params.append(mode)

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        cursor = await self._db.execute(
            f"SELECT * FROM tracked_repos {where} ORDER BY created_at", params
        )
        return await cursor.fetchall()

    async def update_tracked_repo(self, repo: dict[str, Any]) -> None:
        await self._db.execute(
            """
            UPDATE tracked_repos SET
                github_id = :github_id, owner = :owner, name = :name,
                full_name = :full_name, tracking_mode = :tracking_mode,
                default_branch = :default_branch, description = :description,
                fork_depth = :fork_depth, excluded = :excluded,
                webhook_id = :webhook_id, last_synced_at = :last_synced_at
            WHERE id = :id
            """,
            repo,
        )
        await self._db.commit()

    async def delete_tracked_repo(self, repo_id: str) -> None:
        await self._db.execute("DELETE FROM tracked_repos WHERE id = ?", (repo_id,))
        await self._db.commit()

    # ------------------------------------------------------------------
    # Fork CRUD
    # ------------------------------------------------------------------

    async def insert_fork(self, fork: dict[str, Any]) -> None:
        await self._db.execute(
            """
            INSERT INTO forks
                (id, tracked_repo_id, github_id, owner, full_name,
                 default_branch, description, vitality, stars, stars_previous,
                 parent_fork_id, depth, last_pushed_at, commits_ahead,
                 commits_behind, head_sha, created_at, updated_at)
            VALUES
                (:id, :tracked_repo_id, :github_id, :owner, :full_name,
                 :default_branch, :description, :vitality, :stars, :stars_previous,
                 :parent_fork_id, :depth, :last_pushed_at, :commits_ahead,
                 :commits_behind, :head_sha, :created_at, :updated_at)
            """,
            fork,
        )
        await self._db.commit()

    async def get_fork(self, fork_id: str) -> dict[str, Any] | None:
        cursor = await self._db.execute("SELECT * FROM forks WHERE id = ?", (fork_id,))
        return await cursor.fetchone()

    async def get_fork_by_name(self, full_name: str) -> dict[str, Any] | None:
        cursor = await self._db.execute("SELECT * FROM forks WHERE full_name = ?", (full_name,))
        return await cursor.fetchone()

    async def list_forks(self, repo_id: str, vitality: str | None = None) -> list[dict[str, Any]]:
        clauses = ["tracked_repo_id = ?"]
        params: list[Any] = [repo_id]

        if vitality is not None:
            clauses.append("vitality = ?")
            params.append(vitality)

        where = "WHERE " + " AND ".join(clauses)
        cursor = await self._db.execute(f"SELECT * FROM forks {where} ORDER BY stars DESC", params)
        return await cursor.fetchall()

    async def update_fork(self, fork: dict[str, Any]) -> None:
        await self._db.execute(
            """
            UPDATE forks SET
                tracked_repo_id = :tracked_repo_id, github_id = :github_id,
                owner = :owner, full_name = :full_name,
                default_branch = :default_branch, description = :description,
                vitality = :vitality, stars = :stars, stars_previous = :stars_previous,
                parent_fork_id = :parent_fork_id, depth = :depth,
                last_pushed_at = :last_pushed_at, commits_ahead = :commits_ahead,
                commits_behind = :commits_behind, head_sha = :head_sha,
                updated_at = :updated_at
            WHERE id = :id
            """,
            fork,
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Signal CRUD
    # ------------------------------------------------------------------

    async def insert_signal(self, signal: dict[str, Any]) -> None:
        await self._db.execute(
            """
            INSERT INTO signals
                (id, fork_id, tracked_repo_id, category, summary, detail,
                 files_involved, significance, embedding, is_upstream,
                 release_tag, created_at)
            VALUES
                (:id, :fork_id, :tracked_repo_id, :category, :summary, :detail,
                 :files_involved, :significance, :embedding, :is_upstream,
                 :release_tag, :created_at)
            """,
            signal,
        )
        await self._db.commit()

    async def list_signals(
        self,
        repo_id: str,
        since: datetime | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["tracked_repo_id = ?"]
        params: list[Any] = [repo_id]

        if since is not None:
            clauses.append("created_at > ?")
            params.append(since.isoformat())

        if category is not None:
            clauses.append("category = ?")
            params.append(category)

        where = "WHERE " + " AND ".join(clauses)
        cursor = await self._db.execute(
            f"SELECT * FROM signals {where} ORDER BY created_at DESC", params
        )
        return await cursor.fetchall()

    # ------------------------------------------------------------------
    # Cluster CRUD
    # ------------------------------------------------------------------

    async def insert_cluster(self, cluster: dict[str, Any]) -> None:
        await self._db.execute(
            """
            INSERT INTO clusters
                (id, tracked_repo_id, label, description, files_pattern,
                 fork_count, created_at, updated_at)
            VALUES
                (:id, :tracked_repo_id, :label, :description, :files_pattern,
                 :fork_count, :created_at, :updated_at)
            """,
            cluster,
        )
        await self._db.commit()

    async def add_cluster_member(self, member: dict[str, Any]) -> None:
        await self._db.execute(
            """
            INSERT INTO cluster_members (cluster_id, signal_id, fork_id)
            VALUES (:cluster_id, :signal_id, :fork_id)
            """,
            member,
        )
        await self._db.commit()

    async def list_clusters(self, repo_id: str) -> list[dict[str, Any]]:
        cursor = await self._db.execute(
            "SELECT * FROM clusters WHERE tracked_repo_id = ? ORDER BY created_at DESC",
            (repo_id,),
        )
        return await cursor.fetchall()

    # ------------------------------------------------------------------
    # DigestConfig & Digest CRUD
    # ------------------------------------------------------------------

    async def insert_digest_config(self, config: dict[str, Any]) -> None:
        await self._db.execute(
            """
            INSERT INTO digest_configs
                (id, tracked_repo_id, frequency, day_of_week, time_of_day,
                 min_significance, categories, file_patterns, backends, created_at)
            VALUES
                (:id, :tracked_repo_id, :frequency, :day_of_week, :time_of_day,
                 :min_significance, :categories, :file_patterns, :backends, :created_at)
            """,
            config,
        )
        await self._db.commit()

    async def get_digest_config(self, config_id: str) -> dict[str, Any] | None:
        cursor = await self._db.execute("SELECT * FROM digest_configs WHERE id = ?", (config_id,))
        return await cursor.fetchone()

    async def insert_digest(self, digest: dict[str, Any]) -> None:
        await self._db.execute(
            """
            INSERT INTO digests
                (id, config_id, title, body, signal_ids, delivered_at, created_at)
            VALUES
                (:id, :config_id, :title, :body, :signal_ids, :delivered_at, :created_at)
            """,
            digest,
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Annotations CRUD
    # ------------------------------------------------------------------

    async def insert_annotation(self, annotation: dict[str, Any]) -> None:
        await self._db.execute(
            """
            INSERT INTO annotations
                (id, fork_id, title, body, created_at, updated_at)
            VALUES
                (:id, :fork_id, :title, :body, :created_at, :updated_at)
            """,
            annotation,
        )
        await self._db.commit()

    async def get_annotation_by_fork(self, fork_id: str) -> dict[str, Any] | None:
        cursor = await self._db.execute("SELECT * FROM annotations WHERE fork_id = ?", (fork_id,))
        return await cursor.fetchone()

    # ------------------------------------------------------------------
    # BackfillAttempt CRUD
    # ------------------------------------------------------------------

    async def insert_backfill_attempt(self, attempt: dict[str, Any]) -> None:
        await self._db.execute(
            """
            INSERT INTO backfill_attempts
                (id, signal_id, fork_id, tracked_repo_id, status,
                 branch_name, patch_summary, test_output, error,
                 files_patched, score, created_at)
            VALUES
                (:id, :signal_id, :fork_id, :tracked_repo_id, :status,
                 :branch_name, :patch_summary, :test_output, :error,
                 :files_patched, :score, :created_at)
            """,
            attempt,
        )
        await self._db.commit()

    async def update_backfill_attempt(self, attempt: dict[str, Any]) -> None:
        await self._db.execute(
            """
            UPDATE backfill_attempts SET
                status = :status, branch_name = :branch_name,
                patch_summary = :patch_summary, test_output = :test_output,
                error = :error, files_patched = :files_patched, score = :score
            WHERE id = :id
            """,
            attempt,
        )
        await self._db.commit()

    async def get_backfill_attempt(self, attempt_id: str) -> dict[str, Any] | None:
        cursor = await self._db.execute(
            "SELECT * FROM backfill_attempts WHERE id = ?", (attempt_id,)
        )
        return await cursor.fetchone()

    async def list_backfill_attempts(
        self,
        repo_id: str | None = None,
        status: str | None = None,
        signal_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if repo_id is not None:
            clauses.append("tracked_repo_id = ?")
            params.append(repo_id)

        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        if signal_id is not None:
            clauses.append("signal_id = ?")
            params.append(signal_id)

        where = ""
        if clauses:
            where = "WHERE " + " AND ".join(clauses)

        cursor = await self._db.execute(
            f"SELECT * FROM backfill_attempts {where} ORDER BY created_at DESC",
            params,
        )
        return await cursor.fetchall()

    async def has_backfill_for_signal(self, signal_id: str) -> bool:
        """Check if any backfill attempt exists for a given signal."""
        cursor = await self._db.execute(
            "SELECT 1 FROM backfill_attempts WHERE signal_id = ? LIMIT 1",
            (signal_id,),
        )
        return await cursor.fetchone() is not None

    # ------------------------------------------------------------------
    # Sync State
    # ------------------------------------------------------------------

    async def get_sync_state(self, key: str) -> str | None:
        cursor = await self._db.execute("SELECT value FROM sync_state WHERE key = ?", (key,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return row["value"]

    async def set_sync_state(self, key: str, value: str) -> None:
        await self._db.execute(
            """
            INSERT INTO sync_state (key, value, updated)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated = datetime('now')
            """,
            (key, value),
        )
        await self._db.commit()

    # ------------------------------------------------------------------
    # Vector search (sqlite-vec)
    # ------------------------------------------------------------------

    async def search_similar_signals(
        self,
        embedding: list[float],
        repo_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Find signals with similar embeddings via sqlite-vec.

        Returns an empty list when sqlite-vec is not available.
        """
        if not self.vec_enabled:
            return []

        # sqlite-vec integration will be implemented when the extension
        # is set up with a virtual table. For now, return empty.
        return []

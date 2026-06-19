# ABOUTME: Tests for the SQLite database layer.
# ABOUTME: Covers schema creation, CRUD for all tables, and sync state management.

from __future__ import annotations

import aiosqlite
import pytest

from forkhub.database import Database
from tests.stubs import (
    make_cluster,
    make_cluster_member,
    make_fork,
    make_signal,
    make_tracked_repo,
)

# ---------------------------------------------------------------------------
# Schema / connect / close
# ---------------------------------------------------------------------------


class TestConnection:
    async def test_double_connect_is_safe(self):
        """Calling connect() twice should not raise."""
        db = Database(":memory:")
        await db.connect()
        await db.connect()  # should be a no-op
        await db.close()


# Legacy forks table DDL — the schema before baseline_attempts was added.
# Used to verify the additive migration backfills the column on existing DBs.
_LEGACY_FORKS_DDL = """
CREATE TABLE forks (
    id TEXT PRIMARY KEY,
    tracked_repo_id TEXT NOT NULL,
    github_id INTEGER UNIQUE NOT NULL,
    owner TEXT NOT NULL,
    full_name TEXT NOT NULL,
    default_branch TEXT NOT NULL DEFAULT 'main',
    description TEXT,
    vitality TEXT NOT NULL DEFAULT 'unknown',
    stars INTEGER NOT NULL DEFAULT 0,
    stars_previous INTEGER NOT NULL DEFAULT 0,
    parent_fork_id TEXT,
    depth INTEGER NOT NULL DEFAULT 1,
    last_pushed_at TEXT,
    commits_ahead INTEGER DEFAULT 0,
    commits_behind INTEGER DEFAULT 0,
    head_sha TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class TestMigration:
    async def test_adds_baseline_attempts_to_legacy_db(self, tmp_path):
        """A pre-existing database whose forks table predates baseline_attempts
        gains the column (defaulting to 0) when reopened — without dropping the
        legacy row's data."""
        db_path = tmp_path / "legacy.db"
        async with aiosqlite.connect(str(db_path)) as conn:
            await conn.execute(_LEGACY_FORKS_DDL)
            await conn.execute(
                "INSERT INTO forks (id, tracked_repo_id, github_id, owner, full_name) "
                "VALUES ('f1', 'r1', 1, 'dave', 'dave/fork')"
            )
            await conn.commit()

        db = Database(str(db_path))
        await db.connect()
        try:
            cursor = await db._db.execute("PRAGMA table_info(forks)")
            cols = {row["name"] for row in await cursor.fetchall()}
            assert "baseline_attempts" in cols
            row = await db.get_fork("f1")
            assert row is not None
            assert row["baseline_attempts"] == 0
        finally:
            await db.close()

    async def test_migration_is_idempotent(self, tmp_path):
        """Reopening a database that already has baseline_attempts is a no-op —
        the migration must not error when the column already exists."""
        db_path = tmp_path / "current.db"
        db = Database(str(db_path))
        await db.connect()
        await db.close()
        # Second connect: schema already current, migration should skip cleanly.
        db2 = Database(str(db_path))
        await db2.connect()
        try:
            cursor = await db2._db.execute("PRAGMA table_info(forks)")
            cols = {row["name"] for row in await cursor.fetchall()}
            assert "baseline_attempts" in cols
        finally:
            await db2.close()

    async def test_concurrent_add_column_race_does_not_raise(self, tmp_path, monkeypatch):
        """If a concurrent process adds the column between our check and our ALTER,
        the losing process sees a duplicate-column OperationalError. The migration
        must swallow that specific case rather than crashing on startup."""
        # Legacy DB missing the column.
        db_path = tmp_path / "race.db"
        async with aiosqlite.connect(str(db_path)) as conn:
            await conn.execute(_LEGACY_FORKS_DDL)
            await conn.commit()

        db = Database(str(db_path))
        # connect() runs _migrate(), which has already added baseline_attempts —
        # this stands in for the process that won the race.
        await db.connect()
        try:
            real_execute = db._db.execute

            async def fake_execute(sql, *args, **kwargs):
                if sql.startswith("PRAGMA table_info"):
                    # Pretend the column is not there yet (the race window).
                    return await real_execute("PRAGMA table_info(nonexistent_table)")
                return await real_execute(sql, *args, **kwargs)

            monkeypatch.setattr(db._db, "execute", fake_execute)

            # The losing process re-attempts the ALTER and must not raise.
            await db._add_column_if_missing(
                "forks", "baseline_attempts", "INTEGER NOT NULL DEFAULT 0"
            )
        finally:
            await db.close()

    async def test_add_column_reraises_unrelated_operational_error(self, tmp_path):
        """Only the duplicate-column race is swallowed; other OperationalErrors
        (e.g. an ALTER against a missing table) still propagate."""
        db_path = tmp_path / "broken.db"
        db = Database(str(db_path))
        await db.connect()
        try:
            with pytest.raises(aiosqlite.OperationalError):
                await db._add_column_if_missing(
                    "no_such_table", "col", "INTEGER NOT NULL DEFAULT 0"
                )
        finally:
            await db.close()


class TestForkCRUD:
    async def test_baseline_attempts_round_trips(self, db: Database, repo_in_db: dict):
        """baseline_attempts persists through insert and update_fork."""
        fork = make_fork(repo_in_db["id"], baseline_attempts=2)
        await db.insert_fork(fork)
        row = await db.get_fork(fork["id"])
        assert row is not None
        assert row["baseline_attempts"] == 2

        row["baseline_attempts"] = 4
        await db.update_fork(row)
        updated = await db.get_fork(fork["id"])
        assert updated is not None
        assert updated["baseline_attempts"] == 4


# ---------------------------------------------------------------------------
# Tracked repo batch lookup
# ---------------------------------------------------------------------------


class TestGetTrackedReposBatch:
    async def test_returns_dict_keyed_by_id(self, db: Database):
        """get_tracked_repos fetches multiple repos in one query, keyed by id."""
        repo_a = make_tracked_repo(owner="alice", name="proj", full_name="alice/proj", github_id=1)
        repo_b = make_tracked_repo(owner="bob", name="proj", full_name="bob/proj", github_id=2)
        await db.insert_tracked_repo(repo_a)
        await db.insert_tracked_repo(repo_b)

        result = await db.get_tracked_repos([repo_a["id"], repo_b["id"]])

        assert set(result.keys()) == {repo_a["id"], repo_b["id"]}
        assert result[repo_a["id"]]["full_name"] == "alice/proj"
        assert result[repo_b["id"]]["full_name"] == "bob/proj"

    async def test_empty_ids_returns_empty_dict(self, db: Database):
        """An empty id list short-circuits to an empty dict without querying."""
        assert await db.get_tracked_repos([]) == {}

    async def test_missing_ids_omitted(self, db: Database, repo_in_db: dict):
        """Unknown ids are simply absent from the result mapping."""
        result = await db.get_tracked_repos([repo_in_db["id"], "does-not-exist"])
        assert set(result.keys()) == {repo_in_db["id"]}


# ---------------------------------------------------------------------------
# Signal CRUD
# ---------------------------------------------------------------------------


class TestSignalCRUD:
    async def test_list_filtered_by_category(
        self, db: Database, repo_in_db: dict, fork_in_db: dict
    ):
        sig_feature = make_signal(fork_in_db["id"], repo_in_db["id"], category="feature")
        sig_fix = make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            category="fix",
            summary="Fixed memory leak",
        )
        await db.insert_signal(sig_feature)
        await db.insert_signal(sig_fix)
        results = await db.list_signals(repo_in_db["id"], category="fix")
        assert len(results) == 1
        assert results[0]["category"] == "fix"


# ---------------------------------------------------------------------------
# Cluster membership read path
# ---------------------------------------------------------------------------


class TestSignalClusterMap:
    async def test_maps_signals_to_their_clusters(
        self, db: Database, repo_in_db: dict, fork_in_db: dict
    ):
        """Signals in clusters map to their cluster_id; uncovered signals are absent."""
        repo_id = repo_in_db["id"]
        fork_id = fork_in_db["id"]

        clustered_sig = make_signal(fork_id, repo_id, summary="Clustered change")
        lone_sig = make_signal(fork_id, repo_id, summary="Uncovered change")
        await db.insert_signal(clustered_sig)
        await db.insert_signal(lone_sig)

        cluster = make_cluster(repo_id)
        await db.insert_cluster(cluster)
        await db.add_cluster_member(
            make_cluster_member(cluster["id"], clustered_sig["id"], fork_id)
        )

        mapping = await db.get_signal_cluster_map(repo_id)
        assert mapping == {clustered_sig["id"]: cluster["id"]}
        assert lone_sig["id"] not in mapping

    async def test_multiple_clusters_in_one_repo(
        self, db: Database, repo_in_db: dict, fork_in_db: dict
    ):
        """Distinct clusters in the same repo each map their members."""
        repo_id = repo_in_db["id"]
        fork_id = fork_in_db["id"]

        sig_a = make_signal(fork_id, repo_id, summary="Change A")
        sig_b = make_signal(fork_id, repo_id, summary="Change B")
        await db.insert_signal(sig_a)
        await db.insert_signal(sig_b)

        cluster_a = make_cluster(repo_id, label="Cluster A")
        cluster_b = make_cluster(repo_id, label="Cluster B")
        await db.insert_cluster(cluster_a)
        await db.insert_cluster(cluster_b)
        await db.add_cluster_member(make_cluster_member(cluster_a["id"], sig_a["id"], fork_id))
        await db.add_cluster_member(make_cluster_member(cluster_b["id"], sig_b["id"], fork_id))

        mapping = await db.get_signal_cluster_map(repo_id)
        assert mapping == {sig_a["id"]: cluster_a["id"], sig_b["id"]: cluster_b["id"]}

    async def test_empty_when_no_clusters(self, db: Database, repo_in_db: dict):
        """A repo with no cluster members yields an empty map."""
        mapping = await db.get_signal_cluster_map(repo_in_db["id"])
        assert mapping == {}


# ---------------------------------------------------------------------------
# Vector search (graceful degradation)
# ---------------------------------------------------------------------------


class TestVectorSearch:
    async def test_vec_enabled_flag_set(self, db: Database):
        """vec_enabled should be a boolean flag on the database."""
        assert isinstance(db.vec_enabled, bool)

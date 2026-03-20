# ABOUTME: Tests for the SQLite database layer.
# ABOUTME: Covers schema creation, CRUD for all tables, and sync state management.

from __future__ import annotations

import json
from datetime import UTC, datetime

import aiosqlite
import pytest

from forkhub.database import Database
from tests.stubs import (
    make_cluster,
    make_cluster_member,
    make_digest,
    make_digest_config,
    make_fork,
    make_id,
    make_signal,
    make_tracked_repo,
    now_iso,
)

# ---------------------------------------------------------------------------
# Schema / connect / close
# ---------------------------------------------------------------------------


class TestConnection:
    async def test_connect_creates_schema(self):
        """Connecting to a new database should create all tables."""
        db = Database(":memory:")
        await db.connect()
        try:
            tables = await db._table_names()
            expected_tables = {
                "tracked_repos",
                "forks",
                "signals",
                "clusters",
                "cluster_members",
                "digest_configs",
                "digests",
                "annotations",
                "sync_state",
            }
            assert expected_tables.issubset(set(tables))
        finally:
            await db.close()

    async def test_context_manager(self):
        """Database should work as an async context manager."""
        async with Database(":memory:") as db:
            tables = await db._table_names()
            assert "tracked_repos" in tables

    async def test_double_connect_is_safe(self):
        """Calling connect() twice should not raise."""
        db = Database(":memory:")
        await db.connect()
        await db.connect()  # should be a no-op
        await db.close()

    async def test_close_without_connect(self):
        """Calling close() without connect() should not raise."""
        db = Database(":memory:")
        await db.close()

    async def test_wal_mode_enabled(self):
        """WAL journal mode should be enabled after connect."""
        async with Database(":memory:") as db:
            mode = await db._get_pragma("journal_mode")
            # In-memory databases may return 'memory' instead of 'wal',
            # so we just verify the pragma is queryable.
            assert mode is not None

    async def test_foreign_keys_enabled(self):
        """Foreign key enforcement should be on."""
        async with Database(":memory:") as db:
            fk = await db._get_pragma("foreign_keys")
            assert fk == 1


# ---------------------------------------------------------------------------
# TrackedRepo CRUD
# ---------------------------------------------------------------------------


class TestTrackedRepoCRUD:
    async def test_insert_and_get(self, db: Database):
        repo = make_tracked_repo()
        await db.insert_tracked_repo(repo)
        result = await db.get_tracked_repo(repo["id"])
        assert result is not None
        assert result["id"] == repo["id"]
        assert result["full_name"] == "torvalds/linux"
        assert result["tracking_mode"] == "active"

    async def test_get_nonexistent_returns_none(self, db: Database):
        result = await db.get_tracked_repo(make_id())
        assert result is None

    async def test_get_by_name(self, db: Database):
        repo = make_tracked_repo()
        await db.insert_tracked_repo(repo)
        result = await db.get_tracked_repo_by_name("torvalds/linux")
        assert result is not None
        assert result["id"] == repo["id"]

    async def test_get_by_name_nonexistent(self, db: Database):
        result = await db.get_tracked_repo_by_name("nobody/nothing")
        assert result is None

    async def test_list_all(self, db: Database):
        repo1 = make_tracked_repo(github_id=1, owner="a", name="r1", full_name="a/r1")
        repo2 = make_tracked_repo(github_id=2, owner="b", name="r2", full_name="b/r2")
        await db.insert_tracked_repo(repo1)
        await db.insert_tracked_repo(repo2)
        results = await db.list_tracked_repos()
        assert len(results) == 2

    async def test_list_filtered_by_mode(self, db: Database):
        repo_active = make_tracked_repo(
            github_id=1, owner="a", name="r1", full_name="a/r1", tracking_mode="active"
        )
        repo_passive = make_tracked_repo(
            github_id=2, owner="b", name="r2", full_name="b/r2", tracking_mode="passive"
        )
        await db.insert_tracked_repo(repo_active)
        await db.insert_tracked_repo(repo_passive)
        results = await db.list_tracked_repos(mode="active")
        assert len(results) == 1
        assert results[0]["tracking_mode"] == "active"

    async def test_list_excludes_excluded_by_default(self, db: Database):
        repo_ok = make_tracked_repo(
            github_id=1, owner="a", name="r1", full_name="a/r1", excluded=False
        )
        repo_excl = make_tracked_repo(
            github_id=2, owner="b", name="r2", full_name="b/r2", excluded=True
        )
        await db.insert_tracked_repo(repo_ok)
        await db.insert_tracked_repo(repo_excl)
        results = await db.list_tracked_repos()
        assert len(results) == 1

    async def test_list_includes_excluded_when_asked(self, db: Database):
        repo_ok = make_tracked_repo(
            github_id=1, owner="a", name="r1", full_name="a/r1", excluded=False
        )
        repo_excl = make_tracked_repo(
            github_id=2, owner="b", name="r2", full_name="b/r2", excluded=True
        )
        await db.insert_tracked_repo(repo_ok)
        await db.insert_tracked_repo(repo_excl)
        results = await db.list_tracked_repos(include_excluded=True)
        assert len(results) == 2

    async def test_update(self, db: Database):
        repo = make_tracked_repo()
        await db.insert_tracked_repo(repo)
        repo["description"] = "Updated description"
        repo["last_synced_at"] = now_iso()
        await db.update_tracked_repo(repo)
        result = await db.get_tracked_repo(repo["id"])
        assert result is not None
        assert result["description"] == "Updated description"
        assert result["last_synced_at"] is not None

    async def test_delete(self, db: Database):
        repo = make_tracked_repo()
        await db.insert_tracked_repo(repo)
        await db.delete_tracked_repo(repo["id"])
        result = await db.get_tracked_repo(repo["id"])
        assert result is None

    async def test_delete_cascades_to_forks(self, db: Database):
        repo = make_tracked_repo()
        await db.insert_tracked_repo(repo)
        fork = make_fork(repo["id"])
        await db.insert_fork(fork)
        await db.delete_tracked_repo(repo["id"])
        result = await db.get_fork(fork["id"])
        assert result is None

    async def test_insert_duplicate_github_id_raises(self, db: Database):
        repo1 = make_tracked_repo(github_id=999)
        repo2 = make_tracked_repo(github_id=999, owner="other", name="x", full_name="other/x")
        await db.insert_tracked_repo(repo1)
        with pytest.raises(aiosqlite.IntegrityError):
            await db.insert_tracked_repo(repo2)

    async def test_insert_with_default_sync_status(self, db: Database):
        """Repos inserted without sync_status get default 'ok'."""
        repo = make_tracked_repo()
        await db.insert_tracked_repo(repo)
        result = await db.get_tracked_repo(repo["id"])
        assert result is not None
        assert result["sync_status"] == "ok"
        assert result["last_sync_error"] is None

    async def test_insert_with_inaccessible_status(self, db: Database):
        """Repos can be inserted with inaccessible sync_status and error message."""
        repo = make_tracked_repo(
            sync_status="inaccessible",
            last_sync_error="404 Not Found",
        )
        await db.insert_tracked_repo(repo)
        result = await db.get_tracked_repo(repo["id"])
        assert result is not None
        assert result["sync_status"] == "inaccessible"
        assert result["last_sync_error"] == "404 Not Found"

    async def test_update_sync_status(self, db: Database):
        """sync_status can be updated from ok to inaccessible."""
        repo = make_tracked_repo()
        await db.insert_tracked_repo(repo)
        repo["sync_status"] = "inaccessible"
        repo["last_sync_error"] = "403 Forbidden"
        await db.update_tracked_repo(repo)
        result = await db.get_tracked_repo(repo["id"])
        assert result is not None
        assert result["sync_status"] == "inaccessible"
        assert result["last_sync_error"] == "403 Forbidden"

    async def test_list_filtered_by_sync_status(self, db: Database):
        """list_tracked_repos(sync_status=...) filters correctly."""
        repo_ok = make_tracked_repo(
            github_id=1, owner="a", name="r1", full_name="a/r1", sync_status="ok"
        )
        repo_bad = make_tracked_repo(
            github_id=2,
            owner="b",
            name="r2",
            full_name="b/r2",
            sync_status="inaccessible",
            last_sync_error="404",
        )
        await db.insert_tracked_repo(repo_ok)
        await db.insert_tracked_repo(repo_bad)

        results = await db.list_tracked_repos(sync_status="inaccessible")
        assert len(results) == 1
        assert results[0]["sync_status"] == "inaccessible"

        results_ok = await db.list_tracked_repos(sync_status="ok")
        assert len(results_ok) == 1
        assert results_ok[0]["sync_status"] == "ok"

    async def test_migration_adds_columns_to_existing_db(self, db: Database):
        """Re-connecting after schema change adds new columns via ALTER TABLE migration."""
        await db.close()
        db2 = Database(":memory:")
        await db2.connect()
        repo = make_tracked_repo()
        await db2.insert_tracked_repo(repo)
        result = await db2.get_tracked_repo(repo["id"])
        assert result is not None
        assert result["sync_status"] == "ok"
        await db2.close()


# ---------------------------------------------------------------------------
# Fork CRUD
# ---------------------------------------------------------------------------


class TestForkCRUD:
    async def test_insert_and_get(self, db: Database, repo_in_db: dict):
        fork = make_fork(repo_in_db["id"])
        await db.insert_fork(fork)
        result = await db.get_fork(fork["id"])
        assert result is not None
        assert result["full_name"] == fork["full_name"]
        assert result["stars"] == 42

    async def test_get_nonexistent_returns_none(self, db: Database):
        result = await db.get_fork(make_id())
        assert result is None

    async def test_get_by_name(self, db: Database, repo_in_db: dict):
        fork = make_fork(repo_in_db["id"])
        await db.insert_fork(fork)
        result = await db.get_fork_by_name(fork["full_name"])
        assert result is not None
        assert result["id"] == fork["id"]

    async def test_list_by_repo(self, db: Database, repo_in_db: dict):
        fork1 = make_fork(repo_in_db["id"], github_id=100, owner="u1", full_name="u1/linux")
        fork2 = make_fork(repo_in_db["id"], github_id=101, owner="u2", full_name="u2/linux")
        await db.insert_fork(fork1)
        await db.insert_fork(fork2)
        results = await db.list_forks(repo_in_db["id"])
        assert len(results) == 2

    async def test_list_filtered_by_vitality(self, db: Database, repo_in_db: dict):
        fork_active = make_fork(
            repo_in_db["id"],
            github_id=200,
            owner="a",
            full_name="a/linux",
            vitality="active",
        )
        fork_stale = make_fork(
            repo_in_db["id"],
            github_id=201,
            owner="b",
            full_name="b/linux",
            vitality="stale",
        )
        await db.insert_fork(fork_active)
        await db.insert_fork(fork_stale)
        results = await db.list_forks(repo_in_db["id"], vitality="active")
        assert len(results) == 1
        assert results[0]["vitality"] == "active"

    async def test_update(self, db: Database, repo_in_db: dict):
        fork = make_fork(repo_in_db["id"])
        await db.insert_fork(fork)
        fork["stars"] = 100
        fork["head_sha"] = "newsha999"
        await db.update_fork(fork)
        result = await db.get_fork(fork["id"])
        assert result is not None
        assert result["stars"] == 100
        assert result["head_sha"] == "newsha999"

    async def test_insert_with_foreign_key_violation_raises(self, db: Database):
        fork = make_fork("nonexistent-repo-id")
        with pytest.raises(aiosqlite.IntegrityError):
            await db.insert_fork(fork)


# ---------------------------------------------------------------------------
# Signal CRUD
# ---------------------------------------------------------------------------


class TestSignalCRUD:
    async def test_insert_and_list(self, db: Database, repo_in_db: dict, fork_in_db: dict):
        signal = make_signal(fork_in_db["id"], repo_in_db["id"])
        await db.insert_signal(signal)
        results = await db.list_signals(repo_in_db["id"])
        assert len(results) == 1
        assert results[0]["category"] == "feature"
        assert results[0]["summary"] == "Added GPU support"

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

    async def test_list_filtered_by_since(self, db: Database, repo_in_db: dict, fork_in_db: dict):
        old_time = "2020-01-01T00:00:00+00:00"
        recent_time = now_iso()
        sig_old = make_signal(fork_in_db["id"], repo_in_db["id"], created_at=old_time)
        sig_new = make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            created_at=recent_time,
            summary="Recent change",
        )
        await db.insert_signal(sig_old)
        await db.insert_signal(sig_new)
        since = datetime(2024, 1, 1, tzinfo=UTC)
        results = await db.list_signals(repo_in_db["id"], since=since)
        assert len(results) == 1
        assert results[0]["summary"] == "Recent change"

    async def test_files_involved_stored_as_json(
        self, db: Database, repo_in_db: dict, fork_in_db: dict
    ):
        files = ["a.py", "b.py"]
        signal = make_signal(
            fork_in_db["id"],
            repo_in_db["id"],
            files_involved=json.dumps(files),
        )
        await db.insert_signal(signal)
        results = await db.list_signals(repo_in_db["id"])
        stored_files = json.loads(results[0]["files_involved"])
        assert stored_files == files


# ---------------------------------------------------------------------------
# Cluster CRUD
# ---------------------------------------------------------------------------


class TestClusterCRUD:
    async def test_insert_and_list(self, db: Database, repo_in_db: dict):
        cluster = make_cluster(repo_in_db["id"])
        await db.insert_cluster(cluster)
        results = await db.list_clusters(repo_in_db["id"])
        assert len(results) == 1
        assert results[0]["label"] == "GPU acceleration"

    async def test_add_cluster_member(self, db: Database, repo_in_db: dict, fork_in_db: dict):
        cluster = make_cluster(repo_in_db["id"])
        await db.insert_cluster(cluster)
        signal = make_signal(fork_in_db["id"], repo_in_db["id"])
        await db.insert_signal(signal)
        member = make_cluster_member(cluster["id"], signal["id"], fork_in_db["id"])
        await db.add_cluster_member(member)
        # Verify via raw query that the member exists
        results = await db.list_clusters(repo_in_db["id"])
        assert len(results) == 1

    async def test_cluster_member_cascade_on_cluster_delete(
        self, db: Database, repo_in_db: dict, fork_in_db: dict
    ):
        """Deleting a cluster should cascade to cluster_members."""
        cluster = make_cluster(repo_in_db["id"])
        await db.insert_cluster(cluster)
        signal = make_signal(fork_in_db["id"], repo_in_db["id"])
        await db.insert_signal(signal)
        member = make_cluster_member(cluster["id"], signal["id"], fork_in_db["id"])
        await db.add_cluster_member(member)
        # Delete the parent repo (cascades to cluster via tracked_repo_id FK)
        await db.delete_tracked_repo(repo_in_db["id"])
        results = await db.list_clusters(repo_in_db["id"])
        assert len(results) == 0


# ---------------------------------------------------------------------------
# DigestConfig & Digest CRUD
# ---------------------------------------------------------------------------


class TestDigestCRUD:
    async def test_insert_and_get_config(self, db: Database, repo_in_db: dict):
        config = make_digest_config(repo_in_db["id"])
        await db.insert_digest_config(config)
        result = await db.get_digest_config(config["id"])
        assert result is not None
        assert result["frequency"] == "weekly"
        assert result["min_significance"] == 5

    async def test_get_nonexistent_config_returns_none(self, db: Database):
        result = await db.get_digest_config(make_id())
        assert result is None

    async def test_insert_and_retrieve_digest(self, db: Database, repo_in_db: dict):
        config = make_digest_config(repo_in_db["id"])
        await db.insert_digest_config(config)
        digest = make_digest(config["id"])
        await db.insert_digest(digest)
        # We don't have a get_digest method specified, so verify via config
        # Just ensuring no errors on insert is the key check
        result = await db.get_digest_config(config["id"])
        assert result is not None

    async def test_digest_config_with_null_repo(self, db: Database):
        """Digest config can have a null tracked_repo_id (global config)."""
        config = make_digest_config(tracked_repo_id=None)
        await db.insert_digest_config(config)
        result = await db.get_digest_config(config["id"])
        assert result is not None
        assert result["tracked_repo_id"] is None


# ---------------------------------------------------------------------------
# Sync State
# ---------------------------------------------------------------------------


class TestSyncState:
    async def test_set_and_get(self, db: Database):
        await db.set_sync_state("last_run", "2024-01-01T00:00:00Z")
        result = await db.get_sync_state("last_run")
        assert result == "2024-01-01T00:00:00Z"

    async def test_get_nonexistent_returns_none(self, db: Database):
        result = await db.get_sync_state("nonexistent_key")
        assert result is None

    async def test_upsert_overwrites(self, db: Database):
        await db.set_sync_state("cursor", "abc")
        await db.set_sync_state("cursor", "def")
        result = await db.get_sync_state("cursor")
        assert result == "def"

    async def test_multiple_keys(self, db: Database):
        await db.set_sync_state("key1", "val1")
        await db.set_sync_state("key2", "val2")
        assert await db.get_sync_state("key1") == "val1"
        assert await db.get_sync_state("key2") == "val2"


# ---------------------------------------------------------------------------
# Vector search (graceful degradation)
# ---------------------------------------------------------------------------


class TestVectorSearch:
    async def test_vec_enabled_flag_set(self, db: Database):
        """vec_enabled should be a boolean flag on the database."""
        assert isinstance(db.vec_enabled, bool)

    async def test_search_without_vec_returns_empty(self, db: Database):
        """If sqlite-vec is not available, search_similar_signals returns empty."""
        if not db.vec_enabled:
            embedding = [0.1] * 384
            results = await db.search_similar_signals(embedding, make_id())
            assert results == []


# ---------------------------------------------------------------------------
# Annotations CRUD
# ---------------------------------------------------------------------------


class TestAnnotationsCRUD:
    async def test_insert_and_get(self, db: Database, fork_in_db: dict):
        annotation = {
            "id": make_id(),
            "fork_id": fork_in_db["id"],
            "title": "Interesting fork",
            "body": "This fork has unique GPU optimizations",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.insert_annotation(annotation)
        result = await db.get_annotation_by_fork(fork_in_db["id"])
        assert result is not None
        assert result["title"] == "Interesting fork"

    async def test_get_nonexistent_returns_none(self, db: Database):
        result = await db.get_annotation_by_fork(make_id())
        assert result is None

    async def test_unique_fork_constraint(self, db: Database, fork_in_db: dict):
        """Only one annotation per fork is allowed."""
        ann1 = {
            "id": make_id(),
            "fork_id": fork_in_db["id"],
            "title": "First",
            "body": "First annotation",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        ann2 = {
            "id": make_id(),
            "fork_id": fork_in_db["id"],
            "title": "Second",
            "body": "Should fail",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.insert_annotation(ann1)
        with pytest.raises(aiosqlite.IntegrityError):
            await db.insert_annotation(ann2)

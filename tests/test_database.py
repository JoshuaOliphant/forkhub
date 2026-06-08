# ABOUTME: Tests for the SQLite database layer.
# ABOUTME: Covers schema creation, CRUD for all tables, and sync state management.

from __future__ import annotations

from forkhub.database import Database
from tests.stubs import (
    make_cluster,
    make_cluster_member,
    make_id,
    make_signal,
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

    async def test_search_without_vec_returns_empty(self, db: Database):
        """If sqlite-vec is not available, search_similar_signals returns empty."""
        if not db.vec_enabled:
            embedding = [0.1] * 384
            results = await db.search_similar_signals(embedding, make_id())
            assert results == []

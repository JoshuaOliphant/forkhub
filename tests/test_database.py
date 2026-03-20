# ABOUTME: Tests for the SQLite database layer.
# ABOUTME: Covers schema creation, CRUD for all tables, and sync state management.

from __future__ import annotations

from forkhub.database import Database
from tests.stubs import (
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

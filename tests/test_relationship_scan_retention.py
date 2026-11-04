# ABOUTME: Prevent partial discoveries from destroying previously complete fork intelligence.
# ABOUTME: Verify scan attempts, freshness, recovery, migration and user boundaries.

from __future__ import annotations

import aiosqlite

from forkhub.database import Database
from forkhub.mcp_preview_queries import PreviewQueries


def snapshot(
    *,
    github_id: int = 100,
    repository: str = "alice/project",
    complete: bool = True,
    pages: int = 2,
    edge_id: int = 200,
) -> dict:
    return {
        "focus_github_id": github_id,
        "focus_repo": repository,
        "upstream_repo": None,
        "complete": complete,
        "pages_scanned": pages,
        "relationships": [
            {
                "direction": "downstream",
                "github_id": edge_id,
                "source_repo": f"forks/repo-{edge_id}",
                "target_repo": repository,
                "is_user_repository": False,
            }
        ],
    }


async def test_partial_attempt_preserves_complete_edges_and_reports_staleness(tmp_path):
    path = tmp_path / "retained.db"
    async with Database(path) as db:
        original = snapshot()
        await db.save_relationship_snapshot("ALICE", original)
        await db.save_relationship_snapshot(
            "alice", snapshot(complete=False, pages=1, edge_id=999)
        )
        assert await db.get_relationship_snapshot("alice", "alice/project") == original
        preview = PreviewQueries(path, "alice").get_cached_relationships("alice/project")
        assert preview["snapshot"]["relationships"][0]["github_id"] == 200
        assert preview["preserved_complete_snapshot"] is True
        assert preview["last_attempt_complete"] is False
        assert preview["last_attempt_pages_scanned"] == 1
        assert preview["last_complete_at"] is not None
        assert preview["last_attempt_at"] is not None
        assert "stale" in preview["warning"]

    # The evidence and last-failed-attempt metadata survive a process restart.
    async with Database(path) as reopened:
        assert await reopened.get_relationship_snapshot("ALICE", "alice/project") == original


async def test_first_incomplete_discovery_is_still_visible(tmp_path):
    path = tmp_path / "incomplete.db"
    async with Database(path) as db:
        partial = snapshot(complete=False)
        await db.save_relationship_snapshot("alice", partial)
        assert await db.get_relationship_snapshot("alice", "alice/project") == partial
        result = PreviewQueries(path, "ALICE").get_cached_relationships("alice/project")
        assert result["preserved_complete_snapshot"] is False
        assert result["last_complete_at"] is None
        assert result["last_attempt_complete"] is False
        assert "Incomplete fork coverage" in result["warning"]


async def test_later_complete_replaces_stale_graph(tmp_path):
    path = tmp_path / "recovery.db"
    async with Database(path) as db:
        await db.save_relationship_snapshot("alice", snapshot())
        await db.save_relationship_snapshot("alice", snapshot(complete=False, edge_id=301))
        recovered = snapshot(pages=4, edge_id=302)
        await db.save_relationship_snapshot("alice", recovered)
        assert await db.get_relationship_snapshot("alice", "alice/project") == recovered
        result = PreviewQueries(path, "alice").get_cached_relationships("alice/project")
        assert result["preserved_complete_snapshot"] is False
        assert result["last_attempt_complete"] is True
        assert result["last_attempt_pages_scanned"] == 4
        assert result["warning"] is None


async def test_multiple_partial_attempts_without_complete_replace_each_other(tmp_path):
    path = tmp_path / "partial-only.db"
    async with Database(path) as db:
        await db.save_relationship_snapshot("alice", snapshot(complete=False, edge_id=201))
        second = snapshot(complete=False, pages=3, edge_id=202)
        await db.save_relationship_snapshot("alice", second)
        assert await db.get_relationship_snapshot("alice", "alice/project") == second


async def test_attempts_are_isolated_by_user_and_github_id(tmp_path):
    path = tmp_path / "scoped.db"
    async with Database(path) as db:
        initial = snapshot()
        independent = snapshot(github_id=101, repository="alice/other", edge_id=303)
        await db.save_relationship_snapshot("alice", initial)
        await db.save_relationship_snapshot("bob", initial)
        await db.save_relationship_snapshot("alice", independent)
        await db.save_relationship_snapshot("alice", snapshot(complete=False, edge_id=400))
        assert await db.get_relationship_snapshot("bob", "alice/project") == initial
        assert await db.get_relationship_snapshot("alice", "alice/other") == independent


async def test_existing_schema_adds_metadata_and_retains_legacy_complete(tmp_path):
    path = tmp_path / "legacy.db"
    async with aiosqlite.connect(path) as conn:
        await conn.execute(
            """
            CREATE TABLE relationship_snapshots (
                username TEXT NOT NULL, focus_github_id INTEGER NOT NULL,
                focus_repo TEXT NOT NULL, upstream_repo TEXT,
                complete BOOLEAN NOT NULL, pages_scanned INTEGER NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY(username, focus_github_id)
            )
            """
        )
        await conn.execute(
            """
            INSERT INTO relationship_snapshots (
                username, focus_github_id, focus_repo, upstream_repo,
                complete, pages_scanned
            ) VALUES ('alice', 100, 'alice/project', NULL, 1, 2)
            """
        )
        await conn.commit()

    async with Database(path) as db:
        await db.save_relationship_snapshot(
            "alice", snapshot(complete=False, pages=1, edge_id=400)
        )
        result = PreviewQueries(path, "alice").get_cached_relationships("alice/project")
        assert result["snapshot"]["complete"] is True
        assert result["preserved_complete_snapshot"] is True
        assert result["last_complete_at"] is not None

# ABOUTME: Explore uses the same relationship scan contract as MCP.
# ABOUTME: Test never-scanned, complete, incomplete and preserved-complete states.

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from forkhub import ForkHub
from forkhub.config import ForkHubSettings
from forkhub.web.data import build_explore_data
from tests.stubs import (
    StubEmbeddingProvider,
    StubGitProvider,
    StubNotificationBackend,
    make_tracked_repo,
)

if TYPE_CHECKING:
    from forkhub.database import Database


@pytest.fixture
def hub(
    db: Database,
    provider: StubGitProvider,
    backend: StubNotificationBackend,
    embedding_provider: StubEmbeddingProvider,
) -> ForkHub:
    return ForkHub(
        settings=ForkHubSettings(),
        git_provider=provider,
        notification_backends=[backend],
        embedding_provider=embedding_provider,
        db=db,
    )


def snapshot(*, complete=True, edge_id=456):
    return {
        "focus_github_id": 123456,
        "focus_repo": "torvalds/linux",
        "upstream_repo": None,
        "complete": complete,
        "pages_scanned": 1,
        "relationships": [
            {
                "direction": "downstream",
                "github_id": edge_id,
                "source_repo": f"example/fork-{edge_id}",
                "target_repo": "torvalds/linux",
                "is_user_repository": False,
            }
        ],
    }


class TestBuildExploreData:
    async def test_never_scanned_is_explicit(self, hub: ForkHub, db: Database):
        await db.insert_tracked_repo(make_tracked_repo())
        data = await build_explore_data(hub, "torvalds", "linux")
        assert data["repo"]["full_name"] == "torvalds/linux"
        assert data["repo"]["last_sync"] is None
        assert data["relationship"]["status"] == "not_scanned"
        assert data["discovery_username"] == "torvalds"
        assert "forks" not in data
        assert "clusters" not in data

    async def test_complete_snapshot_uses_mcp_contract(self, hub: ForkHub, db: Database):
        await db.insert_tracked_repo(make_tracked_repo())
        await db.save_relationship_snapshot("torvalds", snapshot())
        data = await build_explore_data(hub, "torvalds", "linux")
        assert data["relationship"] == await db.get_relationship_view("torvalds", "torvalds/linux")
        assert data["relationship"]["status"] == "cached"
        edges = data["relationship"]["snapshot"]["relationships"]
        assert edges[0]["source_repo"] == "example/fork-456"
        assert data["relationship"]["last_attempt_complete"] is True

    async def test_incomplete_snapshot_is_not_exhaustive(self, hub: ForkHub, db: Database):
        await db.insert_tracked_repo(make_tracked_repo())
        await db.save_relationship_snapshot("torvalds", snapshot(complete=False))
        data = await build_explore_data(hub, "torvalds", "linux")
        assert data["relationship"]["snapshot"]["complete"] is False
        assert "Incomplete fork coverage" in data["relationship"]["warning"]

    async def test_partial_refresh_retains_complete_graph(self, hub: ForkHub, db: Database):
        await db.insert_tracked_repo(make_tracked_repo())
        await db.save_relationship_snapshot("torvalds", snapshot())
        await db.save_relationship_snapshot("torvalds", snapshot(complete=False, edge_id=999))
        data = await build_explore_data(hub, "torvalds", "linux")
        relationship = data["relationship"]
        assert relationship["preserved_complete_snapshot"] is True
        assert relationship["last_attempt_complete"] is False
        assert relationship["snapshot"]["relationships"][0]["source_repo"] == "example/fork-456"

    async def test_configured_username_scopes_watched_repository(self, hub: ForkHub, db: Database):
        await db.insert_tracked_repo(make_tracked_repo())
        hub._settings.github.username = "watcher"
        await db.save_relationship_snapshot("watcher", snapshot())
        data = await build_explore_data(hub, "torvalds", "linux")
        assert data["relationship"]["status"] == "cached"
        assert data["discovery_username"] == "watcher"

    async def test_last_sync_serialized_when_set(self, hub: ForkHub, db: Database):
        await db.insert_tracked_repo(make_tracked_repo(last_synced_at="2026-06-01T12:00:00+00:00"))
        data = await build_explore_data(hub, "torvalds", "linux")
        assert data["repo"]["last_sync"].startswith("2026-06-01T12:00:00")

    async def test_untracked_repo_raises(self, hub: ForkHub):
        with pytest.raises(ValueError, match="not tracked"):
            await build_explore_data(hub, "nobody", "nothing")

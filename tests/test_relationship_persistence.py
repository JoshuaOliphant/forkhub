# ABOUTME: Tests persistent bidirectional relationship snapshots and public APIs.
# ABOUTME: Uses in-memory SQLite and shared GitProvider stubs.

from __future__ import annotations

import pytest

from forkhub import ForkHub
from forkhub.database import Database
from forkhub.models import ForkInfo
from forkhub.services.relationships import RelationshipDirection
from tests.stubs import STUB_NOW, StubEmbeddingProvider, StubGitProvider


def _sibling(github_id: int, full_name: str) -> ForkInfo:
    return ForkInfo(
        github_id=github_id,
        owner=full_name.split("/")[0],
        full_name=full_name,
        default_branch="main",
        stars=0,
        last_pushed_at=STUB_NOW,
        has_diverged=True,
        created_at=STUB_NOW,
    )


@pytest.fixture
def hub(db: Database) -> ForkHub:
    return ForkHub(
        db=db,
        git_provider=StubGitProvider.with_testuser_data(),
        embedding_provider=StubEmbeddingProvider(),
        auto_analyze=False,
    )


class TestPersistentRelationships:
    async def test_cache_miss(self, hub: ForkHub):
        assert await hub.get_cached_relationships("testuser", "testuser/alpha") is None

    async def test_persisted_downstream_snapshot(self, hub: ForkHub):
        discovered = await hub.discover_relationships("testuser", "testuser/alpha")
        cached = await hub.get_cached_relationships("testuser", "testuser/alpha")
        assert cached == discovered
        assert cached is not None
        assert cached.focus_github_id == 1001
        assert cached.relationships[0].direction == RelationshipDirection.DOWNSTREAM

    async def test_repeated_refresh_replaces_old_edges(self, hub: ForkHub):
        await hub.discover_relationships("testuser", "testuser/alpha")
        provider = hub._provider
        provider._forks["testuser/alpha"] = [
            _sibling(8888, "second/alpha"),
        ]
        refreshed = await hub.discover_relationships("testuser", "testuser/alpha")
        cached = await hub.get_cached_relationships("testuser", "testuser/alpha")
        assert cached == refreshed
        assert cached is not None
        assert [edge.github_id for edge in cached.relationships] == [8888]

    async def test_user_cache_is_scoped(self, hub: ForkHub):
        await hub.discover_relationships("testuser", "testuser/alpha")
        assert await hub.get_cached_relationships("other", "testuser/alpha") is None
        assert await hub.get_cached_relationships("TESTUSER", "testuser/alpha") is not None

    async def test_partial_scan_is_explicit(self, hub: ForkHub):
        provider = hub._provider
        del provider.repos["upstream-org/forked-lib"]
        discovered = await hub.discover_relationships("testuser", "testuser/forked-lib")
        cached = await hub.get_cached_relationships("testuser", "testuser/forked-lib")
        assert cached == discovered
        assert cached is not None
        assert not cached.complete
        assert cached.upstream_repo == "upstream-org/forked-lib"

    async def test_duplicate_edge_rolls_back(self, db: Database):
        snapshot = {
            "focus_github_id": 123,
            "focus_repo": "alice/project",
            "upstream_repo": None,
            "complete": True,
            "pages_scanned": 1,
            "relationships": [
                {
                    "direction": "downstream",
                    "github_id": 456,
                    "source_repo": "bob/project",
                    "target_repo": "alice/project",
                    "is_user_repository": False,
                }
            ],
        }
        await db.save_relationship_snapshot("alice", snapshot)
        invalid = {**snapshot, "relationships": snapshot["relationships"] * 2}
        with pytest.raises(Exception):
            await db.save_relationship_snapshot("alice", invalid)
        stored = await db.get_relationship_snapshot("alice", "alice/project")
        assert stored == snapshot

    async def test_existing_sqlite_database_migrates(self, tmp_path):
        path = tmp_path / "persist.db"
        first = Database(path)
        await first.connect()
        await first.close()
        second = Database(path)
        await second.connect()
        try:
            assert await second.get_relationship_snapshot("alice", "missing/repo") is None
            cursor = await second._db.execute(
                "SELECT name FROM sqlite_master WHERE name = 'repository_relationships'"
            )
            assert await cursor.fetchone() is not None
        finally:
            await second.close()

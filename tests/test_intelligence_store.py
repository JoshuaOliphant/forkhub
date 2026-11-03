# ABOUTME: Tests the swappable intelligence storage contract and SQLite adapter.
# ABOUTME: Verifies ForkHub operates with an injected non-SQLite store.

from __future__ import annotations

from forkhub import ForkHub
from forkhub.intelligence_store import IntelligenceStore, SQLiteIntelligenceStore
from forkhub.services.relationships import RelationshipDirection, RelationshipSnapshot
from tests.stubs import StubEmbeddingProvider, StubGitProvider, StubIntelligenceStore


async def test_sqlite_store_roundtrip(db):
    store = SQLiteIntelligenceStore(db)
    snapshot = RelationshipSnapshot(focus_github_id=1001, focus_repo="testuser/alpha")
    assert isinstance(store, IntelligenceStore)
    assert await store.get_relationship_snapshot("testuser", "testuser/alpha") is None
    await store.save_relationship_snapshot("testuser", snapshot)
    assert await store.get_relationship_snapshot("testuser", "testuser/alpha") == snapshot
    assert await store.get_relationship_snapshot("other", "testuser/alpha") is None


async def test_injected_store_drives_facade_without_sqlite_writes(db):
    store = StubIntelligenceStore()
    assert isinstance(store, IntelligenceStore)
    hub = ForkHub(
        db=db,
        intelligence_store=store,
        git_provider=StubGitProvider.with_testuser_data(),
        embedding_provider=StubEmbeddingProvider(),
        auto_analyze=False,
    )
    observed = await hub.discover_relationships("testuser", "testuser/alpha")
    assert observed.relationships[0].direction == RelationshipDirection.DOWNSTREAM
    assert await hub.get_cached_relationships("testuser", "testuser/alpha") == observed
    assert await db.get_relationship_snapshot("testuser", "testuser/alpha") is None
    assert await hub.get_cached_relationships("other", "testuser/alpha") is None


async def test_in_memory_store_returns_independent_snapshots():
    store = StubIntelligenceStore()
    snapshot = RelationshipSnapshot(focus_github_id=7, focus_repo="alice/repo")
    await store.save_relationship_snapshot("alice", snapshot)
    snapshot.complete = False
    first = await store.get_relationship_snapshot("alice", "alice/repo")
    assert first is not None
    assert first.complete
    first.complete = False
    second = await store.get_relationship_snapshot("alice", "alice/repo")
    assert second is not None
    assert second.complete

# ABOUTME: Apply the same MCP cache contract to read-only SQLite and asynchronous D1 queries.
# ABOUTME: Compare real SQL results, limits, validation, snapshot freshness, and provenance.

from __future__ import annotations

import inspect

import pytest

from forkhub.database import Database
from forkhub.mcp_d1_queries import D1Queries
from forkhub.mcp_preview_queries import PreviewQueries
from tests.stubs import make_signal, make_tracked_repo


async def test_missing_database_fails_without_creating_it(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(FileNotFoundError):
        PreviewQueries(path, "alice")
    assert not path.exists()


async def test_empty_username_rejected(tmp_path):
    path = tmp_path / "existing.db"
    path.touch()
    with pytest.raises(ValueError, match="FORKHUB_MCP_USER"):
        PreviewQueries(path, " ")
    with pytest.raises(ValueError, match="FORKHUB_MCP_USER"):
        D1Queries(None, " ")


@pytest.fixture(params=["sqlite", "d1"])
async def preview(tmp_path, request):
    path = tmp_path / "preview.db"
    db = Database(path)
    await db.connect()
    reference = PreviewQueries(path, "ALICE")

    async def query(sql, parameters):
        async with db._db.execute(sql, parameters) as cursor:
            return await cursor.fetchall()

    reader = reference if request.param == "sqlite" else D1Queries(query, " ALICE ")

    async def read(method, *args, **kwargs):
        result = getattr(reader, method)(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
            assert result == getattr(reference, method)(*args, **kwargs)
        return result

    yield db, read
    await db.close()


async def test_tracked_repositories_and_limits(preview):
    db, reader = preview
    for i in range(3):
        await db.insert_tracked_repo(
            make_tracked_repo(
                github_id=i + 1,
                owner="alice",
                name=f"repo{i}",
                full_name=f"alice/repo{i}",
                excluded=i == 2,
            )
        )
    result = await reader("list_tracked_repositories", limit=1)
    assert result["repositories"][0]["name"] == "alice/repo0"
    assert result["truncated"] is True
    assert result["returned"] == 1
    assert len((await reader("list_tracked_repositories", limit=20))["repositories"]) == 2
    for limit in (0, 51):
        with pytest.raises(ValueError, match="limit"):
            await reader("list_tracked_repositories", limit=limit)


async def test_relationship_cache_miss_and_complete_snapshot(preview):
    db, reader = preview
    assert (await reader("get_cached_relationships", "alice/repo"))["status"] == "not_scanned"
    snapshot = {
        "focus_github_id": 2,
        "focus_repo": "alice/repo",
        "upstream_repo": "acme/repo",
        "complete": True,
        "pages_scanned": 1,
        "relationships": [
            {
                "direction": "upstream",
                "github_id": 1,
                "source_repo": "acme/repo",
                "target_repo": "alice/repo",
                "is_user_repository": False,
            }
        ],
    }
    await db.save_relationship_snapshot("alice", snapshot)
    found = await reader("get_cached_relationships", "ALICE/REPO")
    assert found["status"] == "cached"
    assert found["snapshot"]["focus_github_id"] == 2
    assert found["snapshot"]["relationships"][0]["source_repo"] == "acme/repo"
    assert found["warning"] is None


async def test_partial_relationship_cache_discloses_incomplete_coverage(preview):
    db, reader = preview
    await db.save_relationship_snapshot(
        "alice",
        {
            "focus_github_id": 7,
            "focus_repo": "alice/partial",
            "upstream_repo": None,
            "complete": False,
            "pages_scanned": 3,
            "relationships": [],
        },
    )
    found = await reader("get_cached_relationships", "alice/partial")
    assert found["snapshot"]["complete"] is False
    assert "Incomplete" in found["warning"]


@pytest.mark.parametrize("legacy_metadata", [False, True])
async def test_relationship_snapshot_preserves_complete_results_and_legacy_metadata(
    preview, legacy_metadata
):
    db, reader = preview
    snapshot = {
        "focus_github_id": 9,
        "focus_repo": "alice/preserved",
        "upstream_repo": "upstream/repo",
        "complete": True,
        "pages_scanned": 2,
        "relationships": [
            {
                "direction": "upstream",
                "github_id": 1,
                "source_repo": "upstream/repo",
                "target_repo": "alice/preserved",
                "is_user_repository": False,
            }
        ],
    }
    await db.save_relationship_snapshot("alice", snapshot)
    if legacy_metadata:
        await db._db.execute(
            "UPDATE relationship_snapshots SET last_attempt_at = NULL, "
            "last_attempt_complete = NULL, last_attempt_pages_scanned = NULL, "
            "last_complete_at = NULL"
        )
        await db._db.commit()
    else:
        await db.save_relationship_snapshot(
            "alice", {**snapshot, "complete": False, "pages_scanned": 4, "relationships": []}
        )

    result = await reader("get_cached_relationships", "alice/preserved")

    assert result["snapshot"]["relationships"] == snapshot["relationships"]
    assert result["snapshot"]["complete"] is True
    assert result["last_attempt_complete"] is legacy_metadata
    assert result["last_attempt_pages_scanned"] == (2 if legacy_metadata else 4)
    assert result["last_attempt_at"] is not None
    assert result["last_complete_at"] is not None
    assert result["preserved_complete_snapshot"] is not legacy_metadata
    assert (result["warning"] is None) is legacy_metadata


async def test_signal_missing_repo_returns_structured_status(preview):
    _, reader = preview
    result = await reader("list_cached_signals", "alice/missing")
    assert result["status"] == "not_tracked"
    assert result["signals"] == []


@pytest.mark.parametrize("repository", ["alice/excluded", "alice/repo' OR 1=1 --"])
async def test_signal_lookup_excludes_hidden_repositories_and_binds_names(preview, repository):
    db, reader = preview
    await db.insert_tracked_repo(
        make_tracked_repo(
            github_id=99,
            owner="alice",
            name="excluded",
            full_name="alice/excluded",
            excluded=True,
        )
    )

    result = await reader("list_cached_signals", repository)

    assert result["status"] == "not_tracked"
    assert result["signals"] == []


async def test_signal_filters_truncates_and_keeps_provenance_caveat(preview):
    db, reader = preview
    repo = make_tracked_repo(github_id=888, owner="alice", name="repo", full_name="alice/repo")
    await db.insert_tracked_repo(repo)
    for i in range(3):
        await db.insert_signal(
            make_signal(
                None,
                repo["id"],
                significance=6 + i,
                summary=f"change {i}",
            )
        )
    result = await reader("list_cached_signals", "ALICE/REPO", min_significance=7, limit=1)
    assert result["status"] == "cached"
    assert result["truncated"]
    assert result["signals"][0]["significance"] == 8
    assert result["signals"][0]["interpretation_is_model_generated"]
    assert not result["signals"][0]["verified_against_immutable_sha_evidence"]
    assert result["signals"][0]["files_involved"] == ["src/gpu.py", "src/train.py"]
    assert "SHA-level" in result["warning"]
    assert (await reader("list_cached_signals", "alice/repo", min_significance=10))["signals"] == []


@pytest.mark.parametrize("value", ["broken", "a/", "/b", "a/b/c"])
async def test_repository_name_validation(value, preview):
    _, reader = preview
    with pytest.raises(ValueError, match="owner/name"):
        await reader("get_cached_relationships", value)
    with pytest.raises(ValueError, match="owner/name"):
        await reader("list_cached_signals", value)


@pytest.mark.parametrize("significance,limit", [(0, 1), (11, 1), (5, 0), (5, 51)])
async def test_signal_range_validation(preview, significance, limit):
    _, reader = preview
    with pytest.raises(ValueError):
        await reader(
            "list_cached_signals", "alice/repo", min_significance=significance, limit=limit
        )

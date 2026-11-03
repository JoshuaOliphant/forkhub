# ABOUTME: Contract tests for the local-only read-only MCP intelligence query service.
# ABOUTME: Check no database creation, pagination limits, and honest missing-data states.

from __future__ import annotations

import sqlite3

import pytest

from forkhub.database import Database
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


@pytest.fixture
async def preview(tmp_path):
    path = tmp_path / "preview.db"
    db = Database(path)
    await db.connect()
    yield db, PreviewQueries(path, "ALICE")
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
    result = reader.list_tracked_repositories(limit=1)
    assert result["repositories"][0]["name"] == "alice/repo0"
    assert result["truncated"] is True
    assert result["returned"] == 1
    assert len(reader.list_tracked_repositories(limit=20)["repositories"]) == 2
    for limit in (0, 51):
        with pytest.raises(ValueError, match="limit"):
            reader.list_tracked_repositories(limit=limit)


async def test_relationship_cache_miss_and_complete_snapshot(preview):
    db, reader = preview
    assert reader.get_cached_relationships("alice/repo")["status"] == "not_scanned"
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
    found = reader.get_cached_relationships("ALICE/REPO")
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
    found = reader.get_cached_relationships("alice/partial")
    assert found["snapshot"]["complete"] is False
    assert "Incomplete" in found["warning"]


async def test_signal_missing_repo_returns_structured_status(preview):
    _, reader = preview
    result = reader.list_cached_signals("alice/missing")
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
    result = reader.list_cached_signals("ALICE/REPO", min_significance=7, limit=1)
    assert result["status"] == "cached"
    assert result["truncated"]
    assert result["signals"][0]["significance"] == 8
    assert result["signals"][0]["interpretation_is_model_generated"]
    assert not result["signals"][0]["verified_against_immutable_sha_evidence"]
    assert result["signals"][0]["files_involved"] == ["src/gpu.py", "src/train.py"]
    assert "SHA-level" in result["warning"]
    assert reader.list_cached_signals("alice/repo", min_significance=10)["signals"] == []


@pytest.mark.parametrize("value", ["broken", "a/", "/b", "a/b/c"])
def test_repository_name_validation(value, tmp_path):
    path = tmp_path / "empty.db"
    with sqlite3.connect(path):
        pass
    reader = PreviewQueries(path, "alice")
    with pytest.raises(ValueError, match="owner/name"):
        reader.get_cached_relationships(value)
    with pytest.raises(ValueError, match="owner/name"):
        reader.list_cached_signals(value)


@pytest.mark.parametrize("significance,limit", [(0, 1), (11, 1), (5, 0), (5, 51)])
async def test_signal_range_validation(preview, significance, limit):
    _, reader = preview
    with pytest.raises(ValueError):
        reader.list_cached_signals("alice/repo", min_significance=significance, limit=limit)

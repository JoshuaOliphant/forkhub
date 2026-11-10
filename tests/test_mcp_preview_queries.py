# ABOUTME: Apply the same MCP cache contract to read-only SQLite and asynchronous D1 queries.
# ABOUTME: Compare real SQL results, limits, validation, snapshot freshness, and provenance.

from __future__ import annotations

import inspect
import json

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


@pytest.mark.parametrize("state", ["unavailable", "partial", "verified"])
@pytest.mark.parametrize(
    "sync_status,last_synced_at,freshness",
    [
        ("ok", None, "unknown"),
        ("ok", "2026-11-10T12:00:00+00:00", "last_sync_succeeded"),
        ("error", "2026-11-09T12:00:00+00:00", "stale"),
        ("inaccessible", None, "stale"),
    ],
)
async def test_signal_evidence_and_cache_freshness_are_separate(
    preview, state, sync_status, last_synced_at, freshness
):
    db, reader = preview
    repo = make_tracked_repo(
        full_name="alice/repo", sync_status=sync_status, last_synced_at=last_synced_at
    )
    await db.insert_tracked_repo(repo)
    sha = "a" * 40
    evidence = {
        "source_repository": "alice/fork",
        "commit_shas": [sha],
        "files": ["src/gpu.py"],
        "changes": [
            {
                "commit_sha": sha,
                "filename": "src/gpu.py",
                "status": "modified",
                "patch": "@@ -1 +1 @@\n-old\n+actual",
            }
        ],
        "verification_state": state,
        "verified_at": "2026-11-10T11:00:00+00:00" if state == "verified" else None,
    }
    await db.insert_signal(
        make_signal(
            None,
            repo["id"],
            files_involved=json.dumps(["src/gpu.py"]),
            evidence=json.dumps(evidence),
        )
    )

    result = await reader("list_cached_signals", "alice/repo")

    signal = result["signals"][0]
    assert signal["evidence"] == evidence
    assert signal["commit_links"] == [f"https://github.com/alice/fork/commit/{sha}"]
    assert signal["verified_against_immutable_sha_evidence"] is (state == "verified")
    assert signal["interpretation_is_model_generated"] is True
    assert signal["warning"]
    assert result["freshness"] == freshness
    assert result["last_synced_at"] == last_synced_at
    assert result["sync_status"] == sync_status
    assert "current branch equivalence" in result["warning"]
    if freshness == "stale":
        assert "may be stale" in result["warning"]
    empty = await reader("list_cached_signals", "alice/repo", min_significance=10)
    assert empty["signals"] == []
    assert empty["freshness"] == freshness


@pytest.mark.parametrize(
    "malformed",
    [
        "{broken",
        "null",
        "[]",
        "{}",
        json.dumps(
            {
                "source_repository": "alice/fork",
                "commit_shas": [],
                "files": [],
                "verification_state": "verified",
                "verified_at": None,
            }
        ),
        json.dumps(
            {
                "source_repository": "alice/fork",
                "commit_shas": ["a" * 40],
                "files": ["src/a.py"],
                "verification_state": "verified",
                "verified_at": "2026-11-10T12:00:00",
                "changes": [{"commit_sha": "a" * 40, "filename": "src/a.py", "patch": "patch"}],
            }
        ),
        json.dumps(
            {
                "source_repository": "alice/fork",
                "commit_shas": ["main"],
                "files": ["src/a.py"],
                "verification_state": "verified",
            }
        ),
        json.dumps(
            {
                "source_repository": "alice/fork/../../evil",
                "commit_shas": ["a" * 40],
                "files": ["src/a.py"],
                "verification_state": "verified",
            }
        ),
    ],
)
async def test_malformed_cache_evidence_is_unavailable_and_never_linked(preview, malformed):
    db, reader = preview
    repo = make_tracked_repo(full_name="alice/repo")
    await db.insert_tracked_repo(repo)
    await db.insert_signal(make_signal(None, repo["id"]))
    await db._db.execute("UPDATE signals SET evidence = ?", (malformed,))
    await db._db.commit()

    result = await reader("list_cached_signals", "alice/repo")

    signal = result["signals"][0]
    assert signal["evidence"] is None
    assert signal["commit_links"] == []
    assert signal["verified_against_immutable_sha_evidence"] is False
    assert "malformed" in signal["warning"]


@pytest.mark.parametrize(
    "changes",
    [
        None,
        [],
        [{"commit_sha": "a" * 40, "filename": "src/a.py", "status": "modified", "patch": None}],
        [{"commit_sha": "a" * 40, "filename": "src/a.py", "status": "modified", "patch": " "}],
        [{"commit_sha": "b" * 40, "filename": "src/a.py", "status": "modified", "patch": "patch"}],
        [
            {
                "commit_sha": "a" * 40,
                "filename": "src/else.py",
                "status": "modified",
                "patch": "patch",
            }
        ],
        [{"commit_sha": "a" * 40, "filename": "src/a.py", "status": "modified", "patch": "patch"}],
    ],
)
async def test_verified_cache_evidence_requires_exact_commit_file_patch_coverage(preview, changes):
    db, reader = preview
    repo = make_tracked_repo(full_name="alice/repo")
    await db.insert_tracked_repo(repo)
    await db.insert_signal(make_signal(None, repo["id"]))
    evidence = {
        "source_repository": "alice/fork",
        "commit_shas": ["a" * 40, "b" * 40],
        "files": ["src/a.py", "src/b.py"],
        "verification_state": "verified",
        "verified_at": "2026-11-10T12:00:00+00:00",
    }
    if changes is not None:
        evidence["changes"] = changes
    await db._db.execute("UPDATE signals SET evidence = ?", (json.dumps(evidence),))
    await db._db.commit()

    result = await reader("list_cached_signals", "alice/repo")

    assert result["signals"][0]["evidence"] is None
    assert result["signals"][0]["verified_against_immutable_sha_evidence"] is False
    assert "malformed" in result["signals"][0]["warning"]


@pytest.mark.parametrize(
    "mutation", ["duplicate_sha", "duplicate_sha_case", "duplicate_file", "files_mismatch"]
)
async def test_cache_evidence_cannot_verify_unrelated_files_or_duplicate_commits(preview, mutation):
    db, reader = preview
    repo = make_tracked_repo(full_name="alice/repo")
    await db.insert_tracked_repo(repo)
    evidence = {
        "source_repository": "alice/fork",
        "commit_shas": ["a" * 40],
        "files": ["src/a.py"],
        "verification_state": "verified",
        "verified_at": "2026-11-10T12:00:00+00:00",
        "changes": [{"commit_sha": "a" * 40, "filename": "src/a.py", "patch": "patch"}],
    }
    if mutation == "duplicate_sha":
        evidence["commit_shas"].append("a" * 40)
    elif mutation == "duplicate_sha_case":
        evidence["commit_shas"].append("A" * 40)
    elif mutation == "duplicate_file":
        evidence["files"].append("src/a.py")
    await db.insert_signal(
        make_signal(
            None,
            repo["id"],
            files_involved=json.dumps(
                ["src/else.py"] if mutation == "files_mismatch" else ["src/a.py"]
            ),
            evidence=json.dumps(evidence),
        )
    )

    result = await reader("list_cached_signals", "alice/repo")

    signal = result["signals"][0]
    assert signal["evidence"] is None
    assert signal["commit_links"] == []
    assert signal["verified_against_immutable_sha_evidence"] is False
    assert "malformed" in signal["warning"]

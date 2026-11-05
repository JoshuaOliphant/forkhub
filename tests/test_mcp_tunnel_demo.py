# ABOUTME: Test synthetic MCP demo data isolation and tool-readable contracts.
# ABOUTME: Verify no real repository access and prevent overwriting an existing database.

from __future__ import annotations

import pytest

from examples.seed_mcp_demo import DEMO_REPO, DEMO_USER, seed
from forkhub.mcp_preview_queries import PreviewQueries


async def test_seeded_demo_is_readable_by_all_three_tools(tmp_path):
    database_path = tmp_path / "synthetic.db"
    await seed(database_path)
    preview = PreviewQueries(database_path, DEMO_USER)

    tracked = preview.list_tracked_repositories()
    assert tracked["repositories"][0]["name"] == DEMO_REPO
    assert not tracked["truncated"]

    relationships = preview.get_cached_relationships(DEMO_REPO)
    assert relationships["status"] == "cached"
    assert relationships["snapshot"]["complete"]
    assert relationships["snapshot"]["relationships"][0]["github_id"] == 900002

    signals = preview.list_cached_signals(DEMO_REPO)
    assert signals["status"] == "cached"
    assert signals["signals"][0]["summary"].startswith("Synthetic example")
    assert not signals["signals"][0]["verified_against_immutable_sha_evidence"]


async def test_demo_seed_does_not_overwrite_existing_database(tmp_path):
    path = tmp_path / "existing.db"
    path.write_bytes(b"existing contents")
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        await seed(path)
    assert path.read_bytes() == b"existing contents"


async def test_demo_seed_requires_existing_parent_directory(tmp_path):
    path = tmp_path / "nonexistent" / "demo.db"
    with pytest.raises(FileNotFoundError, match="destination directory"):
        await seed(path)
    assert not path.exists()

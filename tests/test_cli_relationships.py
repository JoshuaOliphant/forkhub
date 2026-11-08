# ABOUTME: Verify explicit CLI relationship cache population and incomplete-scan behavior.
# ABOUTME: Keep website and MCP consumers working from the same persisted cache.

from __future__ import annotations

from typer.testing import CliRunner

from forkhub.cli.app import app
from forkhub.cli.relationships_cmd import _relationships_impl
from forkhub.mcp_preview_queries import PreviewQueries
from tests.stubs import StubGitProvider


def test_relationship_command_is_registered():
    result = CliRunner().invoke(app, ["relationships", "--help"])
    assert result.exit_code == 0
    assert "--username" in result.output
    assert "--max-pages" in result.output


async def test_command_populates_mcp_readable_cache(db, tmp_path):
    provider = StubGitProvider.with_testuser_data()
    result = await _relationships_impl(
        "testuser/alpha", "testuser", db=db, provider=provider
    )
    assert result["repository"] == "testuser/alpha"
    assert result["complete"] is True
    assert result["relationship_count"] > 0

    snapshot = await db.get_relationship_snapshot("testuser", "testuser/alpha")
    assert snapshot is not None
    assert snapshot["complete"] is True

    # The MCP consumer reads the same persisted relationship snapshot.
    preview = PreviewQueries(db.path, "testuser").get_cached_relationships("testuser/alpha")
    assert preview["status"] == "cached"
    assert preview["snapshot"]["focus_repo"] == "testuser/alpha"


async def test_incomplete_attempt_does_not_claim_complete(db):
    provider = StubGitProvider.with_testuser_data()
    result = await _relationships_impl(
        "testuser/alpha", "testuser", max_pages=1, db=db, provider=provider
    )
    snapshot = await db.get_relationship_snapshot("testuser", "testuser/alpha")
    assert snapshot is not None
    assert snapshot["complete"] == result["complete"]
    assert snapshot["pages_scanned"] == result["pages_scanned"]

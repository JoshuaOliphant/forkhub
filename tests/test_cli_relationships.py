# ABOUTME: Verify relationship discovery CLI, persistence and incomplete coverage.
# ABOUTME: Ensure the read-only MCP consumer sees the same file-backed cache.

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from forkhub.cli import relationships_cmd
from forkhub.cli.app import app
from forkhub.cli.relationships_cmd import _relationships_impl
from forkhub.database import Database
from forkhub.mcp_preview_queries import PreviewQueries
from forkhub.models import ForkPage
from tests.stubs import StubGitProvider


def test_relationship_command_is_registered():
    result = CliRunner().invoke(app, ["relationships", "--help"])
    assert result.exit_code == 0
    assert "username" in result.output
    assert "max-pages" in result.output


@pytest.mark.parametrize(
    ("username", "pages", "message"),
    [("", 3, "username is required"), ("testuser", 0, "max_pages must be at least 1")],
)
async def test_invalid_discovery_arguments(username, pages, message):
    with pytest.raises(ValueError, match=message):
        await _relationships_impl("testuser/alpha", username, max_pages=pages)


async def test_command_populates_mcp_readable_cache(tmp_path):
    provider = StubGitProvider.with_testuser_data()
    path = tmp_path / "forkhub.db"
    async with Database(path) as db:
        result = await _relationships_impl(
            "testuser/alpha", "testuser", db=db, provider=provider
        )
        assert result["repository"] == "testuser/alpha"
        assert result["complete"] is True
        assert result["relationship_count"] > 0
        snapshot = await db.get_relationship_snapshot("testuser", "testuser/alpha")
        assert snapshot is not None
        assert snapshot["complete"] is True

    preview = PreviewQueries(path, "testuser").get_cached_relationships("testuser/alpha")
    assert preview["status"] == "cached"
    assert preview["snapshot"]["focus_repo"] == "testuser/alpha"


async def test_incomplete_attempt_reports_partial_and_preserves_complete(db, monkeypatch):
    provider = StubGitProvider.with_testuser_data()
    original_get_forks = provider.get_forks
    await _relationships_impl("testuser/alpha", "testuser", db=db, provider=provider)

    async def paginated_forks(owner, repo, *, page=1):
        result = await original_get_forks(owner, repo, page=page)
        return ForkPage(
            forks=result.forks,
            total_count=result.total_count + 1,
            page=page,
            has_next=True,
        )

    monkeypatch.setattr(provider, "get_forks", paginated_forks)
    result = await _relationships_impl(
        "testuser/alpha", "testuser", max_pages=1, db=db, provider=provider
    )
    assert result["complete"] is False
    assert result["pages_scanned"] == 1
    preserved = await db.get_relationship_snapshot("testuser", "testuser/alpha")
    assert preserved is not None
    assert preserved["complete"] is True


@pytest.mark.parametrize("complete", [True, False])
def test_cli_reports_success_and_incomplete_warning(monkeypatch, complete):
    async def fake_impl(repository, username, *, max_pages=3):
        assert repository == "testuser/alpha"
        assert username == "testuser"
        assert max_pages == 1
        return {
            "repository": repository,
            "complete": complete,
            "pages_scanned": 1,
            "relationship_count": 2,
        }

    monkeypatch.setattr(relationships_cmd, "_relationships_impl", fake_impl)
    result = CliRunner().invoke(
        app, ["relationships", "testuser/alpha", "--username", "testuser", "--max-pages", "1"]
    )
    assert result.exit_code == 0
    assert "2 relationships" in result.output
    assert f"complete={str(complete).lower()}" in result.output
    assert ("Warning: incomplete coverage" in result.output) is not complete

# ABOUTME: Local-only read-only MCP experiment for ChatGPT-first fork intelligence.
# ABOUTME: Delegates to SQLite read-only queries, with no model or GitHub API calls.

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from forkhub.mcp_preview_queries import PreviewQueries

# This personal development spike has no OAuth or tenant authorization.
# Keep it on loopback; do NOT expose through a public tunnel.
mcp = FastMCP(
    "forkhub-intelligence-preview",
    host="127.0.0.1",
    port=8765,
    stateless_http=True,
    json_response=True,
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


def _queries() -> PreviewQueries:
    """Fail fast without creating a database or initializing AI/GitHub providers."""
    path = os.environ.get("FORKHUB_MCP_DATABASE_PATH", "").strip()
    if not path:
        raise ValueError("Set FORKHUB_MCP_DATABASE_PATH to an existing SQLite file")
    return PreviewQueries(path, os.environ.get("FORKHUB_MCP_USER", ""))


@mcp.tool(annotations=READ_ONLY)
async def list_tracked_repositories(limit: int = 20) -> dict:
    """List already tracked repositories without triggering discovery."""
    return _queries().list_tracked_repositories(limit)


@mcp.tool(annotations=READ_ONLY)
async def get_cached_relationships(repository: str) -> dict:
    """Show existing upstream/downstream/sibling relationships."""
    return _queries().get_cached_relationships(repository)


@mcp.tool(annotations=READ_ONLY)
async def list_cached_signals(repository: str, min_significance: int = 5, limit: int = 20) -> dict:
    """Return existing classifications, not a fresh AI analysis."""
    return _queries().list_cached_signals(repository, min_significance, limit)


if __name__ == "__main__":
    # Validate configuration before opening the HTTP server.
    _queries()
    mcp.run(transport="streamable-http")

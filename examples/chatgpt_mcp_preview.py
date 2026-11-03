# ABOUTME: Local-only read-only MCP experiment for ChatGPT-first fork intelligence.
# ABOUTME: Exposes cached ForkHub data; no background model calls or GitHub writes.

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from forkhub import ForkHub

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


def _user() -> str:
    user = os.environ.get("FORKHUB_MCP_USER", "").strip()
    if not user:
        raise ValueError("Set FORKHUB_MCP_USER to your GitHub username")
    return user


def _repo_name(value: str) -> tuple[str, str]:
    parts = value.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError("Repository must be owner/name")
    return parts[0], parts[1]


@mcp.tool(annotations=READ_ONLY)
async def list_tracked_repositories(limit: int = 20) -> dict:
    """List ForkHub's existing tracked repositories. Does not refresh or scan."""
    _user()
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    async with ForkHub(auto_analyze=False) as hub:
        repos = await hub.get_repos()
    return {
        "repositories": [
            {
                "name": repo.full_name,
                "mode": str(repo.tracking_mode),
                "last_synced_at": (
                    repo.last_synced_at.isoformat() if repo.last_synced_at else None
                ),
                "sync_status": str(repo.sync_status),
            }
            for repo in repos[:limit]
        ],
        "returned": min(len(repos), limit),
        "truncated": len(repos) > limit,
        "source": "forkhub_cache",
    }


@mcp.tool(annotations=READ_ONLY)
async def get_cached_relationships(repository: str) -> dict:
    """Show cached upstream, downstream and sibling edges for one repository."""
    _repo_name(repository)
    user = _user()
    async with ForkHub(auto_analyze=False) as hub:
        snapshot = await hub.get_cached_relationships(user, repository)
    if snapshot is None:
        return {
            "repository": repository,
            "status": "not_scanned",
            "message": "No cached relationship snapshot. Run local discovery first.",
        }
    return {
        "repository": repository,
        "status": "cached",
        "snapshot": snapshot.model_dump(mode="json"),
        "warning": (
            "Incomplete fork coverage; results must not be presented as exhaustive."
            if not snapshot.complete
            else None
        ),
    }


@mcp.tool(annotations=READ_ONLY)
async def list_cached_signals(
    repository: str, min_significance: int = 5, limit: int = 20
) -> dict:
    """List existing classified signals, with no new model inference."""
    owner, name = _repo_name(repository)
    _user()
    if not 1 <= min_significance <= 10:
        raise ValueError("min_significance must be between 1 and 10")
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")
    async with ForkHub(auto_analyze=False) as hub:
        signals = await hub.get_signals(owner, name)
    matching = [signal for signal in signals if signal.significance >= min_significance]
    return {
        "repository": repository,
        "signals": [
            {
                "id": signal.id,
                "summary": signal.summary,
                "detail": signal.detail,
                "category": str(signal.category),
                "significance": signal.significance,
                "created_at": signal.created_at.isoformat(),
                "files_involved": signal.files_involved,
                "interpretation_is_model_generated": True,
                "verified_against_immutable_sha_evidence": False,
            }
            for signal in matching[:limit]
        ],
        "truncated": len(matching) > limit,
        "source": "forkhub_cache",
        "warning": (
            "These classifications are existing ForkHub interpretations, "
            "not independently verified claims. Commit-level provenance "
            "is not yet provided by this prototype."
        ),
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

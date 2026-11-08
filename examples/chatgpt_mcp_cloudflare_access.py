# ABOUTME: Serve read-only ForkHub tools behind Cloudflare Access Managed OAuth.
# ABOUTME: Require a verified Access application assertion on every loopback HTTP request.

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from forkhub.mcp_cloudflare_access import (
    AccessAssertionMiddleware,
    AccessAssertionVerifier,
    AccessPolicy,
    require_access_identity,
)
from forkhub.mcp_preview_queries import PreviewQueries

if TYPE_CHECKING:
    import httpx
    from starlette.applications import Starlette


@dataclass(frozen=True)
class AccessSettings:
    policy: AccessPolicy
    github_username: str
    database_path: str

    @classmethod
    def from_env(cls) -> AccessSettings:
        names = [
            "FORKHUB_ACCESS_ISSUER",
            "FORKHUB_ACCESS_AUDIENCE",
            "FORKHUB_ACCESS_EMAIL",
            "FORKHUB_PILOT_GITHUB_USERNAME",
            "FORKHUB_MCP_DATABASE_PATH",
        ]
        values = {name: os.environ.get(name, "").strip() for name in names}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise ValueError("Missing required Access pilot configuration: " + ", ".join(missing))
        path = Path(values["FORKHUB_MCP_DATABASE_PATH"]).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError("Configured ForkHub pilot database does not exist")
        return cls(
            policy=AccessPolicy(
                issuer=values["FORKHUB_ACCESS_ISSUER"],
                audience=values["FORKHUB_ACCESS_AUDIENCE"],
                email=values["FORKHUB_ACCESS_EMAIL"],
            ),
            github_username=values["FORKHUB_PILOT_GITHUB_USERNAME"],
            database_path=str(path),
        )


def create_app(
    settings: AccessSettings, *, transport: httpx.AsyncBaseTransport | None = None
) -> Starlette:
    reader = PreviewQueries(settings.database_path, settings.github_username)
    server = FastMCP(
        "forkhub-cloudflare-access-pilot",
        host="127.0.0.1",
        port=8767,
        stateless_http=True,
        json_response=True,
    )
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    @server.tool(annotations=annotations)
    async def list_tracked_repositories(limit: int = 20) -> dict:
        """List existing repositories in the pilot user's dedicated cache."""
        require_access_identity()
        return reader.list_tracked_repositories(limit)

    @server.tool(annotations=annotations)
    async def get_cached_relationships(repository: str) -> dict:
        """Read cached upstream, downstream, and sibling relationships."""
        require_access_identity()
        return reader.get_cached_relationships(repository)

    @server.tool(annotations=annotations)
    async def list_cached_signals(
        repository: str, min_significance: int = 5, limit: int = 20
    ) -> dict:
        """Return previous classifications with their provenance limitations."""
        require_access_identity()
        return reader.list_cached_signals(repository, min_significance, limit)

    app = server.streamable_http_app()
    app.add_middleware(
        AccessAssertionMiddleware,
        verifier=AccessAssertionVerifier(settings.policy, transport=transport),
    )
    return app


if __name__ == "__main__":
    uvicorn.run(create_app(AccessSettings.from_env()), host="127.0.0.1", port=8767)

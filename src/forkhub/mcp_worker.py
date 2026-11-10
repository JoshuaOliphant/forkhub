# ABOUTME: Build the authenticated read-only MCP application for Cloudflare Workers.
# ABOUTME: Create a stateless transport with an exact hostname and verified Access identity.

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import Settings as FastMCPSettings
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from forkhub.mcp_cloudflare_access import (
    AccessAssertionMiddleware,
    AccessAssertionVerifier,
    AccessPolicy,
    require_access_identity,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.applications import Starlette

    from forkhub.mcp_d1_queries import D1Queries


class JwksTransport(httpx.AsyncBaseTransport):
    def __init__(self, jwks_url: str, fetch: Callable[[str], Awaitable[tuple[int, bytes]]]) -> None:
        self._jwks_url = jwks_url
        self._fetch = fetch

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET" or str(request.url) != self._jwks_url:
            raise httpx.UnsupportedProtocol("Only the configured Access keys URL is allowed")
        try:
            async with asyncio.timeout(5):
                status, body = await self._fetch(self._jwks_url)
        except TimeoutError as error:
            raise httpx.ReadTimeout(
                "Access verification keys timed out", request=request
            ) from error
        except OSError as error:
            raise httpx.ConnectError(
                "Access verification keys unavailable", request=request
            ) from error
        return httpx.Response(status, content=body, request=request)


@dataclass(frozen=True)
class WorkerSettings:
    policy: AccessPolicy
    github_username: str
    hostname: str

    def __post_init__(self) -> None:
        if not self.github_username.strip():
            raise ValueError("ForkHub cache owner is required")
        if not re.fullmatch(r"[a-z0-9.-]+(?::[0-9]{1,5})?", self.hostname):
            raise ValueError("An exact ForkHub hostname is required")
        parsed = urlsplit("https://" + self.hostname)
        if any(
            not label or label.startswith("-") or label.endswith("-")
            for label in parsed.hostname.split(".")
        ):
            raise ValueError("An exact ForkHub hostname is required")
        if parsed.port == 0:
            raise ValueError("ForkHub hostname port must be between 1 and 65535")


def create_worker_app(
    settings: WorkerSettings,
    reader: D1Queries,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Starlette:
    FastMCPSettings.model_rebuild()
    server = FastMCP(
        "forkhub",
        log_level="WARNING",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[settings.hostname],
            allowed_origins=["https://" + settings.hostname],
        ),
    )
    annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    @server.tool(annotations=annotations)
    async def list_tracked_repositories(limit: int = 20) -> dict:
        """List existing repositories in the owner's dedicated cache."""
        require_access_identity()
        return await reader.list_tracked_repositories(limit)

    @server.tool(annotations=annotations)
    async def get_cached_relationships(repository: str) -> dict:
        """Read cached upstream, downstream, and sibling relationships."""
        require_access_identity()
        return await reader.get_cached_relationships(repository)

    @server.tool(annotations=annotations)
    async def list_cached_signals(
        repository: str, min_significance: int = 5, limit: int = 20
    ) -> dict:
        """Return SHA evidence, verification state, and model-interpretation uncertainty."""
        require_access_identity()
        return await reader.list_cached_signals(repository, min_significance, limit)

    app = server.streamable_http_app()
    app.add_middleware(
        AccessAssertionMiddleware,
        verifier=AccessAssertionVerifier(settings.policy, transport=transport),
    )
    return app

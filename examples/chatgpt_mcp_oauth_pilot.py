# ABOUTME: OAuth-protected MCP resource server for a single-user ForkHub pilot.
# ABOUTME: Requires external IdP introspection; never issues tokens or serves unauthenticated data.

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Annotated
from pathlib import Path
from urllib.parse import urlparse

import httpx
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl, TypeAdapter, UrlConstraints

from forkhub.mcp_auth import validate_introspection
from forkhub.mcp_preview_queries import PreviewQueries


@dataclass(frozen=True)
class PilotSettings:
    issuer: str
    resource: str
    introspection_url: str
    client_id: str
    client_secret: str
    subject: str
    github_username: str
    database_path: str

    @classmethod
    def from_env(cls) -> PilotSettings:
        names = {
            "issuer": "FORKHUB_OAUTH_ISSUER",
            "resource": "FORKHUB_OAUTH_RESOURCE",
            "introspection_url": "FORKHUB_OAUTH_INTROSPECTION_URL",
            "client_id": "FORKHUB_OAUTH_CLIENT_ID",
            "client_secret": "FORKHUB_OAUTH_CLIENT_SECRET",
            "subject": "FORKHUB_PILOT_SUBJECT",
            "github_username": "FORKHUB_PILOT_GITHUB_USERNAME",
            "database_path": "FORKHUB_MCP_DATABASE_PATH",
        }
        values = {key: os.environ.get(env, "").strip() for key, env in names.items()}
        missing = [names[key] for key, value in values.items() if not value]
        if missing:
            raise ValueError("Missing required OAuth pilot configuration: " + ", ".join(missing))
        for field in ("issuer", "resource", "introspection_url"):
            url = urlparse(values[field])
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError(f"{names[field]} must be an HTTPS URL")
        # Preserve the identity provider's exact issuer for token validation.
        # Pydantic may add a slash to a bare origin in MCP metadata only.
        if not values["resource"].endswith("/mcp"):
            raise ValueError("FORKHUB_OAUTH_RESOURCE must end with /mcp")
        if not Path(values["database_path"]).expanduser().is_file():
            raise FileNotFoundError("Configured ForkHub pilot database does not exist")
        return cls(**values)


class PilotAccessToken(AccessToken):
    """Retain the verified subject on SDK versions predating native subject support."""

    subject: str


class IntrospectionVerifier(TokenVerifier):
    """Verify tokens with a trusted IdP, checking resource, scope and user."""

    def __init__(
        self, settings: PilotSettings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            async with httpx.AsyncClient(timeout=5.0, transport=self._transport) as client:
                response = await client.post(
                    self._settings.introspection_url,
                    data={"token": token, "token_type_hint": "access_token"},
                    auth=(self._settings.client_id, self._settings.client_secret),
                )
                response.raise_for_status()
                claims = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not isinstance(claims, dict) or not validate_introspection(
            claims,
            issuer=self._settings.issuer,
            audience=self._settings.resource,
            subject=self._settings.subject,
        ):
            return None
        client_id = claims.get("client_id")
        if not isinstance(client_id, str) or not client_id:
            return None
        raw_scopes = claims["scope"]
        scopes = raw_scopes.split() if isinstance(raw_scopes, str) else raw_scopes
        return PilotAccessToken(
            token=token,
            client_id=client_id,
            scopes=scopes,
            resource=self._settings.resource,
            subject=self._settings.subject,
            expires_at=int(claims["exp"]),
        )


def create_server(settings: PilotSettings) -> FastMCP:
    """Construct authenticated MCP endpoints without user-controlled account selection."""
    reader = PreviewQueries(settings.database_path, settings.github_username)
    # Preserve the IdP's exact RFC 8414 issuer, including an absent trailing slash.
    # Construct the URL with explicit Pydantic 2.12+ constraints before AuthSettings.
    issuer_url = TypeAdapter(
        Annotated[AnyHttpUrl, UrlConstraints(preserve_empty_path=True)]
    ).validate_python(settings.issuer)
    mcp = FastMCP(
        "forkhub-oauth-pilot",
        host="127.0.0.1",
        port=8766,
        stateless_http=True,
        json_response=True,
        token_verifier=IntrospectionVerifier(settings),
        auth=AuthSettings(
            issuer_url=issuer_url,
            resource_server_url=AnyHttpUrl(settings.resource),
            required_scopes=["forkhub:read"],
        ),
    )
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)

    def require_user() -> None:
        access = get_access_token()
        if access is None or access.subject != settings.subject:
            raise PermissionError("Authenticated pilot user required")
        if "forkhub:read" not in access.scopes:
            raise PermissionError("Missing forkhub:read permission")

    @mcp.tool(annotations=read_only)
    async def list_tracked_repositories(limit: int = 20) -> dict:
        """List the pilot user's existing tracked repositories."""
        require_user()
        return reader.list_tracked_repositories(limit)

    @mcp.tool(annotations=read_only)
    async def get_cached_relationships(repository: str) -> dict:
        """Inspect cached fork relationships without triggering scans."""
        require_user()
        return reader.get_cached_relationships(repository)

    @mcp.tool(annotations=read_only)
    async def list_cached_signals(
        repository: str, min_significance: int = 5, limit: int = 20
    ) -> dict:
        """Inspect previous AI classifications and their known limitations."""
        require_user()
        return reader.list_cached_signals(repository, min_significance, limit)

    return mcp


if __name__ == "__main__":
    create_server(PilotSettings.from_env()).run(transport="streamable-http")

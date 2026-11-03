# ABOUTME: Inspect OAuth discovery documents before connecting ForkHub to ChatGPT.
# ABOUTME: Performs metadata-only HTTP GET requests and never handles user tokens.

from __future__ import annotations

import argparse
import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

import httpx


def validate_discovery(
    resource_metadata: Mapping[str, Any],
    authorization_metadata: Mapping[str, Any],
    *,
    resource_url: str,
    issuer: str,
) -> list[str]:
    """Return actionable compatibility problems without relaxing exact OAuth identifiers."""
    problems: list[str] = []
    if resource_metadata.get("resource") != resource_url:
        problems.append("Resource metadata must advertise the exact configured MCP resource URL.")
    servers = resource_metadata.get("authorization_servers")
    if not isinstance(servers, list) or issuer not in servers:
        problems.append("Resource metadata must list the exact authorization-server issuer.")

    if authorization_metadata.get("issuer") != issuer:
        problems.append("Authorization-server metadata issuer does not match exactly.")
    pkce = authorization_metadata.get("code_challenge_methods_supported")
    if not isinstance(pkce, list) or "S256" not in pkce:
        problems.append("Authorization server must advertise PKCE S256.")
    if not isinstance(authorization_metadata.get("authorization_endpoint"), str):
        problems.append("Authorization endpoint is missing.")
    if not isinstance(authorization_metadata.get("token_endpoint"), str):
        problems.append("Token endpoint is missing.")

    has_cimd = authorization_metadata.get("client_id_metadata_document_supported") is True
    has_dcr = isinstance(authorization_metadata.get("registration_endpoint"), str)
    if not (has_cimd or has_dcr):
        problems.append("Authorization server needs CIMD support or a DCR registration endpoint.")
    return problems


async def fetch_discovery(
    client: httpx.AsyncClient,
    *,
    resource_metadata_url: str,
    authorization_metadata_url: str,
    resource_url: str,
    issuer: str,
) -> list[str]:
    """Fetch only public OAuth metadata; report network and schema failures."""
    documents: list[dict[str, Any]] = []
    for label, url in [
        ("resource", resource_metadata_url),
        ("authorization", authorization_metadata_url),
    ]:
        if not url.startswith("https://"):
            return [f"{label} metadata URL must use HTTPS."]
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return [f"Cannot read {label} metadata: {type(exc).__name__}"]
        if not isinstance(data, dict):
            return [f"{label} metadata must be a JSON object."]
        documents.append(data)
    return validate_discovery(documents[0], documents[1], resource_url=resource_url, issuer=issuer)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Check ForkHub OAuth discovery metadata.")
    parser.add_argument("--resource", required=True, help="Exact HTTPS MCP resource URL")
    parser.add_argument("--issuer", required=True, help="Exact IdP issuer (including slash)")
    parser.add_argument("--resource-metadata", required=True, help="Full HTTPS metadata URL")
    parser.add_argument("--authorization-metadata", required=True, help="Full HTTPS metadata URL")
    args = parser.parse_args()
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        problems = await fetch_discovery(
            client,
            resource_metadata_url=args.resource_metadata,
            authorization_metadata_url=args.authorization_metadata,
            resource_url=args.resource,
            issuer=args.issuer,
        )
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}")
        return 1
    print("PASS: Discovery metadata meets basic ForkHub/ChatGPT OAuth preflight checks.")
    print("Next: test full PKCE login, consent, token validation and MCP tools in ChatGPT.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

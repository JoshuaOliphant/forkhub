# ABOUTME: Validate OAuth discovery preflight against representative MCP and IdP metadata.
# ABOUTME: Use an in-memory HTTP transport so tests never contact live identity services.

from __future__ import annotations

import httpx
import pytest

from examples.mcp_oauth_preflight import fetch_discovery, validate_discovery

RESOURCE = "https://forkhub.example.com/mcp"
ISSUER = "https://idp.example.com"
RESOURCE_DOC = {
    "resource": RESOURCE,
    "authorization_servers": [ISSUER],
    "scopes_supported": ["forkhub:read"],
}
AUTH_DOC = {
    "issuer": ISSUER,
    "authorization_endpoint": "https://idp.example.com/authorize",
    "token_endpoint": "https://idp.example.com/token",
    "code_challenge_methods_supported": ["S256"],
    "client_id_metadata_document_supported": True,
}


def test_valid_cimd_and_dcr_discovery():
    assert validate_discovery(RESOURCE_DOC, AUTH_DOC, resource_url=RESOURCE, issuer=ISSUER) == []
    dcr = {**AUTH_DOC, "client_id_metadata_document_supported": False}
    dcr["registration_endpoint"] = "https://idp.example.com/register"
    assert validate_discovery(RESOURCE_DOC, dcr, resource_url=RESOURCE, issuer=ISSUER) == []


@pytest.mark.parametrize(
    "resource,auth,message",
    [
        (
            {**RESOURCE_DOC, "resource": "https://wrong.example.com/mcp"},
            AUTH_DOC,
            "exact configured",
        ),
        ({**RESOURCE_DOC, "authorization_servers": []}, AUTH_DOC, "exact authorization"),
        (RESOURCE_DOC, {**AUTH_DOC, "issuer": ISSUER + "/"}, "issuer does not match"),
        (RESOURCE_DOC, {**AUTH_DOC, "code_challenge_methods_supported": ["plain"]}, "PKCE S256"),
        (RESOURCE_DOC, {**AUTH_DOC, "authorization_endpoint": None}, "Authorization endpoint"),
        (RESOURCE_DOC, {**AUTH_DOC, "token_endpoint": None}, "Token endpoint"),
        (
            RESOURCE_DOC,
            {**AUTH_DOC, "client_id_metadata_document_supported": False},
            "CIMD support",
        ),
    ],
)
def test_bad_metadata_explains_failure(resource, auth, message):
    assert any(
        message in error
        for error in validate_discovery(resource, auth, resource_url=RESOURCE, issuer=ISSUER)
    )


async def test_fetches_two_discovery_documents():
    urls = {
        "https://forkhub.example.com/.well-known/oauth-protected-resource/mcp": RESOURCE_DOC,
        "https://idp.example.com/.well-known/oauth-authorization-server": AUTH_DOC,
    }

    def respond(request):
        return httpx.Response(200, json=urls[str(request.url)])

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await fetch_discovery(
            client,
            resource_metadata_url=list(urls)[0],
            authorization_metadata_url=list(urls)[1],
            resource_url=RESOURCE,
            issuer=ISSUER,
        )
    assert result == []


async def test_invalid_urls_and_failure_modes():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(503))
    ) as client:
        params = {
            "resource_metadata_url": "https://forkhub.example.com/meta",
            "authorization_metadata_url": "https://idp.example.com/meta",
            "resource_url": RESOURCE,
            "issuer": ISSUER,
        }
        assert (
            "HTTPS"
            in (
                await fetch_discovery(
                    client, **{**params, "resource_metadata_url": "http://forkhub.example.com/meta"}
                )
            )[0]
        )
        assert "HTTPStatusError" in (await fetch_discovery(client, **params))[0]


async def test_bad_json_and_non_object_response():
    for response, error in [
        (httpx.Response(200, text="bad-json"), "JSONDecodeError"),
        (httpx.Response(200, json=[]), "JSON object"),
    ]:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request, response=response: response)
        ) as client:
            result = await fetch_discovery(
                client,
                resource_metadata_url="https://forkhub.example.com/meta",
                authorization_metadata_url="https://idp.example.com/meta",
                resource_url=RESOURCE,
                issuer=ISSUER,
            )
        assert error in result[0]

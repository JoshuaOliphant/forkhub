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
    "response_types_supported": ["code"],
    "grant_types_supported": ["authorization_code"],
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
        (RESOURCE_DOC, {**AUTH_DOC, "response_types_supported": ["token"]}, "response type code"),
        (RESOURCE_DOC, {**AUTH_DOC, "grant_types_supported": ["client_credentials"]}, "authorization_code grant"),
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
        error = (await fetch_discovery(client, **params))[0]
        assert "HTTP 503" in error
        assert params["resource_metadata_url"] in error


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


def test_trailing_slash_only_issuer_difference_is_an_error():
    advertised = {**RESOURCE_DOC, "authorization_servers": [ISSUER + "/"]}
    problems = validate_discovery(advertised, AUTH_DOC, resource_url=RESOURCE, issuer=ISSUER)
    assert len(problems) == 1
    assert "extra trailing slash" in problems[0]
    assert ISSUER + "/" in problems[0]
    assert "AnyHttpUrl" in problems[0]


def test_trailing_slash_issuer_is_valid_when_exactly_published():
    issuer = ISSUER + "/"
    advertised = {**RESOURCE_DOC, "authorization_servers": [issuer]}
    identity = {**AUTH_DOC, "issuer": issuer}
    assert validate_discovery(advertised, identity, resource_url=RESOURCE, issuer=issuer) == []


def test_optional_grant_types_can_be_omitted():
    identity = {key: value for key, value in AUTH_DOC.items() if key != "grant_types_supported"}
    assert validate_discovery(RESOURCE_DOC, identity, resource_url=RESOURCE, issuer=ISSUER) == []


async def test_redirect_reports_status_and_location():
    def redirect(request):
        return httpx.Response(302, headers={"Location": "https://idp.example.com/final"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(redirect)) as client:
        errors = await fetch_discovery(
            client,
            resource_metadata_url="https://forkhub.example.com/meta",
            authorization_metadata_url="https://idp.example.com/meta",
            resource_url=RESOURCE,
            issuer=ISSUER,
        )
    assert "HTTP 302" in errors[0]
    assert "https://forkhub.example.com/meta" in errors[0]
    assert "https://idp.example.com/final" in errors[0]

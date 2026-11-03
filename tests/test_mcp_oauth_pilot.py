# ABOUTME: Verify the OAuth MCP example with mocked introspection and HTTP requests.
# ABOUTME: Test secure configuration, token propagation, and fail-closed behavior.

from __future__ import annotations

import base64
from datetime import UTC, datetime

import httpx
import pytest

from examples.chatgpt_mcp_oauth_pilot import (
    IntrospectionVerifier,
    PilotSettings,
    create_server,
)

ISSUER = "https://identity.example.com/"
RESOURCE = "https://forkhub.example.com/mcp"


@pytest.fixture
def settings(tmp_path):
    db_path = tmp_path / "forkhub.db"
    db_path.touch()
    return PilotSettings(
        issuer=ISSUER,
        resource=RESOURCE,
        introspection_url="https://identity.example.com/oauth/introspect",
        client_id="pilot-service",
        client_secret="test-secret",
        subject="pilot-user",
        github_username="octocat",
        database_path=str(db_path),
    )


@pytest.fixture
def claims():
    return {
        "active": True,
        "iss": ISSUER,
        "aud": RESOURCE,
        "sub": "pilot-user",
        "exp": datetime.now(UTC).timestamp() + 3600,
        "nbf": datetime.now(UTC).timestamp() - 60,
        "scope": "openid forkhub:read profile",
        "client_id": "chatgpt-test-client",
    }


def test_settings_preserves_bare_origin_issuer(monkeypatch, settings):
    values = {
        "FORKHUB_OAUTH_ISSUER": ISSUER.rstrip("/"),
        "FORKHUB_OAUTH_RESOURCE": RESOURCE,
        "FORKHUB_OAUTH_INTROSPECTION_URL": settings.introspection_url,
        "FORKHUB_OAUTH_CLIENT_ID": settings.client_id,
        "FORKHUB_OAUTH_CLIENT_SECRET": settings.client_secret,
        "FORKHUB_PILOT_SUBJECT": settings.subject,
        "FORKHUB_PILOT_GITHUB_USERNAME": settings.github_username,
        "FORKHUB_MCP_DATABASE_PATH": settings.database_path,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert PilotSettings.from_env().issuer == ISSUER.rstrip("/")


def test_settings_rejects_missing_and_insecure_configuration(monkeypatch, settings):
    with pytest.raises(ValueError, match="Missing required"):
        PilotSettings.from_env()
    values = {
        "FORKHUB_OAUTH_ISSUER": ISSUER,
        "FORKHUB_OAUTH_RESOURCE": RESOURCE,
        "FORKHUB_OAUTH_INTROSPECTION_URL": settings.introspection_url,
        "FORKHUB_OAUTH_CLIENT_ID": settings.client_id,
        "FORKHUB_OAUTH_CLIENT_SECRET": settings.client_secret,
        "FORKHUB_PILOT_SUBJECT": settings.subject,
        "FORKHUB_PILOT_GITHUB_USERNAME": settings.github_username,
        "FORKHUB_MCP_DATABASE_PATH": settings.database_path,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("FORKHUB_OAUTH_ISSUER", "http://identity.example.com")
    with pytest.raises(ValueError, match="HTTPS"):
        PilotSettings.from_env()
    monkeypatch.setenv("FORKHUB_OAUTH_ISSUER", ISSUER)
    monkeypatch.setenv("FORKHUB_OAUTH_RESOURCE", "https://forkhub.example.com/other")
    with pytest.raises(ValueError, match="/mcp"):
        PilotSettings.from_env()
    monkeypatch.setenv("FORKHUB_OAUTH_RESOURCE", RESOURCE)
    monkeypatch.setenv("FORKHUB_MCP_DATABASE_PATH", settings.database_path + ".absent")
    with pytest.raises(FileNotFoundError):
        PilotSettings.from_env()


@pytest.mark.parametrize("status", [200, 401, 503])
async def test_introspection_errors_fail_closed(settings, status):
    def respond(request):
        if status == 200:
            return httpx.Response(200, text="not-json")
        return httpx.Response(status, json={"error": "unavailable"})

    verifier = IntrospectionVerifier(settings, transport=httpx.MockTransport(respond))
    assert await verifier.verify_token("opaque-token") is None


async def test_introspection_transport_failure_denied(settings):
    def respond(request):
        raise httpx.ConnectError("IdP unavailable")

    verifier = IntrospectionVerifier(settings, transport=httpx.MockTransport(respond))
    assert await verifier.verify_token("opaque-token") is None


async def test_introspection_preserves_scopes_and_authenticated_identity(settings, claims):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=claims)

    verifier = IntrospectionVerifier(settings, transport=httpx.MockTransport(respond))
    access = await verifier.verify_token("opaque-token")
    assert access is not None
    assert access.subject == "pilot-user"
    assert access.client_id == "chatgpt-test-client"
    assert access.scopes == ["openid", "forkhub:read", "profile"]
    assert access.resource == RESOURCE
    assert access.expires_at == int(claims["exp"])
    assert requests[0].url == settings.introspection_url
    assert requests[0].headers["authorization"] == (
        "Basic " + base64.b64encode(b"pilot-service:test-secret").decode("ascii")
    )
    assert "opaque-token" in requests[0].content.decode()


async def test_scope_list_from_introspection(settings, claims):
    claims["scope"] = ["forkhub:read", "another-scope"]
    verifier = IntrospectionVerifier(
        settings, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=claims))
    )
    access = await verifier.verify_token("opaque-token")
    assert access is not None
    assert access.scopes == ["forkhub:read", "another-scope"]


async def test_token_without_client_id_is_denied(settings, claims):
    del claims["client_id"]
    verifier = IntrospectionVerifier(
        settings, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=claims))
    )
    assert await verifier.verify_token("opaque-token") is None


async def test_wrong_issuer_and_future_not_before_are_denied(settings, claims):
    def respond(request):
        return httpx.Response(200, json=claims)

    verifier = IntrospectionVerifier(settings, transport=httpx.MockTransport(respond))
    claims["iss"] = "https://another.example.com/"
    assert await verifier.verify_token("opaque-token") is None
    claims["iss"] = ISSUER
    claims["nbf"] = datetime.now(UTC).timestamp() + 3600
    assert await verifier.verify_token("opaque-token") is None


async def test_http_without_token_is_rejected(settings):
    mcp = create_server(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp.streamable_http_app()),
        base_url="http://localhost:8766",
    ) as client:
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert response.status_code == 401


async def test_introspection_accepts_exact_bare_origin_issuer(settings, claims):
    from dataclasses import replace

    bare = ISSUER.rstrip("/")
    pilot = replace(settings, issuer=bare)
    claims["iss"] = bare
    verifier = IntrospectionVerifier(
        pilot,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=claims)),
    )
    access = await verifier.verify_token("opaque-token")
    assert access is not None
    assert access.subject == "pilot-user"


async def test_tool_handler_rejects_wrong_subject_and_missing_scope(settings, monkeypatch):
    import examples.chatgpt_mcp_oauth_pilot as pilot

    server = create_server(settings)
    tool = server._tool_manager.get_tool("list_tracked_repositories")
    assert tool is not None

    for subject, scopes in [
        ("another-user", ["forkhub:read"]),
        ("pilot-user", ["profile"]),
    ]:
        token = pilot.PilotAccessToken(
            token="opaque-token",
            client_id="chatgpt-test-client",
            scopes=scopes,
            subject=subject,
        )
        monkeypatch.setattr(pilot, "get_access_token", lambda: token)
        with pytest.raises(PermissionError):
            await tool.fn(limit=1)

    monkeypatch.setattr(pilot, "get_access_token", lambda: None)
    with pytest.raises(PermissionError):
        await tool.fn(limit=1)

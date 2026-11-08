# ABOUTME: Verify signed Cloudflare Access assertions and HTTP authorization for MCP.
# ABOUTME: Exercise real RSA signatures, denied identities, and read-only synthetic tool calls.

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from examples.chatgpt_mcp_cloudflare_access import AccessSettings, create_app
from examples.seed_mcp_demo import DEMO_REPO, DEMO_USER, seed
from forkhub.mcp_cloudflare_access import (
    AccessAssertionMiddleware,
    AccessAssertionVerifier,
    AccessIdentity,
    AccessPolicy,
    require_access_identity,
    validate_access_assertion,
)


@pytest.fixture
def access_policy():
    return AccessPolicy(
        issuer="https://forkhub-test.cloudflareaccess.com",
        audience="forkhub-test-audience",
        email="pilot@example.com",
    )


@pytest.fixture(scope="module")
def signing_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public.update(kid="test-key", use="sig", alg="RS256")
    return private_key, {"keys": [public]}


@pytest.fixture
def access_claims(access_policy):
    now = datetime.now(UTC).timestamp()
    return {
        "iss": access_policy.issuer,
        "aud": [access_policy.audience],
        "sub": "cloudflare-pilot-user",
        "email": access_policy.email,
        "type": "app",
        "exp": now + 3600,
        "nbf": now - 60,
    }


@pytest.fixture
def sign_assertion(signing_keys, access_claims):
    def sign(claims=None, headers=None):
        return jwt.encode(
            access_claims if claims is None else claims,
            signing_keys[0],
            algorithm="RS256",
            headers={"kid": "test-key"} if headers is None else headers,
        )

    return sign


@pytest.fixture
async def access_settings(tmp_path, access_policy):
    path = tmp_path / "synthetic.db"
    await seed(path)
    return AccessSettings(policy=access_policy, github_username=DEMO_USER, database_path=str(path))


@pytest.mark.parametrize(
    "issuer",
    [
        "http://forkhub.cloudflareaccess.com",
        "https://forkhub.cloudflareaccess.com/",
        "https://forkhub.cloudflareaccess.com.evil.example",
        "https://user@forkhub.cloudflareaccess.com",
        "https://forkhub.cloudflareaccess.com:8443",
        "https://forkhub.cloudflareaccess.com/other",
        "https://.cloudflareaccess.com",
    ],
)
def test_policy_rejects_issuers_outside_exact_team_origin(access_policy, issuer):
    with pytest.raises(ValueError, match="issuer"):
        replace(access_policy, issuer=issuer)


@pytest.mark.parametrize("audience", ["", " ", " padded"])
def test_policy_requires_exact_application_audience(access_policy, audience):
    with pytest.raises(ValueError, match="audience"):
        replace(access_policy, audience=audience)


@pytest.mark.parametrize("email", ["", "user", "user@", "user @example.com"])
def test_policy_requires_exact_pilot_email(access_policy, email):
    with pytest.raises(ValueError, match="email"):
        replace(access_policy, email=email)


def test_signed_assertion_identifies_only_allowed_user(access_policy, signing_keys, sign_assertion):
    assert validate_access_assertion(
        sign_assertion(), signing_keys[1], access_policy
    ) == AccessIdentity(subject="cloudflare-pilot-user", email=access_policy.email)


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("iss", "https://other.cloudflareaccess.com"),
        ("aud", "another-application"),
        ("email", "another@example.com"),
        ("email", "PILOT@example.com"),
        ("sub", ""),
        ("sub", " "),
        ("sub", 123),
        ("type", "org"),
        ("exp", 1),
        ("exp", True),
        ("exp", "9999999999"),
        ("exp", float("inf")),
        ("nbf", 9999999999),
        ("nbf", False),
        ("nbf", "1"),
        ("nbf", float("-inf")),
        ("iat", True),
        ("iat", "1"),
        ("iat", float("inf")),
    ],
)
def test_signed_assertion_rejects_invalid_grants(
    access_policy, signing_keys, access_claims, sign_assertion, claim, value
):
    access_claims[claim] = value
    assert validate_access_assertion(sign_assertion(), signing_keys[1], access_policy) is None


@pytest.mark.parametrize("claim", ["iss", "aud", "sub", "email", "exp", "type"])
def test_signed_assertion_requires_identity_and_expiry(
    access_policy, signing_keys, access_claims, sign_assertion, claim
):
    del access_claims[claim]
    assert validate_access_assertion(sign_assertion(), signing_keys[1], access_policy) is None


@pytest.mark.parametrize("headers", [{}, {"kid": "unknown"}, {"kid": ""}])
def test_assertion_requires_a_known_key(access_policy, signing_keys, sign_assertion, headers):
    assert (
        validate_access_assertion(sign_assertion(headers=headers), signing_keys[1], access_policy)
        is None
    )


@pytest.mark.parametrize(
    "jwks",
    [
        None,
        [],
        {},
        {"keys": {}},
        {"keys": [None]},
        {"keys": [{"kid": "test-key"}]},
        {"keys": [{"kid": "test-key", "kty": "RSA", "n": "x", "e": "AQAB"}]},
        {"keys": [{"kid": "test-key"}, {"kid": "test-key"}]},
    ],
)
def test_malformed_jwks_fail_closed(access_policy, sign_assertion, jwks):
    assert validate_access_assertion(sign_assertion(), jwks, access_policy) is None


def test_forged_and_unsigned_assertions_fail_closed(
    access_policy, signing_keys, access_claims, sign_assertion
):
    token = sign_assertion()
    header, payload, signature = token.split(".")
    forged = ".".join([header, payload, ("A" if signature[0] != "A" else "B") + signature[1:]])
    unsigned = jwt.encode(access_claims, key="", algorithm="none", headers={"kid": "test-key"})
    for assertion in ["not-a-jwt", forged, unsigned]:
        assert validate_access_assertion(assertion, signing_keys[1], access_policy) is None


async def test_verifier_fetches_only_trusted_jwks(access_policy, signing_keys, sign_assertion):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=signing_keys[1])

    verifier = AccessAssertionVerifier(access_policy, transport=httpx.MockTransport(respond))
    assertion = sign_assertion(headers={"kid": "test-key", "jku": "https://evil.example/keys"})
    assert await verifier.verify(assertion) is not None
    assert len(requests) == 1
    assert str(requests[0].url) == access_policy.issuer + "/cdn-cgi/access/certs"
    assert "authorization" not in requests[0].headers


@pytest.mark.parametrize("status", [200, 302, 503])
async def test_unavailable_jwks_and_redirects_deny_access(access_policy, sign_assertion, status):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, text="not-json", headers={"Location": "https://evil.example"})

    verifier = AccessAssertionVerifier(access_policy, transport=httpx.MockTransport(respond))
    assert await verifier.verify(sign_assertion()) is None
    assert len(requests) == 1


async def test_jwks_network_failure_denies_access(access_policy, sign_assertion):
    def respond(request):
        raise httpx.ConnectError("unreachable")

    verifier = AccessAssertionVerifier(access_policy, transport=httpx.MockTransport(respond))
    assert await verifier.verify(sign_assertion()) is None


async def test_http_tools_require_signed_user_and_leave_database_unchanged(
    access_settings, signing_keys, sign_assertion, access_claims, caplog
):
    path = Path(access_settings.database_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    app = create_app(
        access_settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=signing_keys[1])),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8767"
        ) as client,
    ):
        calls = [
            ("list_tracked_repositories", {}, DEMO_REPO),
            ("get_cached_relationships", {"repository": DEMO_REPO}, "forkhub-demo/sample-fork"),
            (
                "list_cached_signals",
                {"repository": DEMO_REPO},
                "Synthetic example: add retry handling",
            ),
        ]
        headers = {
            "Accept": "application/json, text/event-stream",
            "Cf-Access-Jwt-Assertion": sign_assertion(),
        }
        for index, (name, arguments, expected) in enumerate(calls, start=1):
            response = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": index,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
            )
            assert response.status_code == 200
            assert expected in response.text
            assert not response.json()["result"].get("isError", False)

        listed = await client.post(
            "/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 4, "method": "tools/list"}
        )
        assert len(listed.json()["result"]["tools"]) == 3
        assert all(t["annotations"]["readOnlyHint"] for t in listed.json()["result"]["tools"])

        unauthenticated_headers = [
            {},
            {"Authorization": "Bearer " + sign_assertion()},
            {"Cf-Access-Authenticated-User-Email": access_settings.policy.email},
            {"Cookie": "CF_Authorization=" + sign_assertion()},
            {"Cf-Access-Jwt-Assertion": "forged"},
            {"Cf-Access-Jwt-Assertion": ""},
            [("Cf-Access-Jwt-Assertion", sign_assertion())] * 2,
        ]
        access_claims["email"] = "unapproved@example.com"
        unauthenticated_headers.append({"Cf-Access-Jwt-Assertion": sign_assertion()})
        for extra_headers in unauthenticated_headers:
            response = await client.post(
                "/mcp",
                headers=extra_headers,
                json={"jsonrpc": "2.0", "id": 5, "method": "tools/list"},
            )
            assert response.status_code == 401
            assert response.json() == {"error": "verified_access_user_required"}
            assert response.headers["cache-control"] == "no-store"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert not [record for record in caplog.records if record.levelno >= 30]
    with pytest.raises(PermissionError):
        require_access_identity()


async def test_middleware_preserves_lifespan_and_rejects_websockets(access_policy):
    events = []

    async def app(scope, receive, send):
        events.append(scope["type"])

    async def receive():
        return {}

    async def send(event):
        events.append(event)

    middleware = AccessAssertionMiddleware(app, AccessAssertionVerifier(access_policy))
    await middleware({"type": "lifespan"}, receive, send)
    await middleware({"type": "websocket"}, receive, send)
    assert events == ["lifespan", {"type": "websocket.close", "code": 1008}]


def test_settings_load_exact_policy_and_existing_database(access_settings, monkeypatch):
    values = {
        "FORKHUB_ACCESS_ISSUER": access_settings.policy.issuer,
        "FORKHUB_ACCESS_AUDIENCE": access_settings.policy.audience,
        "FORKHUB_ACCESS_EMAIL": access_settings.policy.email,
        "FORKHUB_PILOT_GITHUB_USERNAME": access_settings.github_username,
        "FORKHUB_MCP_DATABASE_PATH": access_settings.database_path,
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert AccessSettings.from_env() == access_settings
    monkeypatch.setenv("FORKHUB_MCP_DATABASE_PATH", access_settings.database_path + ".absent")
    with pytest.raises(FileNotFoundError, match="database"):
        AccessSettings.from_env()
    monkeypatch.delenv("FORKHUB_ACCESS_ISSUER")
    with pytest.raises(ValueError, match="FORKHUB_ACCESS_ISSUER"):
        AccessSettings.from_env()

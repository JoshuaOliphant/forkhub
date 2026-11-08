# ABOUTME: Verify the Workers MCP factory against signed identities and real SQLite queries.
# ABOUTME: Exercise fresh request lifespans, all read-only tools, and exact host enforcement.

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import replace

import httpx
import pytest

from examples.seed_mcp_demo import DEMO_REPO
from forkhub.mcp_cloudflare_access import AccessAssertionVerifier, require_access_identity
from forkhub.mcp_d1_queries import D1Queries
from forkhub.mcp_preview_queries import PreviewQueries
from forkhub.mcp_worker import JwksTransport, WorkerSettings, create_worker_app


@pytest.fixture
def worker_settings(access_settings):
    return WorkerSettings(
        policy=access_settings.policy,
        github_username=access_settings.github_username,
        hostname="mcp.forkhub.test",
    )


@pytest.fixture
def d1_reader(access_settings):
    async def query(sql, parameters):
        with closing(sqlite3.connect(access_settings.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql, parameters).fetchall()]

    return D1Queries(query, access_settings.github_username)


@pytest.mark.parametrize("username", ["", " "])
def test_worker_requires_cache_owner(worker_settings, username):
    with pytest.raises(ValueError, match="owner"):
        replace(worker_settings, github_username=username)


@pytest.mark.parametrize(
    "hostname",
    [
        "",
        "https://mcp.forkhub.test",
        "*.forkhub.test",
        "mcp.forkhub.test/",
        "user@mcp.forkhub.test",
        "mcp..forkhub.test",
        "-mcp.forkhub.test",
        "mcp.forkhub.test-",
        "mcp.forkhub.test:0",
        "mcp.forkhub.test:65536",
    ],
)
def test_worker_requires_exact_hostname(worker_settings, hostname):
    with pytest.raises(ValueError):
        replace(worker_settings, hostname=hostname)


async def test_worker_transport_fetches_fixed_keys_without_forwarding_headers(
    access_policy, signing_keys, sign_assertion
):
    urls = []

    async def fetch(url):
        urls.append(url)
        return 200, json.dumps(signing_keys[1]).encode()

    verifier = AccessAssertionVerifier(
        access_policy, transport=JwksTransport(access_policy.jwks_url, fetch)
    )
    assert await verifier.verify(sign_assertion()) is not None
    assert urls == [access_policy.jwks_url]


@pytest.mark.parametrize(
    ("status", "body"), [(200, b"not-json"), (302, b"redirect"), (503, b"unavailable")]
)
async def test_worker_transport_denies_unusable_keys(access_policy, sign_assertion, status, body):
    async def fetch(url):
        return status, body

    verifier = AccessAssertionVerifier(
        access_policy, transport=JwksTransport(access_policy.jwks_url, fetch)
    )
    assert await verifier.verify(sign_assertion()) is None


@pytest.mark.parametrize("error", [TimeoutError, OSError])
async def test_worker_transport_denies_network_failure(access_policy, sign_assertion, error):
    async def fetch(url):
        raise error("unreachable")

    verifier = AccessAssertionVerifier(
        access_policy, transport=JwksTransport(access_policy.jwks_url, fetch)
    )
    assert await verifier.verify(sign_assertion()) is None


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("POST", "https://forkhub-test.cloudflareaccess.com/cdn-cgi/access/certs"),
        ("GET", "https://untrusted.example/keys"),
    ],
)
async def test_worker_transport_rejects_other_requests(access_policy, method, url):
    urls = []

    async def fetch(url):
        urls.append(url)
        return 200, b"{}"

    transport = JwksTransport(access_policy.jwks_url, fetch)
    with pytest.raises(httpx.UnsupportedProtocol, match="configured Access"):
        await transport.handle_async_request(httpx.Request(method, url))
    assert urls == []


async def test_fresh_worker_lifespans_keep_all_three_tool_contracts(
    worker_settings, access_settings, d1_reader, signing_keys, sign_assertion, caplog
):
    local = PreviewQueries(access_settings.database_path, access_settings.github_username)
    calls = [
        ("list_tracked_repositories", {}, local.list_tracked_repositories()),
        (
            "get_cached_relationships",
            {"repository": DEMO_REPO},
            local.get_cached_relationships(DEMO_REPO),
        ),
        (
            "list_cached_signals",
            {"repository": DEMO_REPO},
            local.list_cached_signals(DEMO_REPO),
        ),
    ]
    headers = {
        "Accept": "application/json, text/event-stream",
        "Cf-Access-Jwt-Assertion": sign_assertion(),
    }
    for name, arguments, expected in calls:
        app = create_worker_app(
            worker_settings,
            d1_reader,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=signing_keys[1])
            ),
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app), base_url="https://" + worker_settings.hostname
            ) as client,
        ):
            response = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
            )
            assert response.status_code == 200
            assert json.loads(response.json()["result"]["content"][0]["text"]) == expected
    assert not [record for record in caplog.records if record.levelno >= 30]
    with pytest.raises(PermissionError):
        require_access_identity()


async def test_worker_rejects_missing_identity_and_unapproved_host_or_origin(
    worker_settings, d1_reader, signing_keys, sign_assertion, caplog
):
    app = create_worker_app(
        worker_settings,
        d1_reader,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=signing_keys[1])),
    )
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    accept = {"Accept": "application/json, text/event-stream"}
    signed = {**accept, "Cf-Access-Jwt-Assertion": sign_assertion()}
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="https://" + worker_settings.hostname
        ) as client,
    ):
        assert (await client.post("/mcp", headers=accept, json=request)).status_code == 401
        listed = await client.post("/mcp", headers=signed, json=request)
        assert listed.status_code == 200
        tools = listed.json()["result"]["tools"]
        assert len(tools) == 3
        assert all(tool["annotations"]["readOnlyHint"] for tool in tools)
        assert all(not tool["annotations"]["destructiveHint"] for tool in tools)
        assert (
            await client.post(
                "/mcp", headers={**signed, "Host": "preview.workers.dev"}, json=request
            )
        ).status_code == 421
        assert (
            await client.post(
                "/mcp", headers={**signed, "Origin": "https://untrusted.example"}, json=request
            )
        ).status_code == 403
    warnings = [record.message for record in caplog.records if record.levelno >= 30]
    assert warnings == [
        "Invalid Host header: preview.workers.dev",
        "Invalid Origin header: https://untrusted.example",
    ]

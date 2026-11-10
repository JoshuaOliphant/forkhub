# ABOUTME: Checks a real public commit through disposable capture and both read interfaces.
# ABOUTME: Exercises immutable evidence without touching operational caches or hosted services.

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from contextlib import closing

import httpx
import pytest

from forkhub import ForkHub
from forkhub.agent.tools import create_tools
from forkhub.config import ForkHubSettings
from forkhub.database import Database
from forkhub.mcp_cache_export import export_cache
from forkhub.mcp_d1_queries import D1Queries
from forkhub.mcp_preview_queries import PreviewQueries
from forkhub.mcp_worker import WorkerSettings, create_worker_app
from forkhub.web.app import create_app
from forkhub.web.data import build_explore_data
from tests.stubs import make_fork, make_tracked_repo


@pytest.mark.integration
async def test_real_commit_signal_matches_website_export_and_authenticated_mcp(
    tmp_path,
    embedding_provider,
    backend,
    access_policy,
    signing_keys,
    sign_assertion,
    caplog,
    github_acceptance_provider,
):
    sha = "0795ef197cca04f6a8e7d50d10ed4dc71bd1a0cc"
    filename = "tests/chatgpt-auth.test.ts"
    with caplog.at_level(logging.WARNING):
        provider = github_acceptance_provider()
    if caplog.records:
        assert len(caplog.records) == 1
        assert "unauthenticated access" in caplog.records[0].message
    caplog.clear()
    fork = await provider.get_repo("JoshuaOliphant", "learnharness")
    assert fork.parent_full_name == "amosblomqvist/learnharness"
    upstream = await provider.get_repo(*fork.parent_full_name.split("/"))
    source = tmp_path / "source.db"
    async with Database(source) as database:
        tracked = make_tracked_repo(
            github_id=upstream.github_id,
            owner=upstream.owner,
            name=upstream.name,
            full_name=upstream.full_name,
            default_branch=upstream.default_branch,
        )
        await database.insert_tracked_repo(tracked)
        await database.insert_fork(
            make_fork(
                tracked["id"],
                github_id=fork.github_id,
                owner=fork.owner,
                full_name=fork.full_name,
                default_branch=fork.default_branch,
                head_sha=sha,
            )
        )
        tool = next(
            t
            for t in create_tools(database, provider, embedding_provider)
            if t.name == "store_signal"
        )
        stored = await tool.handler(
            {
                "fork_full_name": fork.full_name,
                "category": "fix",
                "significance": 7,
                "summary": "Acceptance interpretation: repeated sign-in test waits for completion",
                "detail": "Manually supplied interpretation; no model analysis was run.",
                "commit_shas": [sha],
                "files_involved": [filename],
            }
        )
        assert not stored.get("is_error"), stored
        evidence = json.loads(stored["content"][0]["text"])["evidence"]
        assert evidence["verification_state"] == "verified"
        assert evidence["source_repository"] == fork.full_name
        assert evidence["commit_shas"] == [sha]
        assert evidence["files"] == [filename]
        assert evidence["changes"][0]["patch"]
        hub = ForkHub(
            settings=ForkHubSettings(),
            db=database,
            git_provider=provider,
            embedding_provider=embedding_provider,
            notification_backends=[backend],
            auto_analyze=False,
        )
        expected = (await build_explore_data(hub, upstream.owner, upstream.name))["signals"]
        assert expected == PreviewQueries(source, fork.owner).list_cached_signals(
            upstream.full_name
        )
        assert (await hub.get_signals(upstream.owner, upstream.name))[0].evidence.commit_shas == [
            sha
        ]
        web = create_app(hub)
        web.state.hub = hub
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(web), base_url="http://local"
        ) as client:
            response = await client.get("/" + upstream.full_name)
            assert response.status_code == 200
            assert f"https://github.com/{fork.full_name}/commit/{sha}" in response.text
            assert "Inspect source evidence · verified" in response.text
            assert "not independently verified" in response.text
            for stylesheet in ("forkhub.css", "relationships.css"):
                css = await client.get("/static/css/" + stylesheet)
                assert css.status_code == 200 and "text/css" in css.headers["content-type"]
                assert len(css.content) > 100
    before = hashlib.sha256(source.read_bytes()).digest()
    sql = tmp_path / "export.sql"
    counts = export_cache(source, sql, fork.owner, confirm_single_user=True)
    assert counts["signals"] == 1
    imported = tmp_path / "imported.db"
    with closing(sqlite3.connect(imported)) as connection:
        connection.executescript(sql.read_text())
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    imported_before = hashlib.sha256(imported.read_bytes()).digest()
    assert PreviewQueries(imported, fork.owner).list_cached_signals(upstream.full_name) == expected

    async def query(sql, parameters):
        with closing(sqlite3.connect(imported.as_uri() + "?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            return [dict(row) for row in connection.execute(sql, parameters)]

    reader = D1Queries(query, fork.owner)
    assert await reader.list_cached_signals(upstream.full_name) == expected
    settings = WorkerSettings(
        policy=access_policy, github_username=fork.owner, hostname="mcp.forkhub.test"
    )
    app = create_worker_app(
        settings,
        reader,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=signing_keys[1])),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="https://mcp.forkhub.test"
        ) as client,
    ):
        response = await client.post(
            "/mcp",
            headers={
                "Accept": "application/json, text/event-stream",
                "Cf-Access-Jwt-Assertion": sign_assertion(),
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "list_cached_signals",
                    "arguments": {"repository": upstream.full_name},
                },
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert not result.get("isError"), result
        assert json.loads(result["content"][0]["text"]) == expected
    assert hashlib.sha256(source.read_bytes()).digest() == before
    assert hashlib.sha256(imported.read_bytes()).digest() == imported_before
    assert not [record for record in caplog.records if record.levelno >= logging.WARNING]

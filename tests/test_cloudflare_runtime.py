# ABOUTME: Verify the authenticated three-tool contract in the real local Workers and D1 runtimes.
# ABOUTME: Exercise signed Access assertions against synthetic data without changing storage.

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from examples.seed_mcp_demo import DEMO_REPO
from forkhub.mcp_cache_export import export_cache
from forkhub.mcp_preview_queries import PreviewQueries


@pytest.mark.integration
async def test_local_workers_and_d1_preserve_authenticated_cache_contract(
    tmp_path, access_settings, signing_keys, sign_assertion, access_claims
):
    root = Path(__file__).resolve().parents[1]
    checkout = tmp_path / "checkout"
    project = checkout / "deploy/cloudflare"
    shutil.copytree(root / "src/forkhub", checkout / "src/forkhub")
    shutil.copytree(
        root / "deploy/cloudflare",
        project,
        ignore=shutil.ignore_patterns(
            ".venv",
            ".venv-workers",
            ".wrangler",
            "node_modules",
            "python_modules",
            "dist",
            "__pycache__",
            ".dev.vars*",
            ".env*",
        ),
    )
    shutil.copyfile(root / "tests/cloudflare/entry.py", project / "src/integration_worker.py")
    source = Path(access_settings.database_path)
    source_before = hashlib.sha256(source.read_bytes()).digest()
    sql = tmp_path / "synthetic.sql"
    export_cache(source, sql, access_settings.github_username, confirm_single_user=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    hostname = f"127.0.0.1:{port}"
    config = json.loads((project / "wrangler.jsonc").read_text())
    config.update(
        name="forkhub-runtime-integration",
        main="src/integration_worker.py",
        routes=[],
        workers_dev=False,
        preview_urls=False,
        vars={
            "FORKHUB_ACCESS_ISSUER": access_settings.policy.issuer,
            "FORKHUB_ACCESS_AUDIENCE": access_settings.policy.audience,
            "FORKHUB_ACCESS_EMAIL": access_settings.policy.email,
            "FORKHUB_GITHUB_USERNAME": access_settings.github_username,
            "FORKHUB_HOSTNAME": hostname,
            "TEST_JWKS_JSON": json.dumps(signing_keys[1]),
        },
    )
    config["d1_databases"][0]["database_id"] = "00000000-0000-0000-0000-000000000001"
    (project / "wrangler.jsonc").write_text(json.dumps(config))
    environment = {**os.environ, "WRANGLER_SEND_METRICS": "false"}
    installed = subprocess.run(
        ["npm", "ci"],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    state = tmp_path / "state"
    imported = subprocess.run(
        [
            "npx",
            "--yes",
            "wrangler",
            "d1",
            "execute",
            "forkhub-cache",
            "--local",
            "--persist-to",
            str(state),
            "--file",
            str(sql),
        ],
        cwd=project,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr
    databases = sorted(state.rglob("*.sqlite"))
    assert databases, "The local D1 import did not create a SQLite database"
    before = {path: hashlib.sha256(path.read_bytes()).digest() for path in databases}
    log = tmp_path / "workers.log"
    with log.open("w") as output:
        process = subprocess.Popen(
            [
                "uv",
                "run",
                "--frozen",
                "pywrangler",
                "dev",
                "--local",
                "--ip",
                "127.0.0.1",
                "--port",
                str(port),
                "--persist-to",
                str(state),
            ],
            cwd=project,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            async with httpx.AsyncClient(base_url="http://" + hostname, timeout=15) as client:
                request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
                deadline = time.monotonic() + 180
                while True:
                    assert process.poll() is None, log.read_text()
                    try:
                        response = await client.post("/mcp", json=request)
                    except httpx.TransportError:
                        response = None
                    if response is not None:
                        assert response.status_code == 401, response.text + "\n" + log.read_text()
                        assert response.json() == {"error": "verified_access_user_required"}
                        break
                    assert time.monotonic() < deadline, log.read_text()
                    await asyncio.sleep(0.25)

                headers = {
                    "Accept": "application/json, text/event-stream",
                    "Cf-Access-Jwt-Assertion": sign_assertion(),
                }
                initialized = await client.post(
                    "/mcp",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-11-25",
                            "capabilities": {},
                            "clientInfo": {"name": "forkhub-runtime-test", "version": "1"},
                        },
                    },
                )
                assert initialized.status_code == 200, initialized.text
                assert initialized.json()["result"]["serverInfo"]["name"] == "forkhub"
                listed = await client.post("/mcp", headers=headers, json=request)
                assert listed.status_code == 200, listed.text
                assert {tool["name"] for tool in listed.json()["result"]["tools"]} == {
                    "list_tracked_repositories",
                    "get_cached_relationships",
                    "list_cached_signals",
                }
                reader = PreviewQueries(source, access_settings.github_username)
                calls = [
                    ("list_tracked_repositories", {}, reader.list_tracked_repositories()),
                    (
                        "get_cached_relationships",
                        {"repository": DEMO_REPO},
                        reader.get_cached_relationships(DEMO_REPO),
                    ),
                    (
                        "list_cached_signals",
                        {"repository": DEMO_REPO},
                        reader.list_cached_signals(DEMO_REPO),
                    ),
                ]
                responses = []
                for index, (name, arguments, expected) in enumerate(calls, start=2):
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
                    assert response.status_code == 200, response.text
                    result = response.json()["result"]
                    responses.append(
                        {"tool": name, "status": response.status_code, "result": result}
                    )
                    (tmp_path / "tool-responses.json").write_text(json.dumps(responses, indent=2))
                    assert not result.get("isError", False), result
                    assert json.loads(result["content"][0]["text"]) == expected

                wrong_email = {**access_claims, "email": "unapproved@example.com"}
                for credentials in [
                    {},
                    {"Cf-Access-Jwt-Assertion": "forged"},
                    {"Cf-Access-Jwt-Assertion": sign_assertion(wrong_email)},
                ]:
                    response = await client.post(
                        "/mcp", headers={"Accept": headers["Accept"], **credentials}, json=request
                    )
                    assert response.status_code == 401, response.text
                    assert response.json() == {"error": "verified_access_user_required"}
                    assert response.headers["cache-control"] == "no-store"
                assert {
                    path: hashlib.sha256(path.read_bytes()).digest() for path in databases
                } == before
                assert hashlib.sha256(source.read_bytes()).digest() == source_before
        finally:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                assert process.poll() is not None
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=15)
    runtime_log = re.sub(r"\x1b\[[0-9;]*m", "", log.read_text())
    assert "Traceback" not in runtime_log, runtime_log
    assert "[ERROR]" not in runtime_log, runtime_log
    assert "[WARNING]" not in runtime_log, runtime_log

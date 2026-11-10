# ABOUTME: Tests for the Explore FastAPI app — routes, redirects, 404, lifespan.
# ABOUTME: Drives the ASGI app via httpx in the test event loop (shared db connection).

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import TYPE_CHECKING

import httpx
import pytest

from forkhub import ForkHub
from forkhub.config import ForkHubSettings
from forkhub.web.app import create_app
from tests.stubs import (
    StubEmbeddingProvider,
    StubGitProvider,
    StubNotificationBackend,
    make_fork,
    make_signal,
    make_tracked_repo,
)

if TYPE_CHECKING:
    from forkhub.database import Database


@pytest.fixture
def hub(
    db: Database,
    provider: StubGitProvider,
    backend: StubNotificationBackend,
    embedding_provider: StubEmbeddingProvider,
) -> ForkHub:
    return ForkHub(
        settings=ForkHubSettings(),
        git_provider=provider,
        notification_backends=[backend],
        embedding_provider=embedding_provider,
        db=db,
    )


async def _seed_repo(db: Database) -> dict:
    repo = make_tracked_repo()  # torvalds/linux
    await db.insert_tracked_repo(repo)
    fork = make_fork(repo["id"])
    await db.insert_fork(fork)
    return repo


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


class TestExploreApp:
    async def test_explore_route_returns_page_with_data(self, hub: ForkHub, db: Database):
        await _seed_repo(db)
        app = create_app(hub)
        app.state.hub = hub
        async with _client(app) as client:
            resp = await client.get("/torvalds/linux")
        assert resp.status_code == 200
        assert 'id="forkhub-data"' not in resp.text
        assert "torvalds/linux" in resp.text  # repo name rendered in the topbar
        assert "Not scanned yet" in resp.text
        assert "forkhub relationships torvalds/linux --username torvalds" in resp.text

    async def test_explore_shows_relationships_and_coverage_warning(
        self, hub: ForkHub, db: Database
    ):
        await _seed_repo(db)
        await db.save_relationship_snapshot(
            "torvalds",
            {
                "focus_github_id": 123456,
                "focus_repo": "torvalds/linux",
                "upstream_repo": None,
                "complete": False,
                "pages_scanned": 1,
                "relationships": [
                    {
                        "direction": "downstream",
                        "github_id": 789012,
                        "source_repo": "someone/linux",
                        "target_repo": "torvalds/linux",
                        "is_user_repository": False,
                    }
                ],
            },
        )
        app = create_app(hub)
        app.state.hub = hub
        async with _client(app) as client:
            resp = await client.get("/torvalds/linux")
        assert resp.status_code == 200
        assert "Coverage warning" in resp.text
        assert "someone/linux" in resp.text
        assert "Incomplete fork coverage" in resp.text

    async def test_not_scanned_watched_repo_uses_configured_username(
        self, hub: ForkHub, db: Database
    ):
        await _seed_repo(db)
        hub._settings.github.username = "watcher"
        app = create_app(hub)
        app.state.hub = hub
        async with _client(app) as client:
            resp = await client.get("/torvalds/linux")
        assert resp.status_code == 200
        assert "forkhub relationships torvalds/linux --username watcher" in resp.text
        assert "forkhub relationships torvalds/linux --username torvalds" not in resp.text

    async def test_explore_untracked_returns_404(self, hub: ForkHub):
        app = create_app(hub)
        app.state.hub = hub
        async with _client(app) as client:
            resp = await client.get("/no/body")
        assert resp.status_code == 404

    async def test_index_redirects_to_first_repo(self, hub: ForkHub, db: Database):
        await _seed_repo(db)
        app = create_app(hub)
        app.state.hub = hub
        async with _client(app) as client:
            resp = await client.get("/", follow_redirects=False)
        assert resp.status_code == 307
        assert resp.headers["location"] == "/torvalds/linux"

    async def test_index_empty_state_when_no_repos(self, hub: ForkHub):
        app = create_app(hub)
        app.state.hub = hub
        async with _client(app) as client:
            resp = await client.get("/")
        assert resp.status_code == 200
        assert "No repos tracked yet" in resp.text
        assert "No repository selected." in resp.text
        assert "forkhub relationships" not in resp.text
        assert "Not scanned yet" not in resp.text

    async def test_lifespan_sets_injected_hub(self, hub: ForkHub):
        app = create_app(hub)
        async with app.router.lifespan_context(app):
            assert app.state.hub is hub

    async def test_explore_route_emits_span_with_labels(
        self, hub: ForkHub, db: Database, monkeypatch
    ):
        """The render path records the repository and relationship scan state."""
        import forkhub.otel as otel

        await _seed_repo(db)
        recorded: list[dict] = []

        @contextmanager
        def fake_span(name, **attrs):
            rec = {"name": name, "attrs": dict(attrs)}
            recorded.append(rec)

            class _S:
                def set_attribute(self, k, v):
                    rec["attrs"][k] = v

            yield _S()

        monkeypatch.setattr(otel, "span", fake_span)
        app = create_app(hub)
        app.state.hub = hub
        async with _client(app) as client:
            await client.get("/torvalds/linux")

        assert recorded and recorded[0]["name"] == "web.explore"
        assert recorded[0]["attrs"]["repo"] == "torvalds/linux"
        assert recorded[0]["attrs"]["relationship_status"] == "not_scanned"

    async def test_explore_escapes_html_in_rendered_relationships(self, hub: ForkHub, db: Database):
        """Jinja autoescaping prevents untrusted repository names from becoming HTML."""
        repo = make_tracked_repo()
        await db.insert_tracked_repo(repo)
        fork = make_fork(repo["id"])
        await db.insert_fork(fork)
        await db.save_relationship_snapshot(
            "torvalds",
            {
                "focus_github_id": 123456,
                "focus_repo": "torvalds/linux",
                "upstream_repo": None,
                "complete": True,
                "pages_scanned": 1,
                "relationships": [
                    {
                        "direction": "downstream",
                        "github_id": 9001,
                        "source_repo": "</script><img src=x onerror=alert(1)>",
                        "target_repo": "torvalds/linux",
                        "is_user_repository": False,
                    }
                ],
            },
        )
        app = create_app(hub)
        app.state.hub = hub
        async with _client(app) as client:
            resp = await client.get("/torvalds/linux")

        assert resp.status_code == 200
        assert "<img src=x" not in resp.text  # the injected tag never appears raw
        assert "&lt;img src=x" in resp.text  # the untrusted name is HTML-escaped


@pytest.mark.parametrize(
    "state",
    [None, "unavailable", "partial", "verified", "mismatched", "bad_warnings", "bad_changes"],
)
async def test_signal_evidence_inspection_and_immutable_links(hub, db, state):
    repo = await _seed_repo(db)
    sha = "a" * 40
    evidence = None
    if state is not None:
        evidence = {
            "source_repository": "someone/linux",
            "commit_shas": [sha],
            "files": ["src/gpu.py"],
            "changes": [
                {
                    "commit_sha": sha,
                    "filename": "src/gpu.py",
                    "status": "modified",
                    "patch": "+<script>alert(1)</script>",
                }
            ],
            "warnings": ["Patch retrieval was incomplete."] if state == "partial" else [],
            "verification_state": (
                "verified"
                if state == "mismatched"
                else "partial"
                if state in {"bad_warnings", "bad_changes"}
                else state
            ),
            "verified_at": (
                "2026-11-10T12:00:00+00:00" if state in {"verified", "mismatched"} else None
            ),
        }
        if state == "bad_warnings":
            evidence["warnings"] = 1
        elif state == "bad_changes":
            evidence["changes"] = None
    await db.insert_signal(
        make_signal(
            None,
            repo["id"],
            files_involved=json.dumps(["other.py" if state == "mismatched" else "src/gpu.py"]),
            evidence=json.dumps(evidence) if evidence else None,
        )
    )
    app = create_app(hub)
    app.state.hub = hub
    async with _client(app) as client:
        response = await client.get("/torvalds/linux")
    assert response.status_code == 200
    assert "Model interpretation" in response.text
    assert "Inspect source evidence" in response.text
    if state in {None, "mismatched", "bad_warnings", "bad_changes"}:
        assert "interpretation has no usable recorded immutable provenance" in response.text
        assert "/commit/" not in response.text
        if state is not None:
            assert "Stored evidence is malformed and cannot be trusted." in response.text
    else:
        assert f"https://github.com/someone/linux/commit/{sha}" in response.text
        assert "src/gpu.py" in response.text
        assert "+&lt;script&gt;alert(1)&lt;/script&gt;" in response.text
        assert "+<script>" not in response.text
        assert f"<dd>{state}</dd>" in response.text
        if state == "partial":
            assert "Patch retrieval was incomplete." in response.text


async def test_empty_signal_cache_does_not_claim_no_changes(hub, db):
    await _seed_repo(db)
    app = create_app(hub)
    app.state.hub = hub
    async with _client(app) as client:
        response = await client.get("/torvalds/linux")
    assert response.status_code == 200
    assert "An empty cache does not establish" in response.text


async def test_signal_list_shows_truncation_and_stale_warning(hub, db):
    repo = make_tracked_repo(sync_status="inaccessible")
    await db.insert_tracked_repo(repo)
    for index in range(21):
        await db.insert_signal(make_signal(None, repo["id"], summary=f"Change {index}"))
    app = create_app(hub)
    app.state.hub = hub
    async with _client(app) as client:
        response = await client.get("/torvalds/linux")
    assert response.status_code == 200
    assert response.text.count('<article class="signal-card">') == 20
    assert "Showing the first 20 signals" in response.text
    assert "Latest repository sync failed; cached analysis may be stale." in response.text

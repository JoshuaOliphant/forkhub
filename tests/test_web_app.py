# ABOUTME: Tests for the Explore FastAPI app — routes, redirects, 404, lifespan.
# ABOUTME: Drives the ASGI app via httpx in the test event loop (shared db connection).

from __future__ import annotations

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
    await db.insert_signal(make_signal(fork["id"], repo["id"]))
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
        assert 'id="forkhub-data"' in resp.text
        assert "torvalds/linux" in resp.text  # repo name rendered in the topbar

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

    async def test_lifespan_sets_injected_hub(self, hub: ForkHub):
        app = create_app(hub)
        async with app.router.lifespan_context(app):
            assert app.state.hub is hub

    async def test_explore_route_emits_span_with_labels(
        self, hub: ForkHub, db: Database, monkeypatch
    ):
        """The render path opens a 'web.explore' span carrying repo + fork_count (AC-13)."""
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
        assert recorded[0]["attrs"]["fork_count"] == 1

    async def test_explore_escapes_html_in_embedded_data(self, hub: ForkHub, db: Database):
        """tojson escapes untrusted markup so it can't break out of the <script> block."""
        repo = make_tracked_repo()
        await db.insert_tracked_repo(repo)
        fork = make_fork(repo["id"])
        await db.insert_fork(fork)
        await db.insert_signal(
            make_signal(fork["id"], repo["id"], summary="</script><img src=x onerror=alert(1)>")
        )
        app = create_app(hub)
        app.state.hub = hub
        async with _client(app) as client:
            resp = await client.get("/torvalds/linux")

        assert resp.status_code == 200
        assert "<img src=x" not in resp.text  # the injected tag never appears raw
        assert "u003cimg" in resp.text  # it's present, but unicode-escaped by tojson

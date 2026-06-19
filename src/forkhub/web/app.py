# ABOUTME: FastAPI app serving the Explore zone from real ForkHub data.
# ABOUTME: create_app(hub) is injectable for tests; lifespan builds a default hub in prod.

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from forkhub.web.data import build_explore_data

if TYPE_CHECKING:
    from forkhub import ForkHub

WEB_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

# Rendered when no repos are tracked yet — a valid-but-empty constellation.
_EMPTY: dict[str, Any] = {
    "repo": {"name": "—", "full_name": "No repos tracked yet", "fork_count": 0, "last_sync": None},
    "clusters": [],
    "forks": [],
}


def create_app(hub: ForkHub | None = None) -> FastAPI:
    """Build the Explore FastAPI app. Pass a connected `hub` for tests; in
    production the lifespan builds and connects a default ForkHub."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if hub is not None:
            app.state.hub = hub
            yield
        else:  # pragma: no cover - builds a real ForkHub + on-disk DB
            from forkhub import ForkHub as _ForkHub

            built = _ForkHub()
            await built.__aenter__()
            app.state.hub = built
            try:
                yield
            finally:
                await built.__aexit__()

    app = FastAPI(title="ForkHub", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        repos = await request.app.state.hub.get_repos()
        if not repos:
            return templates.TemplateResponse(request, "explore.html", {"data": _EMPTY})
        first = repos[0]
        return RedirectResponse(f"/{first.owner}/{first.name}")

    @app.get("/{owner}/{repo}", response_class=HTMLResponse)
    async def explore(request: Request, owner: str, repo: str):
        try:
            data = await build_explore_data(request.app.state.hub, owner, repo)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return templates.TemplateResponse(request, "explore.html", {"data": data})

    return app

# ABOUTME: CLI command to launch the ForkHub web UI (FastAPI served by uvicorn).
# ABOUTME: `forkhub web [--host --port]` serves the Explore zone from real data.

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any


def _web_impl(host: str, port: int, run: Callable[..., Any]) -> None:
    """Build the app and hand it to the server runner (injectable for tests)."""
    from forkhub.web.app import create_app

    run(create_app(), host=host, port=port)


def web_command(
    host: str = typer.Option("127.0.0.1", "--host", help="Host to bind"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind"),
) -> None:
    """Launch the ForkHub web UI (Explore zone)."""
    import uvicorn

    _web_impl(host=host, port=port, run=uvicorn.run)

# ABOUTME: CLI command for listing tracked repositories.
# ABOUTME: Displays tracked repos in a Rich table with optional mode filtering.

from __future__ import annotations

from typing import TYPE_CHECKING

import typer
from rich.console import Console

from forkhub.cli.formatting import render_repo_table
from forkhub.cli.helpers import async_command
from forkhub.models import TrackedRepo

if TYPE_CHECKING:
    from forkhub.database import Database

console = Console()


def _output(line: str, capture: list[str] | None = None) -> None:
    if capture is not None:
        capture.append(line)
    else:
        console.print(line)


async def _repos_impl(
    db: Database | None = None,
    mode: str | None = None,
    capture_output: list[str] | None = None,
) -> None:
    """Core repos listing logic, testable without CLI boilerplate."""
    from forkhub.cli.helpers import get_services

    owns_db = False
    provider = None
    if db is None:
        settings, db, provider = await get_services()
        owns_db = True

    try:
        # Query repos directly from DB
        mode_str = mode if mode else None
        rows = await db.list_tracked_repos(mode=mode_str)

        if not rows:
            msg = "No tracked repositories found. Run 'forkhub init' or 'forkhub track' first."
            _output(msg, capture_output)
            return

        repos = [TrackedRepo(**row) for row in rows]

        if capture_output is not None:
            # For testing: output repo names as plain text
            _output("Tracked Repositories:", capture_output)
            for repo in repos:
                last_synced = (
                    repo.last_synced_at.strftime("%Y-%m-%d %H:%M") if repo.last_synced_at else "-"
                )
                _output(
                    f"  {repo.full_name} | {repo.tracking_mode} | "
                    f"{repo.description or '-'} | {last_synced}",
                    capture_output,
                )
        else:
            render_repo_table(console, repos)
    finally:
        if owns_db:
            await db.close()


@async_command
async def repos_command(
    owned: bool = typer.Option(False, "--owned", help="Show only owned repositories"),
    watched: bool = typer.Option(False, "--watched", help="Show only watched repositories"),
    upstream: bool = typer.Option(False, "--upstream", help="Show only upstream repositories"),
) -> None:
    """List tracked repositories."""
    mode = None
    if owned:
        mode = "owned"
    elif watched:
        mode = "watched"
    elif upstream:
        mode = "upstream"
    await _repos_impl(mode=mode)

# ABOUTME: CLI command for listing tracked repositories.
# ABOUTME: Displays tracked repos in a Rich table with optional mode filtering.

from __future__ import annotations

from typing import TYPE_CHECKING

import typer
from rich.console import Console

from forkhub.cli.formatting import render_repo_table
from forkhub.cli.helpers import async_command

if TYPE_CHECKING:
    from forkhub.database import Database
    from forkhub.interfaces import GitProvider

console = Console()


def _output(line: str, capture: list[str] | None = None) -> None:
    if capture is not None:
        capture.append(line)
    else:
        console.print(line)


async def _repos_impl(
    db: Database | None = None,
    provider: GitProvider | None = None,
    mode: str | None = None,
    sync_status: str | None = None,
    capture_output: list[str] | None = None,
) -> None:
    """Core repos listing logic, testable without CLI boilerplate."""
    from forkhub.cli.helpers import get_services
    from forkhub.models import TrackingMode
    from forkhub.services.tracker import TrackerService

    owns_db = False
    if db is None or provider is None:
        settings, db, provider = await get_services()
        owns_db = True

    try:
        tracker = TrackerService(db=db, provider=provider)
        mode_enum = TrackingMode(mode) if mode else None
        repos = await tracker.list_tracked_repos(
            mode=mode_enum, sync_status=sync_status,
        )

        if not repos:
            msg = "No tracked repositories found. Run 'forkhub init' or 'forkhub track' first."
            _output(msg, capture_output)
            return

        if capture_output is not None:
            # For testing: output repo names as plain text
            _output("Tracked Repositories:", capture_output)
            for repo in repos:
                last_synced = (
                    repo.last_synced_at.strftime("%Y-%m-%d %H:%M") if repo.last_synced_at else "-"
                )
                _output(
                    f"  {repo.full_name} | {repo.tracking_mode} | "
                    f"{repo.sync_status} | {repo.description or '-'} | {last_synced}",
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
    inaccessible: bool = typer.Option(
        False, "--inaccessible", help="Show only inaccessible repositories"
    ),
) -> None:
    """List tracked repositories."""
    mode = None
    if owned:
        mode = "owned"
    elif watched:
        mode = "watched"
    elif upstream:
        mode = "upstream"
    sync_status = "inaccessible" if inaccessible else None
    await _repos_impl(mode=mode, sync_status=sync_status)

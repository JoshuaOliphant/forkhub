# ABOUTME: CLI commands for tracking, untracking, excluding, and including repos.
# ABOUTME: Thin wrappers around TrackerService methods with Rich output.

from __future__ import annotations

from typing import TYPE_CHECKING

import typer
from rich.console import Console

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


async def _track_impl(
    repo: str,
    depth: int = 1,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
) -> None:
    """Core track logic, testable without CLI boilerplate."""
    from forkhub.cli.helpers import open_services
    from forkhub.services.tracker import TrackerService

    async with open_services(db, provider) as (_settings, db, provider):
        parts = repo.split("/")
        if len(parts) != 2:
            msg = f"[red]Error: Invalid repo format '{repo}'. Use owner/repo.[/red]"
            _output(msg, capture_output)
            return

        owner, name = parts
        tracker = TrackerService(db=db, provider=provider)

        try:
            tracked = await tracker.track_repo(owner, name, depth=depth)
            _output(
                f"[green]Tracked[/green] {tracked.full_name} "
                f"(mode: {tracked.tracking_mode}, depth: {tracked.fork_depth})",
                capture_output,
            )
        except ValueError as exc:
            _output(f"[red]Error: {exc}[/red]", capture_output)


async def _untrack_impl(
    repo: str,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
) -> None:
    """Core untrack logic."""
    from forkhub.cli.helpers import open_services
    from forkhub.services.tracker import TrackerService

    async with open_services(db, provider) as (_settings, db, provider):
        parts = repo.split("/")
        if len(parts) != 2:
            msg = f"[red]Error: Invalid repo format '{repo}'. Use owner/repo.[/red]"
            _output(msg, capture_output)
            return

        owner, name = parts
        tracker = TrackerService(db=db, provider=provider)
        await tracker.untrack_repo(owner, name)
        _output(f"[yellow]Untracked[/yellow] {repo}", capture_output)


async def _exclude_impl(
    repo: str,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
) -> None:
    """Core exclude logic."""
    from forkhub.cli.helpers import open_services
    from forkhub.services.tracker import TrackerService

    async with open_services(db, provider) as (_settings, db, provider):
        tracker = TrackerService(db=db, provider=provider)
        await tracker.exclude_repo(repo)
        _output(f"[yellow]Excluded[/yellow] {repo} from sync", capture_output)


async def _include_impl(
    repo: str,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
) -> None:
    """Core include logic."""
    from forkhub.cli.helpers import open_services
    from forkhub.services.tracker import TrackerService

    async with open_services(db, provider) as (_settings, db, provider):
        tracker = TrackerService(db=db, provider=provider)
        await tracker.include_repo(repo)
        _output(f"[green]Included[/green] {repo} in sync", capture_output)


@async_command
async def track_command(
    repo: str = typer.Argument(help="Repository in owner/repo format"),
    depth: int = typer.Option(1, "--depth", "-d", help="Fork traversal depth"),
) -> None:
    """Track a GitHub repository and its forks."""
    await _track_impl(repo=repo, depth=depth)


@async_command
async def untrack_command(
    repo: str = typer.Argument(help="Repository in owner/repo format"),
) -> None:
    """Stop tracking a repository and remove all associated data."""
    await _untrack_impl(repo=repo)


@async_command
async def exclude_command(
    repo: str = typer.Argument(help="Repository full name (owner/repo)"),
) -> None:
    """Exclude a tracked repository from sync operations."""
    await _exclude_impl(repo=repo)


@async_command
async def include_command(
    repo: str = typer.Argument(help="Repository full name (owner/repo)"),
) -> None:
    """Re-include a previously excluded repository in sync operations."""
    await _include_impl(repo=repo)

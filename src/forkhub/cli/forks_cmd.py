# ABOUTME: CLI commands for listing forks and inspecting individual fork details.
# ABOUTME: Shows fork tables with vitality/stars and detailed signal views for inspect.

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import typer
from rich.console import Console

from forkhub.cli.formatting import render_fork_table, render_signal
from forkhub.cli.helpers import async_command
from forkhub.models import Fork, Signal, SignalCategory

if TYPE_CHECKING:
    from forkhub.database import Database

console = Console()


def _output(line: str, capture: list[str] | None = None) -> None:
    if capture is not None:
        capture.append(line)
    else:
        console.print(line)


async def _forks_impl(
    repo: str,
    active: bool = False,
    sort: str = "stars",
    limit: int = 20,
    db: Database | None = None,
    capture_output: list[str] | None = None,
) -> None:
    """Core forks listing logic."""
    from forkhub.cli.helpers import get_services

    owns_db = False
    if db is None:
        settings, db, _ = await get_services()
        owns_db = True

    try:
        repo_row = await db.get_tracked_repo_by_name(repo)
        if repo_row is None:
            msg = f"[red]Error: Repository '{repo}' not found or not tracked.[/red]"
            _output(msg, capture_output)
            return

        vitality_filter = "active" if active else None
        fork_rows = await db.list_forks(repo_row["id"], vitality=vitality_filter)

        if not fork_rows:
            _output(f"No forks found for {repo}.", capture_output)
            return

        # Sort forks
        if sort == "stars":
            fork_rows.sort(key=lambda f: f["stars"], reverse=True)
        elif sort == "recent":
            fork_rows.sort(key=lambda f: f["last_pushed_at"] or "", reverse=True)
        elif sort == "ahead":
            fork_rows.sort(key=lambda f: f["commits_ahead"] or 0, reverse=True)

        # Apply limit
        fork_rows = fork_rows[:limit]

        forks = [Fork(**row) for row in fork_rows]

        if capture_output is not None:
            _output(f"Forks for {repo}:", capture_output)
            for fork in forks:
                _output(
                    f"  {fork.full_name} | stars: {fork.stars} | "
                    f"ahead: {fork.commits_ahead} | behind: {fork.commits_behind} | "
                    f"{fork.vitality}",
                    capture_output,
                )
        else:
            render_fork_table(console, forks)
    finally:
        if owns_db:
            await db.close()


async def _inspect_impl(
    fork_name: str,
    db: Database | None = None,
    capture_output: list[str] | None = None,
) -> None:
    """Core inspect logic for a single fork."""
    from forkhub.cli.helpers import get_services

    owns_db = False
    if db is None:
        settings, db, _ = await get_services()
        owns_db = True

    try:
        fork_row = await db.get_fork_by_name(fork_name)
        if fork_row is None:
            _output(f"[red]Error: Fork '{fork_name}' not found.[/red]", capture_output)
            return

        fork = Fork(**fork_row)

        _output(f"[bold cyan]{fork.full_name}[/bold cyan]", capture_output)
        _output(f"  Description: {fork.description or '-'}", capture_output)
        _output(f"  Stars: {fork.stars}", capture_output)
        _output(f"  Vitality: {fork.vitality}", capture_output)
        _output(f"  Commits ahead: {fork.commits_ahead}", capture_output)
        _output(f"  Commits behind: {fork.commits_behind}", capture_output)
        _output(f"  Default branch: {fork.default_branch}", capture_output)
        _output(f"  HEAD SHA: {fork.head_sha or '-'}", capture_output)

        # Fetch signals for this fork
        signals = await db.list_signals(fork.tracked_repo_id)
        fork_signals = [s for s in signals if s["fork_id"] == fork.id]

        if fork_signals:
            _output(f"\n  Signals ({len(fork_signals)}):", capture_output)
            for sig_row in fork_signals:
                files = (
                    json.loads(sig_row["files_involved"])
                    if isinstance(sig_row["files_involved"], str)
                    else sig_row["files_involved"]
                )
                sig = Signal(
                    id=sig_row["id"],
                    fork_id=sig_row["fork_id"],
                    tracked_repo_id=sig_row["tracked_repo_id"],
                    category=SignalCategory(sig_row["category"]),
                    summary=sig_row["summary"],
                    detail=sig_row.get("detail"),
                    files_involved=files,
                    significance=sig_row["significance"],
                )
                if capture_output is not None:
                    _output(
                        f"    [{sig.category}] {sig.summary} (significance: {sig.significance})",
                        capture_output,
                    )
                else:
                    render_signal(console, sig)
        else:
            _output("\n  No signals recorded for this fork.", capture_output)
    finally:
        if owns_db:
            await db.close()


@async_command
async def forks_command(
    repo: str = typer.Argument(help="Repository in owner/repo format"),
    active: bool = typer.Option(False, "--active", help="Show only active forks"),
    sort: str = typer.Option("stars", "--sort", "-s", help="Sort by: stars, recent, ahead"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum number of forks to show"),
) -> None:
    """List forks for a tracked repository."""
    await _forks_impl(repo=repo, active=active, sort=sort, limit=limit)


@async_command
async def inspect_command(
    fork_name: str = typer.Argument(help="Fork full name (owner/repo)"),
) -> None:
    """Show detailed information about a specific fork."""
    await _inspect_impl(fork_name=fork_name)

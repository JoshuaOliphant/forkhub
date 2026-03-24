# ABOUTME: CLI command for running the agentic backfill loop.
# ABOUTME: Evaluates fork signals and attempts to cherry-pick valuable changes.

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

from forkhub.cli.helpers import async_command

if TYPE_CHECKING:
    from forkhub.database import Database
    from forkhub.interfaces import GitProvider
    from forkhub.models import BackfillResult

console = Console()


def _output(line: str, capture: list[str] | None = None) -> None:
    if capture is not None:
        capture.append(line)
    else:
        console.print(line)


async def _backfill_impl(
    repo: str | None = None,
    since_days: int = 30,
    dry_run: bool = False,
    min_significance: int = 5,
    max_attempts: int = 10,
    auto_fix_tests: bool = True,
    repo_path: str | None = None,
    test_command: str | None = None,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
) -> BackfillResult | None:
    """Core backfill logic."""
    from forkhub.cli.helpers import get_services
    from forkhub.models import BackfillResult as _BackfillResult
    from forkhub.services.backfill import BackfillService

    owns_db = False
    if db is None or provider is None:
        settings, db, provider = await get_services()
        owns_db = True

    try:
        # Resolve the target repo
        if repo is not None:
            repo_row = await db.get_tracked_repo_by_name(repo)
            if repo_row is None:
                _output(
                    f"[red]Error: Repository '{repo}' not found or not tracked.[/red]",
                    capture_output,
                )
                return None
            repo_ids = [repo_row["id"]]
        else:
            repos = await db.list_tracked_repos()
            if not repos:
                _output("[yellow]No tracked repositories found.[/yellow]", capture_output)
                return None
            repo_ids = [r["id"] for r in repos]

        since = datetime.now(UTC) - timedelta(days=since_days)

        effective_test_cmd = test_command or "uv run pytest -x --tb=short -q"
        effective_repo_path = Path(repo_path) if repo_path else Path.cwd()

        backfill = BackfillService(
            db=db,
            provider=provider,
            repo_path=effective_repo_path,
            test_command=effective_test_cmd,
            min_significance=min_significance,
            max_attempts=max_attempts,
            auto_fix_tests=auto_fix_tests,
        )

        combined = _BackfillResult()

        for repo_id in repo_ids:
            repo_row = await db.get_tracked_repo(repo_id)
            name = repo_row["full_name"] if repo_row else repo_id

            if dry_run:
                _output(f"[dim]Evaluating candidates for {name} (dry run)...[/dim]", capture_output)
            else:
                _output(f"Backfilling {name}...", capture_output)

            result = await backfill.run_backfill(repo_id, since=since, dry_run=dry_run)

            combined.total_evaluated += result.total_evaluated
            combined.attempted += result.attempted
            combined.accepted += result.accepted
            combined.patch_failed += result.patch_failed
            combined.tests_failed += result.tests_failed
            combined.conflicts += result.conflicts
            combined.branches_created.extend(result.branches_created)

        # Print summary
        _output("", capture_output)
        _output("[bold]Backfill Summary[/bold]", capture_output)
        _output(f"  Signals evaluated: {combined.total_evaluated}", capture_output)
        _output(f"  Attempts made:     {combined.attempted}", capture_output)
        _output(f"  Accepted:          [green]{combined.accepted}[/green]", capture_output)
        _output(f"  Patch failed:      [red]{combined.patch_failed}[/red]", capture_output)
        _output(f"  Tests failed:      [yellow]{combined.tests_failed}[/yellow]", capture_output)
        _output(f"  Conflicts:         [red]{combined.conflicts}[/red]", capture_output)

        if combined.branches_created:
            _output("", capture_output)
            _output("[bold]Candidate branches created:[/bold]", capture_output)
            for branch in combined.branches_created:
                _output(f"  [green]{branch}[/green]", capture_output)

        return combined
    finally:
        if owns_db:
            await db.close()


async def _backfill_list_impl(
    repo: str | None = None,
    status: str | None = None,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
) -> None:
    """List previous backfill attempts."""
    from forkhub.cli.helpers import get_services
    from forkhub.services.backfill import BackfillService

    owns_db = False
    if db is None or provider is None:
        settings, db, provider = await get_services()
        owns_db = True

    try:
        repo_id = None
        if repo is not None:
            repo_row = await db.get_tracked_repo_by_name(repo)
            if repo_row is None:
                _output(
                    f"[red]Error: Repository '{repo}' not found.[/red]",
                    capture_output,
                )
                return
            repo_id = repo_row["id"]

        backfill = BackfillService(db=db, provider=provider)
        attempts = await backfill.list_attempts(repo_id=repo_id, status=status)

        if not attempts:
            _output("[dim]No backfill attempts found.[/dim]", capture_output)
            return

        if capture_output is not None:
            for a in attempts:
                capture_output.append(
                    f"{a.id[:8]} {a.status:15s} {a.patch_summary or 'N/A'}"
                )
            return

        table = Table(title="Backfill Attempts")
        table.add_column("ID", style="dim", width=8)
        table.add_column("Status", width=14)
        table.add_column("Branch", width=30)
        table.add_column("Summary", width=40)
        table.add_column("Score", width=6)

        status_colors = {
            "accepted": "green",
            "pending": "dim",
            "patch_failed": "red",
            "tests_failed": "yellow",
            "conflict": "red",
            "rejected": "red",
        }

        for a in attempts:
            color = status_colors.get(a.status, "white")
            score_str = f"{a.score:.1f}" if a.score is not None else "-"
            table.add_row(
                a.id[:8],
                f"[{color}]{a.status}[/{color}]",
                a.branch_name or "-",
                (a.patch_summary or "-")[:40],
                score_str,
            )

        console.print(table)
    finally:
        if owns_db:
            await db.close()


@async_command
async def backfill_command(
    repo: str | None = typer.Option(
        None, "--repo", "-r", help="Backfill only this repository (owner/repo)"
    ),
    since_days: int = typer.Option(
        30, "--since-days", "-s", help="Look back this many days for signals"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Evaluate candidates without applying patches"
    ),
    min_significance: int = typer.Option(
        5, "--min-significance", help="Minimum signal significance to consider"
    ),
    max_attempts: int = typer.Option(
        10, "--max-attempts", help="Maximum number of backfill attempts per run"
    ),
    auto_fix_tests: bool = typer.Option(
        True, "--auto-fix-tests/--no-auto-fix-tests",
        help="Attempt to fix failing tests after patch application"
    ),
    repo_path: str | None = typer.Option(
        None, "--repo-path", help="Path to the local repository to patch"
    ),
    test_command: str | None = typer.Option(
        None, "--test-command", help="Custom test command to run after patching"
    ),
) -> None:
    """Run the agentic backfill loop to cherry-pick valuable fork changes."""
    await _backfill_impl(
        repo=repo,
        since_days=since_days,
        dry_run=dry_run,
        min_significance=min_significance,
        max_attempts=max_attempts,
        auto_fix_tests=auto_fix_tests,
        repo_path=repo_path,
        test_command=test_command,
    )


@async_command
async def backfill_list_command(
    repo: str | None = typer.Option(
        None, "--repo", "-r", help="Filter by repository (owner/repo)"
    ),
    status: str | None = typer.Option(
        None, "--status", help="Filter by status (accepted, tests_failed, patch_failed, etc.)"
    ),
) -> None:
    """List previous backfill attempts and their outcomes."""
    await _backfill_list_impl(repo=repo, status=status)

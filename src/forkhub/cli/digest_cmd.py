# ABOUTME: CLI commands for generating and configuring digest notifications.
# ABOUTME: Generates digests from signals and optionally delivers via backends.

from __future__ import annotations

from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING

import typer
from rich.console import Console

from forkhub.cli.formatting import emit
from forkhub.cli.helpers import async_command
from forkhub.models import DigestConfig

if TYPE_CHECKING:
    from forkhub.database import Database
    from forkhub.interfaces import NotificationBackend

console = Console()


_output = partial(emit, console)


async def _digest_impl(
    since: str | None = None,
    dry_run: bool = False,
    db: Database | None = None,
    capture_output: list[str] | None = None,
) -> None:
    """Core digest generation logic."""
    from forkhub.cli.helpers import open_db
    from forkhub.notifications.console import ConsoleBackend
    from forkhub.services.digest import DigestService

    async with open_db(db) as db:
        # Parse since date
        since_dt = None
        if since is not None:
            try:
                since_dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=UTC)
            except ValueError:
                _output(
                    f"[red]Error: Invalid date format '{since}'. Use YYYY-MM-DD.[/red]",
                    capture_output,
                )
                return

        # Build digest config
        config = DigestConfig(
            tracked_repo_id=None,
            min_significance=5,
        )

        backends: list[NotificationBackend] = [ConsoleBackend(console)]
        digest_service = DigestService(db=db, backends=backends)

        # Generate the digest
        digest = await digest_service.generate_digest(config, since=since_dt)

        if dry_run:
            _output("[bold]Digest Preview (dry run):[/bold]", capture_output)
            _output(f"\n  Title: {digest.title}", capture_output)
            _output(f"\n{digest.body}", capture_output)
            _output(f"\n  Signals: {len(digest.signal_ids)}", capture_output)
        else:
            # Deliver the digest
            results = await digest_service.deliver_digest(digest)
            _output("[bold]Digest delivered:[/bold]", capture_output)
            _output(f"  Title: {digest.title}", capture_output)
            for result in results:
                if result.success:
                    status = "[green]OK[/green]"
                else:
                    status = f"[red]FAILED: {result.error}[/red]"
                _output(f"  {result.backend_name}: {status}", capture_output)


@async_command
async def digest_command(
    since: str | None = typer.Option(None, "--since", help="Start date (YYYY-MM-DD)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview digest without delivering"),
) -> None:
    """Generate and deliver a digest notification."""
    await _digest_impl(since=since, dry_run=dry_run)

# ABOUTME: CLI command for running the sync pipeline.
# ABOUTME: Discovers forks, compares HEADs, and shows sync summary results.

from __future__ import annotations

from typing import TYPE_CHECKING

import typer
from rich.console import Console

from forkhub.cli.helpers import async_command

if TYPE_CHECKING:
    from forkhub.config import SyncSettings
    from forkhub.database import Database
    from forkhub.interfaces import GitProvider

console = Console()


def _output(line: str, capture: list[str] | None = None) -> None:
    if capture is not None:
        capture.append(line)
    else:
        console.print(line)


async def _sync_impl(
    repo: str | None = None,
    db: Database | None = None,
    provider: GitProvider | None = None,
    sync_settings: SyncSettings | None = None,
    capture_output: list[str] | None = None,
) -> None:
    """Core sync logic."""
    from forkhub.cli.helpers import get_services
    from forkhub.config import SyncSettings as SyncSettingsImpl
    from forkhub.services.sync import SyncService

    owns_db = False
    if db is None or provider is None:
        settings, db, provider = await get_services()
        owns_db = True
        if sync_settings is None:
            sync_settings = settings.sync

    if sync_settings is None:
        sync_settings = SyncSettingsImpl()

    try:
        sync_service = SyncService(db=db, provider=provider, settings=sync_settings)

        if repo is not None:
            # Sync a specific repo
            repo_row = await db.get_tracked_repo_by_name(repo)
            if repo_row is None:
                msg = f"[red]Error: Repository '{repo}' not found or not tracked.[/red]"
                _output(msg, capture_output)
                return

            _output(f"Syncing {repo}...", capture_output)
            result = await sync_service.sync_repo(repo_row["id"])

            _output(f"\nSync complete for {result.repo_full_name}:", capture_output)
            _output(f"  New forks discovered: {result.new_forks}", capture_output)
            _output(f"  Changed forks: {len(result.changed_forks)}", capture_output)
            _output(f"  New releases: {result.new_releases}", capture_output)

            if result.changed_forks:
                _output("  Changed:", capture_output)
                for fork_name in result.changed_forks:
                    _output(f"    ~ {fork_name}", capture_output)

            if result.errors:
                _output(f"  [yellow]Warnings: {len(result.errors)}[/yellow]", capture_output)
                for err in result.errors:
                    _output(f"    ! {err}", capture_output)
        else:
            # Sync all repos
            _output("Syncing all tracked repositories...", capture_output)
            result = await sync_service.sync_all()

            _output("\nSync complete:", capture_output)
            _output(f"  Repos synced: {result.repos_synced}", capture_output)
            _output(f"  Total changed forks: {result.total_changed_forks}", capture_output)
            _output(f"  Total new releases: {result.total_new_releases}", capture_output)

            for repo_result in result.results:
                if repo_result.new_forks or repo_result.changed_forks:
                    _output(
                        f"  {repo_result.repo_full_name}: "
                        f"{repo_result.new_forks} new, "
                        f"{len(repo_result.changed_forks)} changed",
                        capture_output,
                    )

            if result.errors:
                _output(f"\n  [yellow]Warnings: {len(result.errors)}[/yellow]", capture_output)
                for err in result.errors:
                    _output(f"    ! {err}", capture_output)
    finally:
        if owns_db:
            await db.close()


@async_command
async def sync_command(
    repo: str | None = typer.Option(
        None, "--repo", "-r", help="Sync only this repository (owner/repo)"
    ),
) -> None:
    """Run the sync pipeline to discover and compare forks."""
    await _sync_impl(repo=repo)

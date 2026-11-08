# ABOUTME: Explicit local relationship discovery and cache population command.
# ABOUTME: Reports incomplete scans honestly and preserves existing complete snapshots.

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from forkhub.cli.helpers import async_command

if TYPE_CHECKING:
    from forkhub.database import Database
    from forkhub.interfaces import GitProvider


async def _relationships_impl(
    repository: str,
    username: str,
    *,
    max_pages: int = 3,
    db: Database | None = None,
    provider: GitProvider | None = None,
) -> dict:
    """Discover relationships for one repository and persist the scan attempt.

    The returned summary describes *this attempt*, which may be incomplete.
    Database retention rules preserve a previous complete snapshot on failure
    or partial coverage.
    """
    from forkhub.cli.helpers import open_services
    from forkhub.services.relationships import RelationshipService

    if not username.strip():
        raise ValueError("username is required")
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")

    async with open_services(db, provider) as (_settings, db, provider):
        snapshot = await RelationshipService(provider).discover(
            username.strip(), repository, max_pages=max_pages
        )
        await db.save_relationship_snapshot(username.strip(), snapshot.model_dump(mode="json"))
        return {
            "repository": snapshot.focus_repo,
            "complete": snapshot.complete,
            "pages_scanned": snapshot.pages_scanned,
            "relationship_count": len(snapshot.relationships),
        }


@async_command
async def relationships_command(
    repository: str = typer.Argument(help="Repository in owner/name format"),
    username: str = typer.Option(..., "--username", help="GitHub username for scoped cache"),
    max_pages: int = typer.Option(3, "--max-pages", min=1, help="Maximum fork pages"),
) -> None:
    """Discover and cache a repository's relationships (no AI analysis)."""
    result = await _relationships_impl(repository, username, max_pages=max_pages)
    typer.echo(
        f"{result['repository']}: "
        f"{result['relationship_count']} relationships, "
        f"{result['pages_scanned']} pages scanned; "
        f"complete={str(result['complete']).lower()}"
    )
    if not result["complete"]:
        typer.echo("Warning: incomplete coverage; previous complete cache is retained, if any.")

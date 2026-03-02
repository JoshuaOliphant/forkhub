# ABOUTME: CLI command for viewing signal clusters across forks.
# ABOUTME: Shows Rich panels for each cluster with label, fork count, and file patterns.

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import typer
from rich.console import Console

from forkhub.cli.formatting import render_cluster
from forkhub.cli.helpers import async_command
from forkhub.models import Cluster

if TYPE_CHECKING:
    from forkhub.database import Database

console = Console()


def _output(line: str, capture: list[str] | None = None) -> None:
    if capture is not None:
        capture.append(line)
    else:
        console.print(line)


async def _clusters_impl(
    repo: str,
    min_size: int = 2,
    db: Database | None = None,
    capture_output: list[str] | None = None,
) -> None:
    """Core clusters listing logic."""
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

        cluster_rows = await db.list_clusters(repo_row["id"])
        clusters = []
        for row in cluster_rows:
            if row["fork_count"] >= min_size:
                files_pattern = (
                    json.loads(row["files_pattern"])
                    if isinstance(row["files_pattern"], str)
                    else row["files_pattern"]
                )
                clusters.append(
                    Cluster(
                        id=row["id"],
                        tracked_repo_id=row["tracked_repo_id"],
                        label=row["label"],
                        description=row["description"],
                        files_pattern=files_pattern,
                        fork_count=row["fork_count"],
                    )
                )

        if not clusters:
            _output(f"No clusters found for {repo} (min size: {min_size}).", capture_output)
            return

        if capture_output is not None:
            _output(f"Clusters for {repo}:", capture_output)
            for cluster in clusters:
                patterns = ", ".join(cluster.files_pattern) if cluster.files_pattern else "-"
                _output(
                    f"  [{cluster.label}] {cluster.description} "
                    f"| {cluster.fork_count} forks | patterns: {patterns}",
                    capture_output,
                )
        else:
            for cluster in clusters:
                render_cluster(console, cluster)
    finally:
        if owns_db:
            await db.close()


@async_command
async def clusters_command(
    repo: str = typer.Argument(help="Repository in owner/repo format"),
    min_size: int = typer.Option(2, "--min-size", "-m", help="Minimum cluster size (fork count)"),
) -> None:
    """View signal clusters for a tracked repository."""
    await _clusters_impl(repo=repo, min_size=min_size)

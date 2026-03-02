# ABOUTME: Rich console formatting helpers for CLI output.
# ABOUTME: Tables, panels, and styled text for digests, fork listings, and status.

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from forkhub.models import (
    Cluster,
    Digest,
    Fork,
    ForkVitality,
    Signal,
    SignalCategory,
    TrackedRepo,
)

if TYPE_CHECKING:
    from rich.console import Console

# Category display configuration: (color, emoji)
CATEGORY_STYLES: dict[SignalCategory, tuple[str, str]] = {
    SignalCategory.FEATURE: ("green", "+"),
    SignalCategory.FIX: ("red", "x"),
    SignalCategory.REFACTOR: ("blue", "~"),
    SignalCategory.CONFIG: ("yellow", "#"),
    SignalCategory.DEPENDENCY: ("magenta", "^"),
    SignalCategory.REMOVAL: ("red bold", "-"),
    SignalCategory.ADAPTATION: ("cyan", "*"),
    SignalCategory.RELEASE: ("yellow bold", "!"),
}

# Vitality display configuration: (color, label)
VITALITY_STYLES: dict[ForkVitality, tuple[str, str]] = {
    ForkVitality.ACTIVE: ("green", "active"),
    ForkVitality.DORMANT: ("yellow", "dormant"),
    ForkVitality.DEAD: ("red", "dead"),
    ForkVitality.UNKNOWN: ("dim", "unknown"),
}


def format_significance(score: int) -> str:
    """Convert a 1-10 significance score to a visual bar.

    Returns a 10-character string of filled and empty blocks,
    e.g. score=7 produces '███████░░░'.
    """
    filled = score
    empty = 10 - score
    return "\u2588" * filled + "\u2591" * empty


def render_digest(console: Console, digest: Digest) -> None:
    """Render a full digest to the console with Rich formatting.

    Outputs a header panel with the digest title, the body text,
    and a footer with signal count.
    """
    # Header panel with title
    console.print(
        Panel(
            Text(digest.title, style="bold"),
            border_style="cyan",
        )
    )

    # Body text (wrapped in Text to prevent Rich auto-highlighting)
    console.print()
    console.print(Text(digest.body))
    console.print()

    # Footer with signal count
    signal_count = len(digest.signal_ids)
    console.print(
        Text(f"{signal_count} signal(s) included in this digest", style="dim"),
    )


def render_repo_table(console: Console, repos: list[TrackedRepo]) -> None:
    """Render a table of tracked repositories."""
    table = Table(title="Tracked Repositories")
    table.add_column("Repository", style="cyan")
    table.add_column("Mode", style="green")
    table.add_column("Description")
    table.add_column("Last Synced")

    for repo in repos:
        last_synced = repo.last_synced_at.strftime("%Y-%m-%d %H:%M") if repo.last_synced_at else "-"
        table.add_row(
            repo.full_name,
            str(repo.tracking_mode),
            repo.description or "-",
            last_synced,
        )

    console.print(table)


def render_fork_table(console: Console, forks: list[Fork]) -> None:
    """Render a table of forks with stats summary."""
    table = Table(title="Forks")
    table.add_column("Fork", style="cyan")
    table.add_column("Stars", justify="right", style="yellow")
    table.add_column("Ahead", justify="right")
    table.add_column("Behind", justify="right")
    table.add_column("Vitality")

    for fork in forks:
        vitality_style, vitality_label = VITALITY_STYLES.get(
            fork.vitality, ("dim", str(fork.vitality))
        )
        table.add_row(
            fork.full_name,
            str(fork.stars),
            str(fork.commits_ahead),
            str(fork.commits_behind),
            Text(vitality_label, style=vitality_style),
        )

    console.print(table)


def render_signal(console: Console, signal: Signal) -> None:
    """Render a single signal with category, significance bar, and details."""
    style, marker = CATEGORY_STYLES.get(signal.category, ("white", "?"))

    # Category badge and summary
    header = Text()
    header.append(f"[{marker}] ", style=style)
    header.append(f"{signal.category} ", style=f"bold {style}")
    header.append(format_significance(signal.significance))
    header.append(f"  {signal.summary}")

    console.print(
        Panel(
            header,
            border_style=style.split()[0],
        )
    )

    # Detail text if present
    if signal.detail:
        console.print(f"  {signal.detail}", style="dim")

    # Files involved
    if signal.files_involved:
        files_text = Text("  Files: ", style="dim")
        files_text.append(", ".join(signal.files_involved), style="dim italic")
        console.print(files_text)


def render_cluster(console: Console, cluster: Cluster) -> None:
    """Render a cluster summary with label, description, fork count, and file patterns."""
    # Cluster header
    header = Text()
    header.append(cluster.label, style="bold magenta")
    header.append(f"  ({cluster.fork_count} forks)", style="dim")

    console.print(
        Panel(
            header,
            title="Cluster",
            border_style="magenta",
        )
    )

    # Description
    console.print(f"  {cluster.description}", style="dim")

    # File patterns
    if cluster.files_pattern:
        patterns_text = Text("  Patterns: ", style="dim")
        patterns_text.append(", ".join(cluster.files_pattern), style="dim italic")
        console.print(patterns_text)

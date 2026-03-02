# ABOUTME: CLI commands for viewing and managing ForkHub configuration.
# ABOUTME: Shows current settings and config file paths.

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from pathlib import Path
from rich.console import Console

from forkhub.cli.helpers import async_command

console = Console()

config_app = typer.Typer(
    name="config",
    help="View and manage ForkHub configuration.",
)


def _output(line: str, capture: list[str] | None = None) -> None:
    if capture is not None:
        capture.append(line)
    else:
        console.print(line)


async def _config_show_impl(
    config_path: Path | None = None,
    capture_output: list[str] | None = None,
) -> None:
    """Core config show logic."""
    from forkhub.config import load_settings

    settings = load_settings(config_path)

    _output("[bold]ForkHub Configuration[/bold]", capture_output)
    _output("", capture_output)

    _output("[cyan]GitHub[/cyan]", capture_output)
    # Mask the token for security
    token = settings.github.token
    masked_token = f"{token[:4]}...{token[-4:]}" if len(token) > 8 else "***"
    _output(f"  token: {masked_token}", capture_output)
    _output(f"  username: {settings.github.username}", capture_output)

    _output("", capture_output)
    _output("[cyan]Database[/cyan]", capture_output)
    _output(f"  path: {settings.database.path}", capture_output)

    _output("", capture_output)
    _output("[cyan]Sync[/cyan]", capture_output)
    _output(f"  polling_interval: {settings.sync.polling_interval}", capture_output)
    _output(f"  max_forks_per_repo: {settings.sync.max_forks_per_repo}", capture_output)

    _output("", capture_output)
    _output("[cyan]Analysis[/cyan]", capture_output)
    max_dives = settings.analysis.max_deep_dives_per_fork
    _output(f"  max_deep_dives_per_fork: {max_dives}", capture_output)

    _output("", capture_output)
    _output("[cyan]Embedding[/cyan]", capture_output)
    _output(f"  provider: {settings.embedding.provider}", capture_output)
    _output(f"  model: {settings.embedding.model}", capture_output)

    _output("", capture_output)
    _output("[cyan]Digest[/cyan]", capture_output)
    _output(f"  frequency: {settings.digest.frequency}", capture_output)
    _output(f"  min_significance: {settings.digest.min_significance}", capture_output)
    _output(f"  backends: {', '.join(settings.digest.backends)}", capture_output)


async def _config_path_impl(
    capture_output: list[str] | None = None,
) -> None:
    """Core config path logic."""
    from forkhub.config import get_config_dir

    config_dir = get_config_dir()
    config_file = config_dir / "forkhub.toml"

    _output(f"Config directory: {config_dir}", capture_output)
    if config_file.exists():
        _output(f"Config file:      {config_file} [green](exists)[/green]", capture_output)
    else:
        _output(f"Config file:      {config_file} [yellow](not found)[/yellow]", capture_output)


@config_app.command("show")
@async_command
async def config_show_command() -> None:
    """Display current ForkHub configuration."""
    await _config_show_impl()


@config_app.command("path")
@async_command
async def config_path_command() -> None:
    """Show the configuration file path."""
    await _config_path_impl()

# ABOUTME: CLI command for initializing ForkHub configuration and repo discovery.
# ABOUTME: Creates config dir, writes forkhub.toml, discovers owned and upstream repos.

from __future__ import annotations

from typing import TYPE_CHECKING

import typer
from rich.console import Console

from forkhub.cli.helpers import async_command

if TYPE_CHECKING:
    from pathlib import Path

    from forkhub.database import Database
    from forkhub.interfaces import GitProvider

console = Console()


async def _init_impl(
    username: str,
    token: str | None = None,
    config_dir: Path | None = None,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
) -> None:
    """Core init logic, testable without CLI boilerplate.

    If token is None, falls back to GITHUB_TOKEN env var.
    If db/provider are None, they are created from real settings.
    If capture_output is provided, output lines are appended there instead of printed.
    """
    import os

    from forkhub.config import get_config_dir, get_db_path, load_settings
    from forkhub.database import Database as DatabaseImpl
    from forkhub.providers.github import GitHubProvider
    from forkhub.services.tracker import TrackerService

    def _output(line: str) -> None:
        if capture_output is not None:
            capture_output.append(line)
        else:
            console.print(line)

    # Resolve token: explicit arg > GITHUB_TOKEN env var
    if not token:
        token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        _output("[red]Error: No GitHub token provided.[/red]")
        _output("Pass --token or set GITHUB_TOKEN in your .env file.")
        return

    # Determine config directory
    if config_dir is None:
        config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    # Write config file
    config_file = config_dir / "forkhub.toml"
    config_content = f'[github]\ntoken = "{token}"\nusername = "{username}"\n'
    config_file.write_text(config_content)

    _output(f"Configuration written to {config_file}")

    # Initialize database if not provided
    owns_db = False
    if db is None:
        settings = load_settings(config_file)
        db = DatabaseImpl(get_db_path(settings))
        await db.connect()
        owns_db = True

    # Initialize provider if not provided
    if provider is None:
        provider = GitHubProvider(token)

    try:
        tracker = TrackerService(db=db, provider=provider)

        # Discover owned repos
        owned = await tracker.discover_owned_repos(username)
        _output(f"\nDiscovered {len(owned)} owned repositories:")
        for repo in owned:
            _output(f"  + {repo.full_name} ({repo.description or 'no description'})")

        # Detect upstream repos
        upstream = await tracker.detect_upstream_repos(username)
        if upstream:
            _output(f"\nDetected {len(upstream)} upstream repositories:")
            for repo in upstream:
                _output(f"  ^ {repo.full_name} ({repo.description or 'no description'})")

        total = len(owned) + len(upstream)
        _output(f"\nTotal: {total} repositories now tracked.")
    finally:
        if owns_db:
            await db.close()


@async_command
async def init_command(
    username: str = typer.Option(..., "--user", "-u", help="GitHub username"),
    token: str | None = typer.Option(
        None, "--token", "-t", help="GitHub token (defaults to GITHUB_TOKEN env var)"
    ),
) -> None:
    """Initialize ForkHub: create config, discover repos."""
    await _init_impl(username=username, token=token)

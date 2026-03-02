# ABOUTME: Typer app root — registers all CLI subcommands.
# ABOUTME: Entry point for the `forkhub` command.


import typer

from forkhub.cli.clusters_cmd import clusters_command
from forkhub.cli.config_cmd import config_app
from forkhub.cli.digest_cmd import digest_command
from forkhub.cli.forks_cmd import forks_command, inspect_command
from forkhub.cli.init_cmd import init_command
from forkhub.cli.repos_cmd import repos_command
from forkhub.cli.sync_cmd import sync_command
from forkhub.cli.track_cmd import (
    exclude_command,
    include_command,
    track_command,
    untrack_command,
)

app = typer.Typer(
    name="forkhub",
    help="Monitor GitHub fork constellations with AI-powered analysis.",
    invoke_without_command=True,
)

# Register individual commands
app.command("init")(init_command)
app.command("track")(track_command)
app.command("untrack")(untrack_command)
app.command("exclude")(exclude_command)
app.command("include")(include_command)
app.command("repos")(repos_command)
app.command("forks")(forks_command)
app.command("inspect")(inspect_command)
app.command("clusters")(clusters_command)
app.command("sync")(sync_command)
app.command("digest")(digest_command)

# Register sub-apps (grouped commands)
app.add_typer(config_app, name="config")


@app.callback()
def main(
    ctx: typer.Context,
    show_version: bool | None = typer.Option(  # noqa: UP007
        None, "--version", "-V", help="Show the ForkHub version and exit.", is_eager=True
    ),
) -> None:
    """Monitor GitHub fork constellations with AI-powered analysis."""
    if show_version:
        from forkhub import __version__

        typer.echo(f"forkhub {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()

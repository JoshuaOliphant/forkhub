# ABOUTME: Typer app root — registers all CLI subcommands.
# ABOUTME: Entry point for the `forkhub` command.


import typer

app = typer.Typer(
    name="forkhub",
    help="Monitor GitHub fork constellations with AI-powered analysis.",
    invoke_without_command=True,
)


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

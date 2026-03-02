# ABOUTME: Smoke tests to verify project scaffolding is correct.
# ABOUTME: Validates imports, version, and CLI entry point work.


def test_version_importable():
    """The library version should be importable."""
    from forkhub import __version__

    assert __version__ == "0.1.0"


def test_cli_app_importable():
    """The CLI Typer app should be importable."""
    from forkhub.cli.app import app

    assert app is not None


def test_all_packages_importable():
    """All subpackages should be importable without errors."""
    import forkhub.agent
    import forkhub.cli
    import forkhub.config
    import forkhub.database
    import forkhub.embeddings
    import forkhub.interfaces
    import forkhub.models
    import forkhub.notifications
    import forkhub.providers
    import forkhub.services

    # Just verify they loaded (the imports above would fail if not)
    assert forkhub.models is not None
    assert forkhub.interfaces is not None
    assert forkhub.database is not None
    assert forkhub.config is not None
    assert forkhub.providers is not None
    assert forkhub.embeddings is not None
    assert forkhub.notifications is not None
    assert forkhub.agent is not None
    assert forkhub.services is not None
    assert forkhub.cli is not None

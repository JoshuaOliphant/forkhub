# ABOUTME: Tests for package metadata and version consistency.
# ABOUTME: Verifies __version__ exists and build metadata is correct.

import re

from forkhub import __version__


def test_version_exists():
    """Package exposes a __version__ string."""
    assert isinstance(__version__, str)
    assert len(__version__) > 0


def test_version_is_valid_semver():
    """Version follows semver-like format (X.Y.Z)."""
    assert re.match(r"^\d+\.\d+\.\d+", __version__)


def test_version_matches_importlib_metadata():
    """__version__ matches what importlib.metadata reports."""
    from importlib.metadata import version

    assert __version__ == version("forkhub")

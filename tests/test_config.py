# ABOUTME: Tests for the ForkHub configuration system.
# ABOUTME: Verifies TOML loading, env var overrides, search order, defaults, and helper functions.
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from forkhub.config import (
    AnthropicSettings,
    _find_dotenv_file,
    load_dotenv_file,
    load_settings,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

# ===========================================================================
# Test: Config search order (explicit > cwd > ~/.config)
# ===========================================================================


class TestConfigSearchOrder:
    """load_settings should search: explicit path > ./forkhub.toml > ~/.config/forkhub/."""

    def test_cwd_toml_and_defaults_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """./forkhub.toml in cwd should be used; without it, defaults apply."""
        # Test 1: CWD TOML is used
        cwd_toml = tmp_path / "forkhub.toml"
        cwd_toml.write_text('[github]\ntoken = "from-cwd"\n')
        monkeypatch.chdir(tmp_path)
        settings = load_settings()
        assert settings.github.token == "from-cwd"

        # Test 2: No config found → defaults
        empty_cwd = tmp_path / "empty"
        empty_cwd.mkdir()
        monkeypatch.chdir(empty_cwd)
        monkeypatch.setenv("HOME", str(tmp_path))
        settings = load_settings()
        assert settings.github.token == ""
        assert settings.anthropic.api_key == ""
        assert settings.sync.polling_interval == "6h"


# ===========================================================================
# Test: OAuth token support (CLAUDE_ACCESS_TOKEN)
# ===========================================================================


class TestOAuthTokenSupport:
    """AnthropicSettings should support OAuth tokens from `claude set-token`."""

    def test_oauth_token_defaults_to_empty(self) -> None:
        settings = AnthropicSettings()
        assert settings.oauth_token == ""

    def test_effective_token_prefers_api_key(self) -> None:
        settings = AnthropicSettings(api_key="sk-ant-test", oauth_token="oauth-test")
        assert settings.effective_token == "sk-ant-test"

    def test_auth_method_detection(self) -> None:
        assert AnthropicSettings(api_key="sk-ant-test").auth_method == "api_key"
        assert AnthropicSettings(oauth_token="oauth-test").auth_method == "oauth"


# ===========================================================================
# Test: .env discovery (cwd > parent dirs > ~/.config/forkhub/.env)
# ===========================================================================


class TestDotenvDiscovery:
    """load_dotenv_file should find .env outside cwd, like git/ruff search upward."""

    def test_finds_dotenv_in_parent_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Running from a subdir without .env finds the .env in an ancestor dir."""
        project = tmp_path / "project"
        nested = project / "deep" / "nested"
        nested.mkdir(parents=True)
        (project / ".env").write_text("GITHUB_TOKEN=from-parent\n")
        # No HOME .env to interfere.
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.chdir(nested)

        assert _find_dotenv_file() == project / ".env"

    def test_finds_dotenv_in_config_dir_when_not_in_tree(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no .env in cwd or ancestors, ~/.config/forkhub/.env is used."""
        fakehome = tmp_path / "fakehome"
        config_dir = fakehome / ".config" / "forkhub"
        config_dir.mkdir(parents=True)
        config_env = config_dir / ".env"
        config_env.write_text("GITHUB_TOKEN=from-config\n")
        workdir = tmp_path / "elsewhere"
        workdir.mkdir()
        monkeypatch.setenv("HOME", str(fakehome))
        monkeypatch.chdir(workdir)

        assert _find_dotenv_file() == config_env

    def test_returns_none_when_no_dotenv_anywhere(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No .env in tree and none in config dir → None."""
        fakehome = tmp_path / "fakehome"
        fakehome.mkdir()
        workdir = tmp_path / "barren"
        workdir.mkdir()
        monkeypatch.setenv("HOME", str(fakehome))
        monkeypatch.chdir(workdir)

        assert _find_dotenv_file() is None

    def test_load_from_parent_populates_environ(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """load_dotenv_file() loads creds from an ancestor .env, not just cwd."""
        project = tmp_path / "project"
        nested = project / "sub"
        nested.mkdir(parents=True)
        (project / ".env").write_text("GITHUB_TOKEN=discovered-upward\n")
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.chdir(nested)

        load_dotenv_file()

        assert load_settings().github.token == "discovered-upward"

    def test_explicit_path_overrides_search(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An explicit dotenv_path is loaded directly without searching."""
        explicit = tmp_path / "custom.env"
        explicit.write_text("GITHUB_TOKEN=explicit\n")
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.chdir(tmp_path)

        load_dotenv_file(dotenv_path=explicit)

        assert load_settings().github.token == "explicit"

    def test_logs_dotenv_source_and_credentials(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Startup logs which .env was loaded and which credential sources are present."""
        (tmp_path / ".env").write_text("GITHUB_TOKEN=tok\n")
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_ACCESS_TOKEN", raising=False)
        monkeypatch.chdir(tmp_path)

        with caplog.at_level(logging.INFO, logger="forkhub.config"):
            load_dotenv_file()

        text = caplog.text
        assert str(tmp_path / ".env") in text
        assert "GITHUB_TOKEN" in text

    def test_logs_when_no_dotenv_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When no .env is found, a debug line says so rather than silently passing."""
        fakehome = tmp_path / "fakehome"
        fakehome.mkdir()
        workdir = tmp_path / "nothing"
        workdir.mkdir()
        monkeypatch.setenv("HOME", str(fakehome))
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.chdir(workdir)

        with caplog.at_level(logging.DEBUG, logger="forkhub.config"):
            load_dotenv_file()

        assert "No .env file found" in caplog.text

    def test_walk_stops_at_project_root_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A .git/pyproject.toml marker bounds the walk; an ancestor .env above it is ignored."""
        # tmp_path/.env sits ABOVE the project root and must NOT be picked up.
        (tmp_path / ".env").write_text("GITHUB_TOKEN=stray-ancestor\n")
        project = tmp_path / "project"
        nested = project / "deep"
        nested.mkdir(parents=True)
        # Marker makes `project` the boundary; it has no .env of its own.
        (project / "pyproject.toml").write_text("[project]\nname='x'\n")
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.chdir(nested)

        # Walk reaches the project root (boundary) without finding a .env and
        # stops there, so the stray ancestor .env is never returned.
        assert _find_dotenv_file() is None

    def test_walk_includes_project_root_dotenv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A .env in the project-root directory itself is found before the walk stops."""
        project = tmp_path / "project"
        nested = project / "deep"
        nested.mkdir(parents=True)
        (project / ".git").mkdir()
        (project / ".env").write_text("GITHUB_TOKEN=at-root\n")
        (tmp_path / ".env").write_text("GITHUB_TOKEN=stray-ancestor\n")
        monkeypatch.setenv("HOME", str(tmp_path / "fakehome"))
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.chdir(nested)

        assert _find_dotenv_file() == project / ".env"

    def test_config_fallback_still_works_past_boundary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the bounded walk finds nothing, ~/.config/forkhub/.env is still used."""
        fakehome = tmp_path / "fakehome"
        config_dir = fakehome / ".config" / "forkhub"
        config_dir.mkdir(parents=True)
        config_env = config_dir / ".env"
        config_env.write_text("GITHUB_TOKEN=from-config\n")
        project = tmp_path / "project"
        nested = project / "deep"
        nested.mkdir(parents=True)
        (project / "pyproject.toml").write_text("[project]\nname='x'\n")
        monkeypatch.setenv("HOME", str(fakehome))
        monkeypatch.chdir(nested)

        assert _find_dotenv_file() == config_env


# ===========================================================================
# Test: credential logging is quiet for read-only invocations
# ===========================================================================


class TestCredentialLogging:
    """The no-credentials WARNING should not fire for --version/--help runs."""

    def test_no_creds_warns_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A normal credential-less run still emits the WARNING trace."""
        fakehome = tmp_path / "fakehome"
        fakehome.mkdir()
        workdir = tmp_path / "barren"
        workdir.mkdir()
        monkeypatch.setenv("HOME", str(fakehome))
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_ACCESS_TOKEN", raising=False)
        monkeypatch.chdir(workdir)

        with caplog.at_level(logging.DEBUG, logger="forkhub.config"):
            load_dotenv_file()

        assert any(r.levelno == logging.WARNING for r in caplog.records)

    def test_log_credentials_false_suppresses_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """log_credentials=False skips the no-creds WARNING (used by --version/--help)."""
        fakehome = tmp_path / "fakehome"
        fakehome.mkdir()
        workdir = tmp_path / "barren"
        workdir.mkdir()
        monkeypatch.setenv("HOME", str(fakehome))
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("CLAUDE_ACCESS_TOKEN", raising=False)
        monkeypatch.chdir(workdir)

        with caplog.at_level(logging.DEBUG, logger="forkhub.config"):
            load_dotenv_file(log_credentials=False)

        assert not any(r.levelno == logging.WARNING for r in caplog.records)

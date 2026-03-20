# ABOUTME: Tests for the ForkHub configuration system.
# ABOUTME: Verifies TOML loading, env var overrides, search order, defaults, and helper functions.
from __future__ import annotations

from typing import TYPE_CHECKING

from forkhub.config import (
    AnthropicSettings,
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

# ABOUTME: Tests for the ForkHub configuration system.
# ABOUTME: Verifies TOML loading, env var overrides, search order, defaults, and helper functions.
from __future__ import annotations

from pathlib import Path

import pytest

from forkhub.config import (
    AnalysisSettings,
    AnthropicSettings,
    DatabaseSettings,
    DigestSettings,
    EmbeddingSettings,
    ForkHubSettings,
    GitHubSettings,
    SyncSettings,
    TrackingSettings,
    get_config_dir,
    get_data_dir,
    get_db_path,
    load_settings,
)

# ===========================================================================
# Test: Default values work when no config file exists
# ===========================================================================


class TestDefaultValues:
    """All settings should have sensible defaults when constructed directly."""

    def test_github_defaults(self) -> None:
        settings = GitHubSettings()
        assert settings.token == ""
        assert settings.username == ""

    def test_anthropic_defaults(self) -> None:
        settings = AnthropicSettings()
        assert settings.api_key == ""
        assert settings.analysis_budget_usd == 0.50
        assert settings.model == "sonnet"
        assert settings.digest_model == "haiku"

    def test_database_defaults(self) -> None:
        settings = DatabaseSettings()
        assert settings.path == "~/.local/share/forkhub/forkhub.db"

    def test_sync_defaults(self) -> None:
        settings = SyncSettings()
        assert settings.polling_interval == "6h"
        assert settings.max_forks_per_repo == 5000
        assert settings.max_github_requests_per_hour == 4000

    def test_analysis_defaults(self) -> None:
        settings = AnalysisSettings()
        assert settings.max_deep_dives_per_fork == 10

    def test_embedding_defaults(self) -> None:
        settings = EmbeddingSettings()
        assert settings.provider == "local"
        assert settings.model == "all-MiniLM-L6-v2"

    def test_digest_defaults(self) -> None:
        settings = DigestSettings()
        assert settings.frequency == "weekly"
        assert settings.day_of_week == "monday"
        assert settings.time == "09:00"
        assert settings.min_significance == 5
        assert settings.backends == ["console"]

    def test_tracking_defaults(self) -> None:
        settings = TrackingSettings()
        assert settings.default_fork_depth == 1
        assert settings.auto_discover_owned is True
        assert settings.track_sibling_forks is True

    def test_forkhub_settings_all_defaults(self) -> None:
        settings = ForkHubSettings()
        assert settings.github.token == ""
        assert settings.anthropic.api_key == ""
        assert settings.database.path == "~/.local/share/forkhub/forkhub.db"
        assert settings.sync.polling_interval == "6h"
        assert settings.analysis.max_deep_dives_per_fork == 10
        assert settings.embedding.provider == "local"
        assert settings.digest.frequency == "weekly"
        assert settings.tracking.default_fork_depth == 1


# ===========================================================================
# Test: TOML file is loaded correctly
# ===========================================================================


class TestTomlLoading:
    """Settings should be populated from a TOML config file."""

    @pytest.fixture()
    def toml_file(self, tmp_path: Path) -> Path:
        """Create a test TOML file with various sections populated."""
        content = """\
[github]
token = "ghp_test123"
username = "testuser"

[anthropic]
api_key = "sk-ant-test456"
analysis_budget_usd = 1.25
model = "opus"
digest_model = "sonnet"

[database]
path = "/tmp/test-forkhub.db"

[sync]
polling_interval = "1h"
max_forks_per_repo = 100
max_github_requests_per_hour = 1000

[analysis]
max_deep_dives_per_fork = 5

[embedding]
provider = "voyage"
model = "voyage-code-2"

[digest]
frequency = "daily"
day_of_week = "friday"
time = "17:00"
min_significance = 3
backends = ["console", "email"]

[tracking]
default_fork_depth = 2
auto_discover_owned = false
track_sibling_forks = false
"""
        config_path = tmp_path / "forkhub.toml"
        config_path.write_text(content)
        return config_path

    def test_toml_loads_github_section(self, toml_file: Path) -> None:
        settings = load_settings(config_path=toml_file)
        assert settings.github.token == "ghp_test123"
        assert settings.github.username == "testuser"

    def test_toml_loads_anthropic_section(self, toml_file: Path) -> None:
        settings = load_settings(config_path=toml_file)
        assert settings.anthropic.api_key == "sk-ant-test456"
        assert settings.anthropic.analysis_budget_usd == 1.25
        assert settings.anthropic.model == "opus"
        assert settings.anthropic.digest_model == "sonnet"

    def test_toml_loads_database_section(self, toml_file: Path) -> None:
        settings = load_settings(config_path=toml_file)
        assert settings.database.path == "/tmp/test-forkhub.db"

    def test_toml_loads_sync_section(self, toml_file: Path) -> None:
        settings = load_settings(config_path=toml_file)
        assert settings.sync.polling_interval == "1h"
        assert settings.sync.max_forks_per_repo == 100
        assert settings.sync.max_github_requests_per_hour == 1000

    def test_toml_loads_analysis_section(self, toml_file: Path) -> None:
        settings = load_settings(config_path=toml_file)
        assert settings.analysis.max_deep_dives_per_fork == 5

    def test_toml_loads_embedding_section(self, toml_file: Path) -> None:
        settings = load_settings(config_path=toml_file)
        assert settings.embedding.provider == "voyage"
        assert settings.embedding.model == "voyage-code-2"

    def test_toml_loads_digest_section(self, toml_file: Path) -> None:
        settings = load_settings(config_path=toml_file)
        assert settings.digest.frequency == "daily"
        assert settings.digest.day_of_week == "friday"
        assert settings.digest.time == "17:00"
        assert settings.digest.min_significance == 3
        assert settings.digest.backends == ["console", "email"]

    def test_toml_loads_tracking_section(self, toml_file: Path) -> None:
        settings = load_settings(config_path=toml_file)
        assert settings.tracking.default_fork_depth == 2
        assert settings.tracking.auto_discover_owned is False
        assert settings.tracking.track_sibling_forks is False


# ===========================================================================
# Test: Environment variables override TOML values
# ===========================================================================


class TestEnvVarOverrides:
    """Environment variables should take precedence over TOML file values."""

    @pytest.fixture()
    def toml_file(self, tmp_path: Path) -> Path:
        content = """\
[github]
token = "toml-token"
username = "toml-user"

[anthropic]
api_key = "toml-key"
analysis_budget_usd = 0.50
"""
        config_path = tmp_path / "forkhub.toml"
        config_path.write_text(content)
        return config_path

    def test_env_overrides_github_token(
        self, toml_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "env-token-override")
        settings = load_settings(config_path=toml_file)
        assert settings.github.token == "env-token-override"

    def test_env_overrides_anthropic_api_key(
        self, toml_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-override")
        settings = load_settings(config_path=toml_file)
        assert settings.anthropic.api_key == "env-key-override"

    def test_env_overrides_anthropic_budget(
        self, toml_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_ANALYSIS_BUDGET_USD", "2.50")
        settings = load_settings(config_path=toml_file)
        assert settings.anthropic.analysis_budget_usd == 2.50

    def test_toml_value_preserved_when_no_env_override(
        self, toml_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "env-token")
        # username has no env override, so TOML value should remain
        settings = load_settings(config_path=toml_file)
        assert settings.github.username == "toml-user"

    def test_env_works_without_toml_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "env-only-token")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "env-only-key")
        # Pass a nonexistent path so no TOML is loaded
        settings = load_settings(config_path=Path("/nonexistent/forkhub.toml"))
        assert settings.github.token == "env-only-token"
        assert settings.anthropic.api_key == "env-only-key"


# ===========================================================================
# Test: Config search order (explicit > cwd > ~/.config)
# ===========================================================================


class TestConfigSearchOrder:
    """load_settings should search: explicit path > ./forkhub.toml > ~/.config/forkhub/."""

    def test_explicit_path_takes_priority(self, tmp_path: Path) -> None:
        """An explicit config_path argument should always be used."""
        explicit = tmp_path / "explicit.toml"
        explicit.write_text('[github]\ntoken = "from-explicit"\n')

        cwd_dir = tmp_path / "cwd"
        cwd_dir.mkdir()
        cwd_toml = cwd_dir / "forkhub.toml"
        cwd_toml.write_text('[github]\ntoken = "from-cwd"\n')

        settings = load_settings(config_path=explicit)
        assert settings.github.token == "from-explicit"

    def test_cwd_toml_used_when_no_explicit_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """./forkhub.toml in cwd should be used when no explicit path given."""
        cwd_toml = tmp_path / "forkhub.toml"
        cwd_toml.write_text('[github]\ntoken = "from-cwd"\n')
        monkeypatch.chdir(tmp_path)

        settings = load_settings()
        assert settings.github.token == "from-cwd"

    def test_user_config_dir_used_as_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """~/.config/forkhub/forkhub.toml should be the final fallback."""
        # Set up a fake home config directory
        fake_config = tmp_path / ".config" / "forkhub"
        fake_config.mkdir(parents=True)
        config_toml = fake_config / "forkhub.toml"
        config_toml.write_text('[github]\ntoken = "from-home-config"\n')

        # Make cwd somewhere without a forkhub.toml
        empty_cwd = tmp_path / "empty"
        empty_cwd.mkdir()
        monkeypatch.chdir(empty_cwd)
        monkeypatch.setenv("HOME", str(tmp_path))

        settings = load_settings()
        assert settings.github.token == "from-home-config"

    def test_defaults_when_no_config_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """All defaults should apply when no TOML file is found anywhere."""
        empty_cwd = tmp_path / "empty"
        empty_cwd.mkdir()
        monkeypatch.chdir(empty_cwd)
        # Point HOME to a directory without .config/forkhub/forkhub.toml
        monkeypatch.setenv("HOME", str(tmp_path))

        settings = load_settings()
        assert settings.github.token == ""
        assert settings.anthropic.api_key == ""
        assert settings.sync.polling_interval == "6h"


# ===========================================================================
# Test: Partial TOML files work (only some sections)
# ===========================================================================


class TestPartialToml:
    """A TOML file with only some sections should not break loading."""

    def test_only_github_section(self, tmp_path: Path) -> None:
        toml = tmp_path / "forkhub.toml"
        toml.write_text('[github]\ntoken = "partial-token"\n')
        settings = load_settings(config_path=toml)
        assert settings.github.token == "partial-token"
        # All other sections should have defaults
        assert settings.anthropic.api_key == ""
        assert settings.sync.polling_interval == "6h"
        assert settings.digest.frequency == "weekly"

    def test_empty_toml_file(self, tmp_path: Path) -> None:
        toml = tmp_path / "forkhub.toml"
        toml.write_text("")
        settings = load_settings(config_path=toml)
        assert settings.github.token == ""
        assert settings.anthropic.api_key == ""


# ===========================================================================
# Test: get_db_path helper
# ===========================================================================


class TestGetDbPath:
    """get_db_path should expand ~ and create parent directories."""

    def test_expands_tilde(self) -> None:
        settings = ForkHubSettings()
        db_path = get_db_path(settings)
        # Should not contain ~ anymore
        assert "~" not in str(db_path)
        assert db_path.is_absolute()

    def test_returns_path_object(self) -> None:
        settings = ForkHubSettings()
        db_path = get_db_path(settings)
        assert isinstance(db_path, Path)

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        db_dir = tmp_path / "nested" / "deep" / "dir"
        settings = ForkHubSettings(database=DatabaseSettings(path=str(db_dir / "forkhub.db")))
        db_path = get_db_path(settings)
        assert db_path.parent.exists()
        assert db_path.parent == db_dir

    def test_absolute_path_unchanged(self, tmp_path: Path) -> None:
        explicit_path = str(tmp_path / "my.db")
        settings = ForkHubSettings(database=DatabaseSettings(path=explicit_path))
        db_path = get_db_path(settings)
        assert str(db_path) == explicit_path


# ===========================================================================
# Test: get_config_dir and get_data_dir helpers
# ===========================================================================


class TestDirectoryHelpers:
    """get_config_dir and get_data_dir should return correct paths."""

    def test_get_config_dir_under_home(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        config_dir = get_config_dir()
        assert config_dir == tmp_path / ".config" / "forkhub"
        assert config_dir.exists()

    def test_get_config_dir_creates_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        config_dir = get_config_dir()
        assert config_dir.is_dir()

    def test_get_data_dir_under_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        data_dir = get_data_dir()
        assert data_dir == tmp_path / ".local" / "share" / "forkhub"
        assert data_dir.exists()

    def test_get_data_dir_creates_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        data_dir = get_data_dir()
        assert data_dir.is_dir()


# ===========================================================================
# Test: Nested settings load properly
# ===========================================================================


class TestNestedSettings:
    """Verify nested settings (github.token, anthropic.api_key) load from TOML."""

    def test_deeply_nested_access(self, tmp_path: Path) -> None:
        toml = tmp_path / "forkhub.toml"
        toml.write_text(
            """\
[github]
token = "nested-token"

[anthropic]
api_key = "nested-key"
analysis_budget_usd = 3.14

[digest]
backends = ["email", "discord", "webhook"]
min_significance = 7
"""
        )
        settings = load_settings(config_path=toml)
        assert settings.github.token == "nested-token"
        assert settings.anthropic.api_key == "nested-key"
        assert settings.anthropic.analysis_budget_usd == 3.14
        assert settings.digest.backends == ["email", "discord", "webhook"]
        assert settings.digest.min_significance == 7

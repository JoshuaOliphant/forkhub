# ABOUTME: Configuration system using Pydantic Settings.
# ABOUTME: Loads settings from TOML files and environment variables.
from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Env vars that carry credentials, logged (by name only — never values) at
# startup so a run can never silently proceed unauthenticated without a trace
# of which credential sources were found.
_CREDENTIAL_ENV_VARS = ("GITHUB_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_ACCESS_TOKEN")


class GitHubSettings(BaseSettings):
    """GitHub API connection settings."""

    token: str = ""
    username: str = ""

    model_config = SettingsConfigDict(env_prefix="GITHUB_")


class AnthropicSettings(BaseSettings):
    """Anthropic API settings for agent-based analysis."""

    api_key: str = ""
    oauth_token: str = ""
    analysis_budget_usd: float = 0.50
    model: str = "sonnet"
    digest_model: str = "haiku"

    model_config = SettingsConfigDict(env_prefix="ANTHROPIC_")

    @property
    def has_auth(self) -> bool:
        """Return True if any form of authentication is configured."""
        return bool(self.api_key) or bool(self.oauth_token)

    @property
    def effective_token(self) -> str:
        """Return the active token, preferring api_key over oauth_token."""
        if self.api_key:
            return self.api_key
        return self.oauth_token

    @property
    def auth_method(self) -> str | None:
        """Return which auth method is active, or None if neither."""
        if self.api_key:
            return "api_key"
        if self.oauth_token:
            return "oauth"
        return None


class DatabaseSettings(BaseSettings):
    """SQLite database location settings."""

    path: str = "~/.local/share/forkhub/forkhub.db"

    model_config = SettingsConfigDict(env_prefix="FORKHUB_DATABASE_")


class SyncSettings(BaseSettings):
    """Fork discovery and synchronization settings."""

    polling_interval: str = "6h"
    max_forks_per_repo: int = 5000
    max_github_requests_per_hour: int = 4000

    model_config = SettingsConfigDict(env_prefix="FORKHUB_SYNC_")


class AnalysisSettings(BaseSettings):
    """Agent analysis depth and budget settings."""

    max_deep_dives_per_fork: int = 10

    model_config = SettingsConfigDict(env_prefix="FORKHUB_ANALYSIS_")


class EmbeddingSettings(BaseSettings):
    """Embedding provider configuration for cluster detection."""

    provider: str = "local"  # "local", "voyage", "openai"
    model: str = "all-MiniLM-L6-v2"

    model_config = SettingsConfigDict(env_prefix="FORKHUB_EMBEDDING_")


class DigestSettings(BaseSettings):
    """Notification digest scheduling and delivery settings."""

    frequency: str = "weekly"  # daily, weekly, on_demand
    day_of_week: str = "monday"
    time: str = "09:00"
    min_significance: int = 5
    backends: list[str] = Field(default_factory=lambda: ["console"])

    model_config = SettingsConfigDict(env_prefix="FORKHUB_DIGEST_")


class TrackingSettings(BaseSettings):
    """Fork tracking behavior settings."""

    default_fork_depth: int = 1
    auto_discover_owned: bool = True
    track_sibling_forks: bool = True

    model_config = SettingsConfigDict(env_prefix="FORKHUB_TRACKING_")


class ForkHubSettings(BaseSettings):
    """Top-level settings container that aggregates all subsections."""

    github: GitHubSettings = Field(default_factory=GitHubSettings)
    anthropic: AnthropicSettings = Field(default_factory=AnthropicSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    sync: SyncSettings = Field(default_factory=SyncSettings)
    analysis: AnalysisSettings = Field(default_factory=AnalysisSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    digest: DigestSettings = Field(default_factory=DigestSettings)
    tracking: TrackingSettings = Field(default_factory=TrackingSettings)


def _find_dotenv_file() -> Path | None:
    """Search for a .env file: cwd, then each ancestor dir, then ~/.config/forkhub/.

    Walks upward from the current working directory to the filesystem root the
    way git and ruff resolve their config, so forkhub run from a subdirectory of
    a project still picks up the project's .env. Falls back to the documented
    global location ~/.config/forkhub/.env. Returns the first match, or None.
    """
    cwd = Path.cwd()
    for directory in (cwd, *cwd.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate

    home_env = Path.home() / ".config" / "forkhub" / ".env"
    if home_env.is_file():
        return home_env

    return None


def _log_credential_sources() -> None:
    """Log which credential env vars are populated (names only, never values).

    Surfaces at startup so an unauthenticated run leaves a visible trace instead
    of silently failing later with empty tokens.
    """
    present = [name for name in _CREDENTIAL_ENV_VARS if os.environ.get(name)]
    if present:
        logger.info("Credential sources found: %s", ", ".join(present))
    else:
        logger.warning(
            "No credential env vars set (%s) — requests will be unauthenticated",
            ", ".join(_CREDENTIAL_ENV_VARS),
        )


def load_dotenv_file(dotenv_path: Path | None = None) -> None:
    """Load a .env file into os.environ, then log which credentials were found.

    With no explicit dotenv_path, searches cwd and ancestor dirs, then
    ~/.config/forkhub/.env (see _find_dotenv_file), so forkhub run from any
    directory still discovers credentials. Pass dotenv_path to load a specific
    file. Existing env vars are NOT overridden — .env values only fill in gaps.
    Called once at CLI startup before any settings are loaded.
    """
    from dotenv import load_dotenv

    resolved = dotenv_path if dotenv_path is not None else _find_dotenv_file()
    if resolved is not None:
        logger.info("Loading .env from %s", resolved)
        load_dotenv(dotenv_path=resolved, override=False)
    else:
        logger.debug("No .env file found in cwd, ancestors, or ~/.config/forkhub/")

    _log_credential_sources()


def _find_config_file() -> Path | None:
    """Search for a config file in cwd then ~/.config/forkhub/.

    Returns the first found path, or None if no config file exists.
    """
    # Check current working directory
    cwd_path = Path.cwd() / "forkhub.toml"
    if cwd_path.is_file():
        return cwd_path

    # Check user config directory
    home_path = Path.home() / ".config" / "forkhub" / "forkhub.toml"
    if home_path.is_file():
        return home_path

    return None


def _load_toml(path: Path) -> dict[str, Any]:
    """Read and parse a TOML file, returning an empty dict if the file doesn't exist."""
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _env_prefix_for[T: BaseSettings](settings_cls: type[T]) -> str:
    """Extract the env_prefix from a settings class's model_config."""
    return settings_cls.model_config.get("env_prefix", "")


# Fields where the env var name differs from the standard {prefix}{field} pattern.
_CUSTOM_ENV_VARS: dict[type[BaseSettings], dict[str, str]] = {
    AnthropicSettings: {"oauth_token": "CLAUDE_ACCESS_TOKEN"},
}


def _merge_env_over_toml[T: BaseSettings](
    settings_cls: type[T], toml_section: dict[str, Any]
) -> dict[str, Any]:
    """Merge environment variable values on top of TOML data for a settings class.

    For each field in the settings class, checks if the corresponding env var is
    set (using the class's env_prefix). If the env var exists, its value takes
    precedence over the TOML value. Otherwise the TOML value is kept.

    Some fields have custom env var names (e.g., oauth_token -> CLAUDE_ACCESS_TOKEN).
    These are defined in _CUSTOM_ENV_VARS above.
    """
    merged = dict(toml_section)
    prefix = _env_prefix_for(settings_cls)
    custom = _CUSTOM_ENV_VARS.get(settings_cls, {})

    for field_name in settings_cls.model_fields:
        # Use custom env var name if defined, otherwise follow the prefix convention
        env_key = custom.get(field_name, f"{prefix}{field_name}".upper())
        env_val = os.environ.get(env_key)
        if env_val is not None:
            merged[field_name] = env_val

    return merged


def _build_subsettings[T: BaseSettings](settings_cls: type[T], toml_section: dict[str, Any]) -> T:
    """Construct a subsettings instance with TOML data and env var overrides."""
    merged = _merge_env_over_toml(settings_cls, toml_section)
    return settings_cls(**merged)


def load_settings(config_path: Path | None = None) -> ForkHubSettings:
    """Load settings from TOML file + env vars.

    Search order:
    1. Explicit config_path argument
    2. ./forkhub.toml (current directory)
    3. ~/.config/forkhub/forkhub.toml

    Env vars override TOML values. E.g., GITHUB_TOKEN overrides [github].token.
    """
    # Determine which TOML file to use
    if config_path is not None:
        toml_data = _load_toml(config_path)
    else:
        found = _find_config_file()
        toml_data = _load_toml(found) if found else {}

    return ForkHubSettings(
        github=_build_subsettings(GitHubSettings, toml_data.get("github", {})),
        anthropic=_build_subsettings(AnthropicSettings, toml_data.get("anthropic", {})),
        database=_build_subsettings(DatabaseSettings, toml_data.get("database", {})),
        sync=_build_subsettings(SyncSettings, toml_data.get("sync", {})),
        analysis=_build_subsettings(AnalysisSettings, toml_data.get("analysis", {})),
        embedding=_build_subsettings(EmbeddingSettings, toml_data.get("embedding", {})),
        digest=_build_subsettings(DigestSettings, toml_data.get("digest", {})),
        tracking=_build_subsettings(TrackingSettings, toml_data.get("tracking", {})),
    )


def get_db_path(settings: ForkHubSettings) -> Path:
    """Resolve the database path, expanding ~ and creating parent dirs."""
    db_path = Path(settings.database.path).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return db_path


def get_config_dir() -> Path:
    """Return ~/.config/forkhub/, creating if needed."""
    config_dir = Path.home() / ".config" / "forkhub"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_data_dir() -> Path:
    """Return ~/.local/share/forkhub/, creating if needed."""
    data_dir = Path.home() / ".local" / "share" / "forkhub"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir

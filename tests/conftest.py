# ABOUTME: Shared pytest fixtures for ForkHub tests.
# ABOUTME: Provides in-memory database, sample models, and provider stubs.

import pytest

# Env vars that ForkHub settings classes read. Tests should not be affected
# by values in a developer's real .env file or shell environment.
_FORKHUB_ENV_VARS = [
    "GITHUB_TOKEN",
    "GITHUB_USERNAME",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_OAUTH_TOKEN",
    "CLAUDE_ACCESS_TOKEN",
    "ANTHROPIC_ANALYSIS_BUDGET_USD",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DIGEST_MODEL",
    "FORKHUB_DATABASE_PATH",
    "FORKHUB_SYNC_POLLING_INTERVAL",
    "FORKHUB_SYNC_MAX_FORKS_PER_REPO",
    "FORKHUB_SYNC_MAX_GITHUB_REQUESTS_PER_HOUR",
    "FORKHUB_ANALYSIS_MAX_DEEP_DIVES_PER_FORK",
    "FORKHUB_EMBEDDING_PROVIDER",
    "FORKHUB_EMBEDDING_MODEL",
    "FORKHUB_DIGEST_FREQUENCY",
    "FORKHUB_DIGEST_DAY_OF_WEEK",
    "FORKHUB_DIGEST_TIME",
    "FORKHUB_DIGEST_MIN_SIGNIFICANCE",
    "FORKHUB_DIGEST_BACKENDS",
    "FORKHUB_TRACKING_DEFAULT_FORK_DEPTH",
    "FORKHUB_TRACKING_AUTO_DISCOVER_OWNED",
    "FORKHUB_TRACKING_TRACK_SIBLING_FORKS",
]


@pytest.fixture(autouse=True)
def _clean_forkhub_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip ForkHub-related env vars so tests are isolated from .env files."""
    for var in _FORKHUB_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


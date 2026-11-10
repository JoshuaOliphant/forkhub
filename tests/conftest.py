# ABOUTME: Shared pytest fixtures for ForkHub tests.
# ABOUTME: Provides in-memory database, sample models, and provider stubs.

import json
import os
from datetime import UTC, datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from examples.chatgpt_mcp_cloudflare_access import AccessSettings
from examples.seed_mcp_demo import DEMO_USER, seed
from forkhub.database import Database
from forkhub.mcp_cloudflare_access import AccessPolicy
from forkhub.providers.github import GitHubProvider

from .stubs import (
    StubEmbeddingProvider,
    StubGitProvider,
    StubNotificationBackend,
    make_fork,
    make_tracked_repo,
)

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


@pytest.fixture(scope="session")
def github_acceptance_provider():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")

    def create_provider():
        return GitHubProvider(token)

    return create_provider


@pytest.fixture(autouse=True)
def _no_real_otel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize otel.configure() so tests never wire real OTLP exporters.

    The CLI callback calls otel.configure() at startup; when the OTel SDK is
    installed it would register global providers and spin up background exporter
    threads pointed at a live collector — leaking deprecation warnings and
    cross-test thread exceptions into otherwise-pristine test output. The
    record_* call sites stay live (they no-op without a configured provider).
    """
    import forkhub.otel as otel

    monkeypatch.setattr(otel, "configure", lambda *a, **k: False)


@pytest.fixture
async def db():
    """Provide an in-memory Database connected and schema-created."""
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def provider() -> StubGitProvider:
    """Bare-bones StubGitProvider. Use StubGitProvider.with_testuser_data() for richer data."""
    return StubGitProvider()


@pytest.fixture
def backend() -> StubNotificationBackend:
    return StubNotificationBackend()


@pytest.fixture
def embedding_provider() -> StubEmbeddingProvider:
    return StubEmbeddingProvider()


@pytest.fixture
async def repo_in_db(db: Database) -> dict:
    """Insert and return a tracked repo for use as a foreign key parent."""
    repo = make_tracked_repo()
    await db.insert_tracked_repo(repo)
    return repo


@pytest.fixture
async def fork_in_db(db: Database, repo_in_db: dict) -> dict:
    """Insert and return a fork linked to repo_in_db."""
    fork = make_fork(repo_in_db["id"])
    await db.insert_fork(fork)
    return fork


@pytest.fixture
def access_policy():
    return AccessPolicy(
        issuer="https://forkhub-test.cloudflareaccess.com",
        audience="forkhub-test-audience",
        email="pilot@example.com",
    )


@pytest.fixture(scope="module")
def signing_keys():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public.update(kid="test-key", use="sig", alg="RS256")
    return private_key, {"keys": [public]}


@pytest.fixture
def access_claims(access_policy):
    now = datetime.now(UTC).timestamp()
    return {
        "iss": access_policy.issuer,
        "aud": [access_policy.audience],
        "sub": "cloudflare-pilot-user",
        "email": access_policy.email,
        "type": "app",
        "exp": now + 3600,
        "nbf": now - 60,
    }


@pytest.fixture
def sign_assertion(signing_keys, access_claims):
    def sign(claims=None, headers=None):
        return jwt.encode(
            access_claims if claims is None else claims,
            signing_keys[0],
            algorithm="RS256",
            headers={"kid": "test-key"} if headers is None else headers,
        )

    return sign


@pytest.fixture
async def access_settings(tmp_path, access_policy):
    path = tmp_path / "synthetic.db"
    await seed(path)
    return AccessSettings(policy=access_policy, github_username=DEMO_USER, database_path=str(path))

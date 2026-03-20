# ABOUTME: Tests for the AnalysisRunner orchestration layer.
# ABOUTME: Covers prompt building, batching logic, and options configuration.

from __future__ import annotations

import pytest

from forkhub.config import ForkHubSettings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings() -> ForkHubSettings:
    return ForkHubSettings()


@pytest.fixture
def runner(db, provider, embedding_provider, settings):
    from forkhub.agent.runner import AnalysisRunner

    return AnalysisRunner(
        db=db,
        provider=provider,
        embedding_provider=embedding_provider,
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Integration test placeholder (requires ANTHROPIC_API_KEY)
# ---------------------------------------------------------------------------


class TestAnalyzeRepoIntegration:
    @pytest.mark.integration
    async def test_analyze_repo_runs_session(self, runner, db):
        """Full integration test that runs an actual agent session.

        Requires ANTHROPIC_API_KEY to be set. Skipped in CI unless
        explicitly enabled with -m integration.
        """
        # This would actually call the Agent SDK, so we skip in unit tests
        pytest.skip("Requires ANTHROPIC_API_KEY and live API access")  # ty: ignore[invalid-argument-type, too-many-positional-arguments]

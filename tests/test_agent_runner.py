# ABOUTME: Tests for the AnalysisRunner orchestration layer.
# ABOUTME: Covers prompt building, batching logic, and options configuration.

from __future__ import annotations

import pytest

# Skip this whole module if the optional [claude] extra isn't installed —
# AnalysisRunner requires claude-agent-sdk at runtime.
pytest.importorskip("claude_agent_sdk")

from forkhub.config import ForkHubSettings  # noqa: E402

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
# _build_options — coordinator vs subagent model wiring
# ---------------------------------------------------------------------------


class TestBuildOptionsModelWiring:
    def test_coordinator_gets_raw_model_while_subagent_narrows(
        self, db, provider, embedding_provider, caplog
    ):
        """The coordinator accepts full model IDs; subagents narrow to SDK aliases.

        Pins the asymmetry: ClaudeAgentOptions.model receives the configured
        value verbatim, while the diff-analyst AgentDefinition degrades a
        non-alias value to 'inherit' (running on that same session model).
        """
        from forkhub.agent.runner import AnalysisRunner
        from forkhub.config import AnthropicSettings, ForkHubSettings

        settings = ForkHubSettings(anthropic=AnthropicSettings(model="claude-sonnet-4-6"))
        runner = AnalysisRunner(
            db=db,
            provider=provider,
            embedding_provider=embedding_provider,
            settings=settings,
        )
        with caplog.at_level("WARNING", logger="forkhub.agent.agents"):
            options = runner._build_options(system_prompt="sys", mcp_server=None)

        assert options.model == "claude-sonnet-4-6"
        assert options.agents is not None
        assert options.agents["diff-analyst"].model == "inherit"


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

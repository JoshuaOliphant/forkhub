# ABOUTME: Subagent definitions for the coordinator/specialist pattern.
# ABOUTME: Defines diff-analyst and digest-writer subagents with config-driven models.

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal, cast, get_args

from forkhub.agent.prompts import DIFF_ANALYST_PROMPT, DIGEST_WRITER_PROMPT

if TYPE_CHECKING:
    from forkhub.config import ForkHubSettings

logger = logging.getLogger(__name__)

# The SDK's AgentDefinition only accepts these model aliases for subagents.
# Full model IDs are valid for the coordinator (ClaudeAgentOptions) but not here.
SubagentModel = Literal["sonnet", "opus", "haiku", "inherit"]


def _subagent_model(configured: str) -> SubagentModel:
    """Narrow a configured model name to a valid subagent model alias.

    Falls back to "inherit" (subagent uses the session model) when the
    configured value isn't one of the SDK's accepted aliases, e.g. when
    config specifies a full model ID like "claude-sonnet-4-6".
    """
    if configured in get_args(SubagentModel):
        return cast("SubagentModel", configured)
    logger.warning(
        "Model %r is not a valid subagent alias %s; falling back to 'inherit'",
        configured,
        get_args(SubagentModel),
    )
    return "inherit"


def _build_subagents(settings: ForkHubSettings) -> tuple[Any, Any]:
    """Build the subagent definitions. Requires the 'claude' extra.

    Models come from settings (anthropic.model for the diff-analyst,
    anthropic.digest_model for the digest-writer) so config and env var
    overrides propagate instead of baking in string literals.
    """
    from claude_agent_sdk import AgentDefinition

    diff_analyst = AgentDefinition(
        description="Analyzes a single fork in depth to classify changes into signals",
        prompt=DIFF_ANALYST_PROMPT,
        tools=[
            "mcp__forkhub__get_fork_summary",
            "mcp__forkhub__get_file_diff",
            "mcp__forkhub__get_releases",
            "mcp__forkhub__get_fork_stars",
            "mcp__forkhub__store_signal",
            "mcp__forkhub__search_similar_signals",
        ],
        model=_subagent_model(settings.anthropic.model),
    )
    digest_writer = AgentDefinition(
        description="Composes notification digests from accumulated signals",
        prompt=DIGEST_WRITER_PROMPT,
        model=_subagent_model(settings.anthropic.digest_model),
    )
    return diff_analyst, digest_writer

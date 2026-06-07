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
_SUBAGENT_MODEL_ALIASES = get_args(SubagentModel)


def _subagent_model(configured: str, subagent: str) -> SubagentModel:
    """Narrow a configured model name to a valid subagent model alias.

    Falls back to "inherit" (the subagent runs on the session model) when
    the configured value isn't one of the SDK's accepted aliases, e.g. when
    config specifies a full model ID like "claude-sonnet-4-6". The warning
    names the affected subagent so the user can map it back to the config
    field that set it.
    """
    if configured in _SUBAGENT_MODEL_ALIASES:
        return cast("SubagentModel", configured)
    logger.warning(
        "Configured model %r for the %s subagent is not one of the SDK aliases %s; "
        "the subagent will inherit the session model instead",
        configured,
        subagent,
        _SUBAGENT_MODEL_ALIASES,
    )
    return "inherit"


def _build_subagents(settings: ForkHubSettings) -> tuple[Any, Any]:
    """Build the subagent definitions. Requires the 'claude' extra.

    Models come from settings (anthropic.model for the diff-analyst,
    anthropic.digest_model for the digest-writer) so config and env var
    overrides apply.
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
        model=_subagent_model(settings.anthropic.model, "diff-analyst"),
    )
    digest_writer = AgentDefinition(
        description="Composes notification digests from accumulated signals",
        prompt=DIGEST_WRITER_PROMPT,
        model=_subagent_model(settings.anthropic.digest_model, "digest-writer"),
    )
    return diff_analyst, digest_writer

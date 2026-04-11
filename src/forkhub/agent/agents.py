# ABOUTME: Subagent definitions for the coordinator/specialist pattern.
# ABOUTME: Defines diff-analyst (Sonnet) and digest-writer (Haiku) subagents.

from __future__ import annotations

from typing import Any

from forkhub.agent.prompts import DIFF_ANALYST_PROMPT, DIGEST_WRITER_PROMPT


def _build_subagents() -> tuple[Any, Any]:
    """Build the subagent definitions. Requires the 'claude' extra."""
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
        model="sonnet",
    )
    digest_writer = AgentDefinition(
        description="Composes notification digests from accumulated signals",
        prompt=DIGEST_WRITER_PROMPT,
        model="haiku",
    )
    return diff_analyst, digest_writer

# ABOUTME: Agent SDK hooks for cost tracking and rate limiting.
# ABOUTME: PreToolUse and PostToolUse hooks to guard API usage and log costs.

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from forkhub.database import Database
    from forkhub.interfaces import GitProvider

# Type aliases for hook input/output dicts (Agent SDK uses TypedDicts)
PostToolUseHookInput = dict[str, Any]
PreToolUseHookInput = dict[str, Any]
PreCompactHookInput = dict[str, Any]
SyncHookJSONOutput = dict[str, Any]
HookContext = dict[str, Any]

# Tools that make GitHub API calls and should be rate-limited
GITHUB_API_TOOLS = frozenset(
    {
        "mcp__forkhub__list_forks",
        "mcp__forkhub__get_fork_summary",
        "mcp__forkhub__get_file_diff",
        "mcp__forkhub__get_releases",
        "mcp__forkhub__get_fork_stars",
    }
)


def create_cost_tracker_hook(
    db: Database,
) -> Any:
    """PostToolUse hook: increments API call counter in sync_state.

    Tracks how many times each forkhub MCP tool is invoked during an
    analysis session by storing running counts in the sync_state table.
    """

    async def cost_tracker(
        input_data: PostToolUseHookInput,
        matcher: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        tool_name = input_data["tool_name"]
        if tool_name.startswith("mcp__forkhub__"):
            key = f"tool_calls:{tool_name}"
            current = await db.get_sync_state(key)
            count = int(current) + 1 if current else 1
            await db.set_sync_state(key, str(count))
        return {}

    return cost_tracker


def create_rate_limit_guard_hook(
    provider: GitProvider,
) -> Any:
    """PreToolUse hook: blocks GitHub API tool calls when rate limit is low.

    Checks the provider's current rate limit before allowing tools that
    make GitHub API calls. Blocks when fewer than 100 requests remain,
    directing the agent to work with already-fetched data instead.
    """

    async def rate_limit_guard(
        input_data: PreToolUseHookInput,
        matcher: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        tool_name = input_data["tool_name"]
        if tool_name in GITHUB_API_TOOLS:
            try:
                rate_limit = await provider.get_rate_limit()
                if rate_limit.remaining < 100:
                    return {
                        "decision": "block",
                        "reason": (
                            f"Rate limit low ({rate_limit.remaining} remaining). "
                            "Focus on already-fetched data."
                        ),
                    }
            except Exception:
                pass  # Fail open: don't block on rate limit check failure
        return {}

    return rate_limit_guard


def create_pre_compact_hook() -> Any:
    """PreCompact hook: logs compaction event.

    Analysis progress is safe in the database via store_signal calls,
    so compaction is safe to proceed without intervention.
    """

    async def pre_compact(
        input_data: PreCompactHookInput,
        matcher: str | None,
        context: HookContext,
    ) -> SyncHookJSONOutput:
        # Analysis progress is safe in DB via store_signal calls
        return {}

    return pre_compact

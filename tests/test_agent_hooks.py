# ABOUTME: Tests for Agent SDK hooks (cost tracking and rate limiting).
# ABOUTME: Uses real in-memory SQLite and stub GitProvider for testing.

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.stubs import StubGitProvider

if TYPE_CHECKING:
    from forkhub.database import Database


# ---------------------------------------------------------------------------
# Helper to build hook inputs (TypedDict-like dicts)
# ---------------------------------------------------------------------------


def _make_post_tool_use_input(tool_name: str) -> dict:
    """Build a PostToolUseHookInput dict for testing."""
    return {
        "session_id": "test-session",
        "tool_name": tool_name,
        "tool_input": {},
        "tool_response": "ok",
        "tool_use_id": "tu_123",
        "hook_event_name": "PostToolUse",
    }


def _make_pre_tool_use_input(tool_name: str) -> dict:
    """Build a PreToolUseHookInput dict for testing."""
    return {
        "session_id": "test-session",
        "tool_name": tool_name,
        "tool_input": {},
        "tool_use_id": "tu_456",
        "hook_event_name": "PreToolUse",
    }


# ---------------------------------------------------------------------------
# Cost tracker hook tests
# ---------------------------------------------------------------------------


class TestCostTrackerHook:
    async def test_increments_counter_for_forkhub_tool(self, db: Database):
        """Cost tracker should increment the call counter in sync_state for forkhub tools."""
        from forkhub.agent.hooks import create_cost_tracker_hook

        hook = create_cost_tracker_hook(db)
        input_data = _make_post_tool_use_input("mcp__forkhub__list_forks")

        result = await hook(input_data, None, {})

        # Should return empty dict (allow)
        assert result == {}

        # Should have recorded the call count
        count = await db.get_sync_state("tool_calls:mcp__forkhub__list_forks")
        assert count == "1"


# ---------------------------------------------------------------------------
# Rate limit guard hook tests
# ---------------------------------------------------------------------------


class TestRateLimitGuardHook:
    async def test_allows_on_rate_limit_check_failure(
        self,
        db: Database,
    ):
        """If rate limit check fails, should allow the tool call (fail open)."""
        from forkhub.agent.hooks import create_rate_limit_guard_hook

        provider = StubGitProvider(rate_limit_remaining=5000)
        provider.set_rate_limit_error()
        hook = create_rate_limit_guard_hook(provider)
        input_data = _make_pre_tool_use_input("mcp__forkhub__list_forks")

        result = await hook(input_data, None, {})

        assert result == {}

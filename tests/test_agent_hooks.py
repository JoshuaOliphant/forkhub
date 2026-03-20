# ABOUTME: Tests for Agent SDK hooks (cost tracking and rate limiting).
# ABOUTME: Uses real in-memory SQLite and stub GitProvider for testing.

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.stubs import StubGitProvider

if TYPE_CHECKING:
    from forkhub.database import Database

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def provider() -> StubGitProvider:
    """Provide a StubGitProvider with generous rate limits."""
    return StubGitProvider(rate_limit_remaining=5000)


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

    async def test_increments_counter_multiple_times(self, db: Database):
        """Multiple calls to the same tool should increment the counter each time."""
        from forkhub.agent.hooks import create_cost_tracker_hook

        hook = create_cost_tracker_hook(db)
        input_data = _make_post_tool_use_input("mcp__forkhub__get_fork_summary")

        await hook(input_data, None, {})
        await hook(input_data, None, {})
        await hook(input_data, None, {})

        count = await db.get_sync_state("tool_calls:mcp__forkhub__get_fork_summary")
        assert count == "3"

    async def test_tracks_different_tools_separately(self, db: Database):
        """Different forkhub tools should have separate counters."""
        from forkhub.agent.hooks import create_cost_tracker_hook

        hook = create_cost_tracker_hook(db)

        await hook(_make_post_tool_use_input("mcp__forkhub__list_forks"), None, {})
        await hook(_make_post_tool_use_input("mcp__forkhub__list_forks"), None, {})
        await hook(_make_post_tool_use_input("mcp__forkhub__store_signal"), None, {})

        list_count = await db.get_sync_state("tool_calls:mcp__forkhub__list_forks")
        store_count = await db.get_sync_state("tool_calls:mcp__forkhub__store_signal")
        assert list_count == "2"
        assert store_count == "1"

    async def test_ignores_non_forkhub_tools(self, db: Database):
        """Non-forkhub tools should not be tracked."""
        from forkhub.agent.hooks import create_cost_tracker_hook

        hook = create_cost_tracker_hook(db)
        input_data = _make_post_tool_use_input("some_other_tool")

        result = await hook(input_data, None, {})

        assert result == {}
        # Should not have created any sync state entry
        count = await db.get_sync_state("tool_calls:some_other_tool")
        assert count is None


# ---------------------------------------------------------------------------
# Rate limit guard hook tests
# ---------------------------------------------------------------------------


class TestRateLimitGuardHook:
    async def test_blocks_when_rate_limit_low(self, db: Database, provider: StubGitProvider):
        """Should block GitHub API tools when remaining rate limit is below 100."""
        from forkhub.agent.hooks import create_rate_limit_guard_hook

        provider.set_rate_limit(remaining=50)
        hook = create_rate_limit_guard_hook(provider)
        input_data = _make_pre_tool_use_input("mcp__forkhub__list_forks")

        result = await hook(input_data, None, {})

        assert result["decision"] == "block"
        assert "50 remaining" in result["reason"]

    async def test_allows_when_rate_limit_sufficient(self, db: Database, provider: StubGitProvider):
        """Should allow GitHub API tools when remaining rate limit is >= 100."""
        from forkhub.agent.hooks import create_rate_limit_guard_hook

        provider.set_rate_limit(remaining=500)
        hook = create_rate_limit_guard_hook(provider)
        input_data = _make_pre_tool_use_input("mcp__forkhub__list_forks")

        result = await hook(input_data, None, {})

        assert result == {}

    async def test_allows_at_exactly_100(self, db: Database, provider: StubGitProvider):
        """Should allow when remaining is exactly 100 (boundary case)."""
        from forkhub.agent.hooks import create_rate_limit_guard_hook

        provider.set_rate_limit(remaining=100)
        hook = create_rate_limit_guard_hook(provider)
        input_data = _make_pre_tool_use_input("mcp__forkhub__get_fork_summary")

        result = await hook(input_data, None, {})

        assert result == {}

    async def test_blocks_at_99(self, db: Database, provider: StubGitProvider):
        """Should block when remaining is 99 (just below threshold)."""
        from forkhub.agent.hooks import create_rate_limit_guard_hook

        provider.set_rate_limit(remaining=99)
        hook = create_rate_limit_guard_hook(provider)
        input_data = _make_pre_tool_use_input("mcp__forkhub__get_file_diff")

        result = await hook(input_data, None, {})

        assert result["decision"] == "block"

    async def test_ignores_non_github_api_tools(self, db: Database, provider: StubGitProvider):
        """Non-GitHub-API tools (like store_signal) should not be rate limited."""
        from forkhub.agent.hooks import create_rate_limit_guard_hook

        provider.set_rate_limit(remaining=0)  # Even at zero
        hook = create_rate_limit_guard_hook(provider)
        input_data = _make_pre_tool_use_input("mcp__forkhub__store_signal")

        result = await hook(input_data, None, {})

        assert result == {}

    async def test_ignores_search_similar_signals_tool(
        self, db: Database, provider: StubGitProvider
    ):
        """search_similar_signals is a DB-only tool, not a GitHub API tool."""
        from forkhub.agent.hooks import create_rate_limit_guard_hook

        provider.set_rate_limit(remaining=0)
        hook = create_rate_limit_guard_hook(provider)
        input_data = _make_pre_tool_use_input("mcp__forkhub__search_similar_signals")

        result = await hook(input_data, None, {})

        assert result == {}

    async def test_allows_on_rate_limit_check_failure(
        self, db: Database, provider: StubGitProvider
    ):
        """If rate limit check fails, should allow the tool call (fail open)."""
        from forkhub.agent.hooks import create_rate_limit_guard_hook

        provider.set_rate_limit_error()
        hook = create_rate_limit_guard_hook(provider)
        input_data = _make_pre_tool_use_input("mcp__forkhub__list_forks")

        result = await hook(input_data, None, {})

        assert result == {}

    async def test_blocks_all_github_api_tools(self, db: Database, provider: StubGitProvider):
        """All GitHub API tools should be checked against rate limits."""
        from forkhub.agent.hooks import create_rate_limit_guard_hook

        provider.set_rate_limit(remaining=10)
        hook = create_rate_limit_guard_hook(provider)

        github_api_tools = [
            "mcp__forkhub__list_forks",
            "mcp__forkhub__get_fork_summary",
            "mcp__forkhub__get_file_diff",
            "mcp__forkhub__get_releases",
            "mcp__forkhub__get_fork_stars",
        ]

        for tool_name in github_api_tools:
            input_data = _make_pre_tool_use_input(tool_name)
            result = await hook(input_data, None, {})
            assert result["decision"] == "block", f"{tool_name} should be blocked"

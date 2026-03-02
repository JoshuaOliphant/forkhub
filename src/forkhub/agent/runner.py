# ABOUTME: Analysis orchestration that wraps Agent SDK sessions.
# ABOUTME: Manages agent lifecycle, budget caps, and session batching.

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    create_sdk_mcp_server,
)

from forkhub.agent.agents import diff_analyst
from forkhub.agent.hooks import (
    create_cost_tracker_hook,
    create_pre_compact_hook,
    create_rate_limit_guard_hook,
)
from forkhub.agent.prompts import COORDINATOR_PROMPT

if TYPE_CHECKING:
    from forkhub.config import ForkHubSettings
    from forkhub.database import Database
    from forkhub.interfaces import EmbeddingProvider, GitProvider
    from forkhub.models import Fork, Release, Signal, TrackedRepo

logger = logging.getLogger(__name__)

BATCH_SIZE = 30


class AnalysisRunner:
    """Orchestrates Agent SDK sessions for fork analysis.

    Coordinates the lifecycle of analysis sessions including MCP tool setup,
    hook registration, prompt construction, budget management, and batching
    of large fork sets.
    """

    def __init__(
        self,
        db: Database,
        provider: GitProvider,
        embedding_provider: EmbeddingProvider,
        settings: ForkHubSettings,
    ) -> None:
        self._db = db
        self._provider = provider
        self._embedding_provider = embedding_provider
        self._settings = settings

    async def analyze_repo(
        self,
        repo: TrackedRepo,
        changed_forks: list[Fork],
        new_releases: list[Release],
    ) -> list[Signal]:
        """Run agent analysis session on changed forks.

        Splits large fork sets into batches of 30, runs an Agent SDK
        session for each batch, and collects all signals created during
        the sessions.
        """
        from forkhub.models import Signal

        session_start = datetime.now(tz=UTC)
        all_signals: list[Signal] = []

        batches = self._create_batches(changed_forks)
        if not batches and not new_releases:
            return all_signals

        # If no changed forks but there are releases, run a single session
        if not batches:
            batches = [[]]

        for batch in batches:
            try:
                await self._run_session(repo, batch, new_releases)
            except Exception:
                logger.exception(
                    "Agent session failed for batch of %d forks on %s",
                    len(batch),
                    repo.full_name,
                )

        # Collect all signals created during the analysis sessions
        signal_rows = await self._db.list_signals(repo.id, since=session_start)
        for row in signal_rows:
            files = json.loads(row["files_involved"]) if row["files_involved"] else []
            all_signals.append(
                Signal(
                    id=row["id"],
                    fork_id=row["fork_id"],
                    tracked_repo_id=row["tracked_repo_id"],
                    category=row["category"],
                    summary=row["summary"],
                    detail=row["detail"],
                    files_involved=files,
                    significance=row["significance"],
                    embedding=row["embedding"],
                    is_upstream=bool(row["is_upstream"]),
                    release_tag=row["release_tag"],
                )
            )

        return all_signals

    async def _run_session(
        self,
        repo: TrackedRepo,
        forks: list[Fork],
        releases: list[Release],
    ) -> None:
        """Run a single Agent SDK session for a batch of forks."""
        # Build the tools and MCP server
        tools = self._create_tools()
        mcp_server = create_sdk_mcp_server("forkhub", tools=tools)

        prompt = self._build_coordinator_prompt(repo, forks, releases)
        options = self._build_options(
            system_prompt=COORDINATOR_PROMPT,
            mcp_server=mcp_server,
        )

        client = ClaudeSDKClient(options=options)
        await client.connect()
        try:
            await client.query(prompt=prompt)
            async for msg in client.receive_messages():
                if isinstance(msg, ResultMessage):
                    break
        finally:
            await client.disconnect()

    def _create_tools(self) -> list[Any]:
        """Create the MCP tools for the analysis session.

        Tries to import from the tools module. Returns an empty list
        if the tools module is not yet implemented.
        """
        try:
            from forkhub.agent.tools import create_tools

            return create_tools(self._db, self._provider, self._embedding_provider)
        except (ImportError, AttributeError):
            logger.warning("Agent tools not yet implemented, running with empty tool set")
            return []

    def _build_coordinator_prompt(
        self,
        repo: TrackedRepo,
        changed_forks: list[Fork],
        new_releases: list[Release],
    ) -> str:
        """Build the user prompt with repo context, fork summaries, and releases."""
        lines: list[str] = []

        # Repo context
        lines.append(f"## Repository: {repo.full_name}")
        if repo.description:
            lines.append(f"Description: {repo.description}")
        lines.append(f"Default branch: {repo.default_branch}")
        lines.append("")

        # New releases
        if new_releases:
            lines.append("## New Upstream Releases")
            for release in new_releases:
                lines.append(f"- **{release.tag}** ({release.name})")
                if release.body:
                    # Include the first 200 characters of the release body
                    body_preview = release.body[:200]
                    if len(release.body) > 200:
                        body_preview += "..."
                    lines.append(f"  {body_preview}")
            lines.append("")

        # Changed forks
        if changed_forks:
            lines.append(f"## Changed Forks ({len(changed_forks)} forks to analyze)")
            for fork in changed_forks:
                ahead = fork.commits_ahead
                behind = fork.commits_behind
                stars = fork.stars
                desc = f" - {fork.description}" if fork.description else ""
                lines.append(
                    f"- **{fork.full_name}**: "
                    f"{ahead} commits ahead, {behind} behind, "
                    f"{stars} stars{desc}"
                )
            lines.append("")
        else:
            lines.append("## No Changed Forks")
            lines.append("Focus on analyzing any new upstream releases.")
            lines.append("")

        lines.append(
            "Investigate the changed forks, classify their changes, "
            "and store signals for meaningful findings."
        )

        return "\n".join(lines)

    def _create_batches(self, forks: list[Fork]) -> list[list[Fork]]:
        """Split forks into batches of BATCH_SIZE for session management."""
        if not forks:
            return []
        return [forks[i : i + BATCH_SIZE] for i in range(0, len(forks), BATCH_SIZE)]

    def _build_options(
        self,
        system_prompt: str,
        mcp_server: Any,
    ) -> ClaudeAgentOptions:
        """Build ClaudeAgentOptions with hooks, budget, model, and agents."""
        # Build hooks
        cost_tracker = create_cost_tracker_hook(self._db)
        rate_limit_guard = create_rate_limit_guard_hook(self._provider)
        pre_compact = create_pre_compact_hook()

        mcp_servers: dict[str, Any] = {}
        if mcp_server is not None:
            mcp_servers["forkhub"] = mcp_server

        return ClaudeAgentOptions(
            system_prompt=system_prompt,
            mcp_servers=mcp_servers,
            agents={
                "diff-analyst": diff_analyst,
            },
            hooks={
                "PreToolUse": [
                    HookMatcher(
                        matcher="mcp__forkhub__*",
                        hooks=[rate_limit_guard],
                    ),
                ],
                "PostToolUse": [
                    HookMatcher(
                        matcher="mcp__forkhub__*",
                        hooks=[cost_tracker],
                    ),
                ],
                "PreCompact": [
                    HookMatcher(hooks=[pre_compact]),
                ],
            },
            max_budget_usd=self._settings.anthropic.analysis_budget_usd,
            model=self._settings.anthropic.model,
            permission_mode="bypassPermissions",
            max_turns=50,
        )

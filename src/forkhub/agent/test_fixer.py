# ABOUTME: Test-fixer agent client that suggests edits to failing tests.
# ABOUTME: Uses one-shot Claude SDK queries to analyze failures and return file edits.

from __future__ import annotations

import json
import logging

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, ResultMessage

from forkhub.agent.prompts import TEST_FIXER_PROMPT
from forkhub.models import FixSuggestion

logger = logging.getLogger(__name__)


class TestFixerClient:
    """Calls the Claude SDK to suggest test file edits for failing tests.

    Uses minimal one-shot queries (no MCP tools, no subagents) to keep
    the interaction cheap and bounded. The calling service controls the
    retry loop and safety validation.
    """

    def __init__(self, *, model: str = "haiku", budget_usd: float = 0.10) -> None:
        self._model = model
        self._budget_usd = budget_usd

    async def suggest_fixes(
        self,
        test_output: str,
        patch_summary: str,
        files_patched: list[str],
        test_file_contents: dict[str, str],
    ) -> FixSuggestion:
        """Ask the agent to suggest test file edits that fix failing tests.

        Returns a FixSuggestion with reasoning, edits, and a reject flag.
        On any error (network, parse, budget), returns a rejection suggestion.
        """
        prompt = self._build_prompt(test_output, patch_summary, files_patched, test_file_contents)

        try:
            response_text = await self._query(prompt)
            return self._parse_response(response_text)
        except Exception as exc:
            logger.error("Test fixer agent call failed: %s", exc)
            return FixSuggestion(
                reasoning=f"Agent call failed: {exc}",
                should_reject=True,
            )

    async def _query(self, prompt: str) -> str:
        """Send a one-shot query to the Claude SDK and return the response text."""
        options = ClaudeAgentOptions(
            system_prompt=TEST_FIXER_PROMPT,
            model=self._model,
            max_budget_usd=self._budget_usd,
            permission_mode="bypassPermissions",
            max_turns=1,
        )

        client = ClaudeSDKClient(options=options)
        await client.connect()
        try:
            await client.query(prompt=prompt)
            async for msg in client.receive_messages():
                if isinstance(msg, ResultMessage):
                    return str(getattr(msg, "text", msg))
        finally:
            await client.disconnect()

        return ""

    def _build_prompt(
        self,
        test_output: str,
        patch_summary: str,
        files_patched: list[str],
        test_file_contents: dict[str, str],
    ) -> str:
        """Build the user prompt with all context the agent needs."""
        parts = [
            "## Patch Summary",
            patch_summary,
            "",
            "## Files Modified by Patch",
            "\n".join(f"- {f}" for f in files_patched),
            "",
            "## Test Failure Output",
            "```",
            test_output[-4000:],
            "```",
            "",
        ]

        for path, content in test_file_contents.items():
            parts.extend(
                [
                    f"## Test File: {path}",
                    "```python",
                    content,
                    "```",
                    "",
                ]
            )

        parts.append(
            "Analyze the failures and respond with a JSON object containing "
            "your reasoning, the file edits needed, and whether to reject the patch."
        )

        return "\n".join(parts)

    def _parse_response(self, response_text: str) -> FixSuggestion:
        """Parse the agent's JSON response into a FixSuggestion."""
        # Extract JSON from the response (agent may wrap it in markdown code blocks)
        text = response_text.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()

        data = json.loads(text)
        return FixSuggestion.model_validate(data)

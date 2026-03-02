# ABOUTME: Library-level wrapper around the Agent SDK analysis runner.
# ABOUTME: Provides a clean async interface for triggering fork analysis from services.

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forkhub.agent.runner import AnalysisRunner
    from forkhub.models import Fork, Release, Signal, TrackedRepo


class AnalyzerService:
    """Thin service wrapper around the AnalysisRunner.

    Provides the library-level API for triggering fork analysis. The CLI
    and future consumers (web UI, GitHub Action) call this instead of
    using the runner directly.
    """

    def __init__(self, runner: AnalysisRunner) -> None:
        self._runner = runner

    async def analyze(
        self,
        repo: TrackedRepo,
        changed_forks: list[Fork],
        new_releases: list[Release],
    ) -> list[Signal]:
        """Run analysis on changed forks and return discovered signals."""
        return await self._runner.analyze_repo(repo, changed_forks, new_releases)

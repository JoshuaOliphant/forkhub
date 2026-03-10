# ABOUTME: Agentic backfill service that cherry-picks valuable fork changes.
# ABOUTME: Applies patches, runs tests, and uses an agent to fix test failures.

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from forkhub.models import (
    BackfillAttempt,
    BackfillResult,
    BackfillStatus,
    Signal,
)

if TYPE_CHECKING:
    from forkhub.database import Database
    from forkhub.interfaces import GitProvider

logger = logging.getLogger(__name__)


class BackfillService:
    """Evaluates fork signals and attempts to backfill valuable changes.

    The agentic loop:
    1. Rank signals by significance and cluster membership.
    2. For each candidate: fetch the diff, attempt to apply it.
    3. Run the project test suite to score the result.
    4. If tests fail but the feature looks valuable, attempt test fixes.
    5. Record every attempt as a BackfillAttempt trace for future iterations.
    """

    def __init__(
        self,
        db: Database,
        provider: GitProvider,
        *,
        repo_path: Path | None = None,
        test_command: str = "uv run pytest -x --tb=short -q",
        min_significance: int = 5,
        max_attempts: int = 10,
        auto_fix_tests: bool = True,
    ) -> None:
        self._db = db
        self._provider = provider
        self._repo_path = repo_path or Path.cwd()
        self._test_command = test_command
        self._min_significance = min_significance
        self._max_attempts = max_attempts
        self._auto_fix_tests = auto_fix_tests

    async def run_backfill(
        self,
        repo_id: str,
        *,
        since: datetime | None = None,
        dry_run: bool = False,
    ) -> BackfillResult:
        """Run the backfill loop for a tracked repository.

        Fetches high-value signals, ranks them, and attempts to apply
        each one. Returns a summary of all attempts.
        """
        result = BackfillResult()

        # Gather candidate signals
        candidates = await self._gather_candidates(repo_id, since=since)
        result.total_evaluated = len(candidates)

        if not candidates:
            logger.info("No backfill candidates found for repo %s", repo_id)
            return result

        # Process candidates up to max_attempts
        for signal in candidates[: self._max_attempts]:
            # Skip signals we've already attempted
            if await self._db.has_backfill_for_signal(signal.id):
                continue

            attempt = await self._try_backfill(signal, dry_run=dry_run)
            result.attempted += 1

            if attempt.status == BackfillStatus.ACCEPTED:
                result.accepted += 1
                if attempt.branch_name:
                    result.branches_created.append(attempt.branch_name)
            elif attempt.status == BackfillStatus.PATCH_FAILED:
                result.patch_failed += 1
            elif attempt.status == BackfillStatus.TESTS_FAILED:
                result.tests_failed += 1
            elif attempt.status == BackfillStatus.CONFLICT:
                result.conflicts += 1

        return result

    async def _gather_candidates(
        self,
        repo_id: str,
        since: datetime | None = None,
    ) -> list[Signal]:
        """Query signals and rank by backfill potential.

        Prioritizes by: significance (desc), cluster membership, recency.
        Filters out signals already attempted and those below min_significance.
        """
        since_dt = since or datetime(2000, 1, 1, tzinfo=UTC)
        signal_rows = await self._db.list_signals(repo_id, since=since_dt)

        candidates: list[Signal] = []
        for row in signal_rows:
            if row["significance"] < self._min_significance:
                continue
            # Skip upstream signals — we only backfill fork changes
            if row["is_upstream"]:
                continue

            files = json.loads(row["files_involved"]) if row["files_involved"] else []
            signal = Signal(
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
            candidates.append(signal)

        # Sort by significance descending, then by recency
        candidates.sort(key=lambda s: (-s.significance, s.created_at))
        return candidates

    async def _try_backfill(
        self,
        signal: Signal,
        *,
        dry_run: bool = False,
    ) -> BackfillAttempt:
        """Attempt to backfill a single signal's changes.

        Steps:
        1. Fetch the diff from the fork via provider.
        2. Create a candidate branch.
        3. Apply the patch with `git apply`.
        4. Run the test suite.
        5. If tests fail and auto_fix_tests is enabled, attempt to fix tests.
        6. Record the attempt.
        """
        # Signals without a fork can't be backfilled — skip without recording
        if not signal.fork_id:
            attempt = BackfillAttempt(
                signal_id=signal.id,
                fork_id=signal.fork_id or "",
                tracked_repo_id=signal.tracked_repo_id,
                status=BackfillStatus.PATCH_FAILED,
                error="Signal has no associated fork",
            )
            return attempt

        attempt = BackfillAttempt(
            signal_id=signal.id,
            fork_id=signal.fork_id,
            tracked_repo_id=signal.tracked_repo_id,
            patch_summary=signal.summary,
        )

        fork_row = await self._db.get_fork(signal.fork_id)
        if fork_row is None:
            attempt.status = BackfillStatus.PATCH_FAILED
            attempt.error = f"Fork not found: {signal.fork_id}"
            # Don't record — FK would fail since fork is deleted
            return attempt

        tracked = await self._db.get_tracked_repo(signal.tracked_repo_id)
        if tracked is None:
            attempt.status = BackfillStatus.PATCH_FAILED
            attempt.error = f"Tracked repo not found: {signal.tracked_repo_id}"
            return attempt

        # Fetch the diffs for files involved in this signal
        patches: list[str] = []
        for filepath in signal.files_involved:
            try:
                diff = await self._provider.get_file_diff(
                    tracked["owner"],
                    tracked["name"],
                    f"{tracked['owner']}:{tracked['default_branch']}",
                    f"{fork_row['owner']}:{fork_row['default_branch']}",
                    filepath,
                )
                if diff:
                    patches.append(diff)
            except Exception as exc:
                logger.warning("Failed to fetch diff for %s: %s", filepath, exc)

        if not patches:
            attempt.status = BackfillStatus.PATCH_FAILED
            attempt.error = "No diffs could be fetched for signal files"
            await self._record_attempt(attempt)
            return attempt

        attempt.files_patched = signal.files_involved

        if dry_run:
            attempt.status = BackfillStatus.PENDING
            attempt.patch_summary = f"[dry-run] Would apply {len(patches)} patches"
            await self._record_attempt(attempt)
            return attempt

        # Create a candidate branch
        branch_name = f"backfill/{signal.category}/{fork_row['owner']}-{signal.id[:8]}"
        attempt.branch_name = branch_name

        try:
            # Create branch, apply patch, run tests
            await self._apply_and_test(attempt, patches, branch_name)
        except Exception as exc:
            attempt.status = BackfillStatus.PATCH_FAILED
            attempt.error = str(exc)
            logger.exception("Backfill attempt failed for signal %s", signal.id)
        finally:
            # Always return to the original branch
            await self._run_git("checkout", "-")

        await self._record_attempt(attempt)
        return attempt

    async def _apply_and_test(
        self,
        attempt: BackfillAttempt,
        patches: list[str],
        branch_name: str,
    ) -> None:
        """Create branch, apply patches, and run tests.

        Modifies the attempt in-place with results.
        """
        # Save current branch to return to later
        current_branch = await self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        current_branch = current_branch.strip()

        # Create the candidate branch
        await self._run_git("checkout", "-b", branch_name)

        # Apply each patch
        combined_patch = "\n".join(patches)
        apply_result = await self._run_shell(
            f"echo {_shell_quote(combined_patch)} | git apply --check -",
            cwd=self._repo_path,
        )

        if apply_result.returncode != 0:
            # Patch doesn't apply cleanly
            attempt.status = BackfillStatus.CONFLICT
            attempt.error = f"Patch conflict: {apply_result.stderr}"
            # Clean up the branch
            await self._run_git("checkout", current_branch)
            await self._run_git("branch", "-D", branch_name)
            return

        # Actually apply the patch
        apply_result = await self._run_shell(
            f"echo {_shell_quote(combined_patch)} | git apply -",
            cwd=self._repo_path,
        )

        if apply_result.returncode != 0:
            attempt.status = BackfillStatus.PATCH_FAILED
            attempt.error = f"Patch apply failed: {apply_result.stderr}"
            await self._run_git("checkout", current_branch)
            await self._run_git("branch", "-D", branch_name)
            return

        # Stage and commit the changes
        await self._run_git("add", "-A")
        commit_msg = (
            f"backfill: {attempt.patch_summary}\n\n"
            f"Signal: {attempt.signal_id}\nFork: {attempt.fork_id}"
        )
        await self._run_git("commit", "-m", commit_msg)

        # Run the test suite (the "score")
        test_result = await self._run_tests()
        attempt.test_output = test_result.stdout[-2000:] if test_result.stdout else ""

        if test_result.returncode == 0:
            # Tests pass — accepted!
            attempt.status = BackfillStatus.ACCEPTED
            attempt.score = 1.0
        else:
            # Tests failed — can we fix them?
            if self._auto_fix_tests:
                fixed = await self._attempt_test_fix(attempt, test_result)
                if fixed:
                    attempt.status = BackfillStatus.ACCEPTED
                    attempt.score = 0.8  # Slightly lower score since tests needed fixing
                else:
                    attempt.status = BackfillStatus.TESTS_FAILED
                    attempt.score = 0.0
            else:
                attempt.status = BackfillStatus.TESTS_FAILED
                attempt.score = 0.0

    async def _attempt_test_fix(
        self,
        attempt: BackfillAttempt,
        test_result: subprocess.CompletedProcess,
    ) -> bool:
        """Try to fix failing tests after applying a patch.

        This is where the agentic loop gets interesting: rather than
        rejecting a valuable feature because tests broke, we attempt to
        update the tests to accommodate the new behavior.

        Returns True if tests were successfully fixed.
        """
        # For now, this is a placeholder for the agent-powered test fixer.
        # The full implementation would use the Agent SDK to:
        # 1. Parse the test failure output
        # 2. Read the failing test files
        # 3. Understand the new behavior from the patch
        # 4. Update tests to match the new behavior
        # 5. Re-run tests to verify the fix
        #
        # This keeps the loop bounded (principle 3): max 3 fix attempts,
        # each with a fast test run (principle 2).
        logger.info(
            "Test fix attempt for signal %s (auto_fix_tests enabled)",
            attempt.signal_id,
        )
        return False

    async def _run_tests(self) -> subprocess.CompletedProcess:
        """Run the project test suite and return the result."""
        return await self._run_shell(
            self._test_command,
            cwd=self._repo_path,
            timeout=300,
        )

    async def _run_git(self, *args: str) -> str:
        """Run a git command in the repo directory and return stdout."""
        result = await self._run_shell(
            f"git {' '.join(args)}",
            cwd=self._repo_path,
        )
        return result.stdout or ""

    async def _run_shell(
        self,
        command: str,
        cwd: Path | None = None,
        timeout: int = 120,
    ) -> subprocess.CompletedProcess:
        """Run a shell command asynchronously."""
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd or self._repo_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except TimeoutError:
            proc.kill()
            return subprocess.CompletedProcess(
                args=command,
                returncode=-1,
                stdout="",
                stderr="Command timed out",
            )

        return subprocess.CompletedProcess(
            args=command,
            returncode=proc.returncode or 0,
            stdout=stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else "",
            stderr=stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else "",
        )

    async def _record_attempt(self, attempt: BackfillAttempt) -> None:
        """Persist a backfill attempt to the database (the trace)."""
        attempt_dict = attempt.model_dump()
        attempt_dict["created_at"] = attempt.created_at.isoformat()
        attempt_dict["files_patched"] = json.dumps(attempt.files_patched)
        await self._db.insert_backfill_attempt(attempt_dict)

    async def list_attempts(
        self,
        repo_id: str | None = None,
        status: str | None = None,
    ) -> list[BackfillAttempt]:
        """List backfill attempts, optionally filtered."""
        rows = await self._db.list_backfill_attempts(
            repo_id=repo_id, status=status
        )
        attempts = []
        for row in rows:
            files = json.loads(row["files_patched"]) if row["files_patched"] else []
            attempts.append(
                BackfillAttempt(
                    id=row["id"],
                    signal_id=row["signal_id"],
                    fork_id=row["fork_id"],
                    tracked_repo_id=row["tracked_repo_id"],
                    status=row["status"],
                    branch_name=row["branch_name"],
                    patch_summary=row["patch_summary"],
                    test_output=row["test_output"],
                    error=row["error"],
                    files_patched=files,
                    score=row["score"],
                )
            )
        return attempts


def _shell_quote(s: str) -> str:
    """Quote a string for safe shell embedding."""
    return "'" + s.replace("'", "'\\''") + "'"

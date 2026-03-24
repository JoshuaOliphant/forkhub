# ABOUTME: Agentic backfill service that cherry-picks valuable fork changes.
# ABOUTME: Applies patches, runs tests, and uses an agent to fix test failures.

from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from forkhub.models import (
    BackfillAttempt,
    BackfillResult,
    BackfillStatus,
    Signal,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from forkhub.agent.test_fixer import TestFixerClient
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
        auto_fix_tests: bool = False,
        test_fixer: Any = None,
    ) -> None:
        self._db = db
        self._provider = provider
        self._repo_path = repo_path or Path.cwd()
        self._test_command = test_command
        self._min_significance = min_significance
        self._max_attempts = max_attempts
        self._auto_fix_tests = auto_fix_tests
        self._test_fixer: TestFixerClient | None = test_fixer

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

    async def run_backfill_all(
        self,
        *,
        since: datetime | None = None,
        dry_run: bool = False,
        repo_id: str | None = None,
        on_repo_start: Callable[[str], None] | None = None,
    ) -> BackfillResult:
        """Run backfill across one or all tracked repositories.

        If repo_id is provided, runs only for that repo. Otherwise runs for
        all tracked repos. Aggregates results into a single BackfillResult.
        The optional on_repo_start callback is called with the repo full_name
        before processing each repo, enabling progress reporting.
        """
        if repo_id is not None:
            repo_ids = [repo_id]
        else:
            repos = await self._db.list_tracked_repos()
            repo_ids = [r["id"] for r in repos]

        combined = BackfillResult()
        for rid in repo_ids:
            if on_repo_start is not None:
                repo_row = await self._db.get_tracked_repo(rid)
                name = repo_row["full_name"] if repo_row else rid
                on_repo_start(name)

            result = await self.run_backfill(rid, since=since, dry_run=dry_run)
            combined.total_evaluated += result.total_evaluated
            combined.attempted += result.attempted
            combined.accepted += result.accepted
            combined.patch_failed += result.patch_failed
            combined.tests_failed += result.tests_failed
            combined.conflicts += result.conflicts
            combined.branches_created.extend(result.branches_created)

        return combined

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
            # Skip signals with no associated fork — cannot be backfilled
            if not row["fork_id"]:
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
        3. Apply the patch with git apply.
        4. Run the test suite.
        5. If tests fail and auto_fix_tests is enabled, attempt to fix tests.
        6. Record the attempt.
        """
        attempt = BackfillAttempt(
            signal_id=signal.id,
            fork_id=signal.fork_id or "",
            tracked_repo_id=signal.tracked_repo_id,
            patch_summary=signal.summary,
        )

        fork_row = await self._db.get_fork(signal.fork_id)  # type: ignore[arg-type]
        if fork_row is None:
            attempt.status = BackfillStatus.PATCH_FAILED
            attempt.error = f"Fork not found: {signal.fork_id}"
            logger.warning(
                "Skipping backfill for signal %s: fork %s not found", signal.id, signal.fork_id
            )
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
            except (OSError, ConnectionError, TimeoutError, RuntimeError) as exc:
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
            # Always return to original branch and clean up candidate branch on failure
            try:
                current = (
                    await self._run_safe_cmd(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        cwd=self._repo_path,
                    )
                ).stdout.strip()
                if current == branch_name:
                    await self._run_git("checkout", "-")
                if attempt.status != BackfillStatus.ACCEPTED:
                    check = await self._run_safe_cmd(
                        ["git", "rev-parse", "--verify", branch_name],
                        cwd=self._repo_path,
                    )
                    if check.returncode == 0:
                        await self._run_git("branch", "-D", branch_name)
            except Exception as cleanup_exc:
                logger.error(
                    "Failed to clean up after backfill attempt for signal %s: %s",
                    signal.id,
                    cleanup_exc,
                )

        try:
            await self._record_attempt(attempt)
        except Exception as db_exc:
            logger.error("Failed to record backfill attempt for signal %s: %s", signal.id, db_exc)
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
        # Create the candidate branch
        await self._run_git("checkout", "-b", branch_name)

        # Apply each patch via stdin to avoid shell injection
        combined_patch = "\n".join(patches)
        patch_bytes = combined_patch.encode()

        apply_check = await self._run_safe_cmd(
            ["git", "apply", "--check", "-"],
            cwd=self._repo_path,
            stdin_data=patch_bytes,
        )

        if apply_check.returncode != 0:
            # Patch doesn't apply cleanly — outer finally handles branch cleanup
            attempt.status = BackfillStatus.CONFLICT
            attempt.error = f"Patch conflict: {apply_check.stderr}"
            return

        # Actually apply the patch
        apply_result = await self._run_safe_cmd(
            ["git", "apply", "-"],
            cwd=self._repo_path,
            stdin_data=patch_bytes,
        )

        if apply_result.returncode != 0:
            attempt.status = BackfillStatus.PATCH_FAILED
            attempt.error = f"Patch apply failed: {apply_result.stderr}"
            return

        # Stage only the files touched by this patch (not all working-tree changes)
        await self._run_git("add", "--", *attempt.files_patched)
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

    _MAX_FIX_ROUNDS = 3

    async def _attempt_test_fix(
        self,
        attempt: BackfillAttempt,
        test_result: subprocess.CompletedProcess,
    ) -> bool:
        """Try to fix failing tests after applying a patch.

        Runs a bounded loop (max 3 rounds) where each round:
        1. Parses failing test files from pytest output
        2. Reads their contents from disk
        3. Asks the test-fixer agent for edits
        4. Validates edits target only test files
        5. Writes edits, commits, and re-runs tests

        Returns True if tests pass after any round.
        """
        if self._test_fixer is None:
            logger.warning("auto_fix_tests enabled but no test_fixer configured")
            return False

        for fix_round in range(self._MAX_FIX_ROUNDS):
            logger.info(
                "Test fix round %d/%d for signal %s",
                fix_round + 1,
                self._MAX_FIX_ROUNDS,
                attempt.signal_id,
            )

            # 1. Identify failing test files from pytest output
            failing_files = _parse_failing_test_files(test_result.stdout or "")
            if not failing_files:
                logger.warning("Could not identify failing test files from output")
                return False

            # 2. Read their contents (only test files)
            test_file_contents: dict[str, str] = {}
            for tf in failing_files:
                if not _is_test_file(tf):
                    continue
                path = self._repo_path / tf
                if path.exists():
                    test_file_contents[tf] = path.read_text()

            if not test_file_contents:
                logger.warning("No readable test files found among failing files")
                return False

            # 3. Ask the agent for fix suggestions
            try:
                suggestion = await self._test_fixer.suggest_fixes(
                    test_output=test_result.stdout[-4000:] if test_result.stdout else "",
                    patch_summary=attempt.patch_summary or "",
                    files_patched=attempt.files_patched,
                    test_file_contents=test_file_contents,
                )
            except Exception as exc:
                logger.error("Test fixer call failed: %s", exc)
                attempt.patch_summary = (
                    attempt.patch_summary or ""
                ) + f"\n[fix-round-{fix_round + 1}] Agent error: {exc}"
                return False

            # 4. If agent recommends rejection, bail
            if suggestion.should_reject:
                attempt.patch_summary = (
                    attempt.patch_summary or ""
                ) + f"\n[fix-round-{fix_round + 1}] Rejected: {suggestion.reasoning}"
                return False

            # 5. Validate and apply edits (only test files)
            applied_files: list[str] = []
            for edit in suggestion.edits:
                if not _is_test_file(edit.path):
                    logger.warning("Agent tried to edit non-test file: %s, skipping", edit.path)
                    continue
                try:
                    target = self._repo_path / edit.path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(edit.content)
                    applied_files.append(edit.path)
                except OSError as exc:
                    logger.error("Failed to write %s: %s", edit.path, exc)

            if not applied_files:
                attempt.patch_summary = (
                    attempt.patch_summary or ""
                ) + f"\n[fix-round-{fix_round + 1}] No valid edits to apply"
                return False

            # 6. Stage, commit, and re-run tests
            try:
                await self._run_git("add", "--", *applied_files)
                await self._run_git(
                    "commit", "-m", f"test: fix tests for backfill (round {fix_round + 1})"
                )
            except subprocess.CalledProcessError as exc:
                logger.error("Git commit failed after test fix: %s", exc)
                continue

            test_result = await self._run_tests()
            attempt.test_output = test_result.stdout[-2000:] if test_result.stdout else ""
            attempt.patch_summary = (
                attempt.patch_summary or ""
            ) + f"\n[fix-round-{fix_round + 1}] {suggestion.reasoning}"

            if test_result.returncode == 0:
                return True

        return False

    async def _run_tests(self) -> subprocess.CompletedProcess:
        """Run the project test suite and return the result."""
        args = shlex.split(self._test_command)
        return await self._run_safe_cmd(args, cwd=self._repo_path, timeout=300)

    async def _run_git(self, *args: str) -> str:
        """Run a git command in the repo directory and return stdout.

        Raises subprocess.CalledProcessError if the command exits non-zero.
        """
        result = await self._run_safe_cmd(
            ["git", *args],
            cwd=self._repo_path,
        )
        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                ["git", *args],
                output=result.stdout,
                stderr=result.stderr,
            )
        return result.stdout or ""

    async def _run_exec(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        stdin_data: bytes | None = None,
        timeout: int = 120,
    ) -> subprocess.CompletedProcess:
        """Run a command as an argument list (no shell interpolation).

        Public alias kept for testability; delegates to _run_safe_cmd.
        """
        return await self._run_safe_cmd(args, cwd=cwd, stdin_data=stdin_data, timeout=timeout)

    async def _run_safe_cmd(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        stdin_data: bytes | None = None,
        timeout: int = 120,
    ) -> subprocess.CompletedProcess:
        """Run a command as an argument list using subprocess_exec (no shell interpolation)."""
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE if stdin_data else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd or self._repo_path),
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin_data), timeout=timeout
            )
        except TimeoutError:
            proc.kill()
            await proc.wait()
            logger.error("Command timed out after %ds: %s", timeout, " ".join(str(a) for a in args))
            return subprocess.CompletedProcess(
                args=args,
                returncode=-1,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
            )
        return subprocess.CompletedProcess(
            args=args,
            returncode=proc.returncode if proc.returncode is not None else -1,
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
        rows = await self._db.list_backfill_attempts(repo_id=repo_id, status=status)
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


# ── Module-level helpers ─────────────────────────────────────


# Regex for pytest --tb=short failure lines: "tests/test_foo.py:42: AssertionError"
_PYTEST_FILE_RE = re.compile(r"^([\w./\\-]+\.py):\d+:", re.MULTILINE)


def _is_test_file(path: str) -> bool:
    """Check if a file path looks like a test file (safety gate for edits)."""
    from pathlib import PurePosixPath

    p = PurePosixPath(path)
    name = p.name
    # Must be a .py file
    if not name.endswith(".py"):
        return False
    # File in a tests/ directory, or named test_*.py / *_test.py
    parts = p.parts
    return "tests" in parts or name.startswith("test_") or name.endswith("_test.py")


def _parse_failing_test_files(pytest_output: str) -> list[str]:
    """Extract unique test file paths from pytest --tb=short output."""
    matches = _PYTEST_FILE_RE.findall(pytest_output)
    seen: set[str] = set()
    result: list[str] = []
    for m in matches:
        if m not in seen and _is_test_file(m):
            seen.add(m)
            result.append(m)
    return result

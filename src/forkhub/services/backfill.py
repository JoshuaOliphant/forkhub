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

    from forkhub.database import Database
    from forkhub.interfaces import GitProvider, TestFixer

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
        test_fixer: TestFixer | None = None,
    ) -> None:
        self._db = db
        self._provider = provider
        self._repo_path = repo_path or Path.cwd()
        self._test_command = test_command
        self._min_significance = min_significance
        self._max_attempts = max_attempts
        self._auto_fix_tests = auto_fix_tests
        self._test_fixer: TestFixer | None = test_fixer

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

    @staticmethod
    def _row_to_signal(row: dict) -> Signal:
        """Convert a signals DB row dict into a Signal Pydantic model."""
        files = json.loads(row["files_involved"]) if row["files_involved"] else []
        return Signal(
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

    async def gather_candidates(
        self,
        repo_id: str,
        since: datetime | None = None,
    ) -> list[Signal]:
        """Query signals and rank by backfill potential.

        Prioritizes by: significance (desc), cluster membership, recency.
        Filters out signals below min_significance, upstream signals, and
        signals with no associated fork. Does NOT filter out already-attempted
        signals — callers can check that via db.has_backfill_for_signal.
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
            candidates.append(self._row_to_signal(row))

        # Sort by significance descending, then by recency
        candidates.sort(key=lambda s: (-s.significance, s.created_at))
        return candidates

    # Private alias for back-compat with existing tests
    _gather_candidates = gather_candidates

    async def get_signal_by_id(self, signal_id: str) -> Signal | None:
        """Fetch and hydrate a Signal by id. Returns None if not found."""
        row = await self._db.get_signal(signal_id)
        if row is None:
            return None
        return self._row_to_signal(row)

    async def apply_signal(
        self,
        signal_id: str,
        *,
        dry_run: bool = False,
        keep_branch_on_failure: bool = True,
    ) -> BackfillAttempt:
        """Apply a signal's fork diffs to the local repo and run tests.

        This is the core per-signal primitive. Unlike the autonomous
        run_backfill loop, it preserves the candidate branch on test
        failure by default so an external agent can fix tests on it.

        Steps:
        1. Load the signal.
        2. Fetch diffs from the fork via provider.
        3. Create a candidate branch (errors if branch already exists).
        4. Apply the patch with git apply.
        5. Commit and run the test suite.
        6. On failure: if keep_branch_on_failure, leave the branch alone;
           otherwise delete it (autonomous-loop behavior).
        7. Record the attempt to the database.

        Raises ValueError if the signal is not found.
        """
        signal = await self.get_signal_by_id(signal_id)
        if signal is None:
            raise ValueError(f"Signal not found: {signal_id}")

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

        # Check for branch collision before attempting to create it
        existing = await self._run_safe_cmd(
            ["git", "rev-parse", "--verify", branch_name],
            cwd=self._repo_path,
        )
        if existing.returncode == 0:
            attempt.status = BackfillStatus.CONFLICT
            attempt.error = (
                f"Candidate branch '{branch_name}' already exists. "
                "Run 'forkhub backfill cleanup <prior-attempt-id>' first."
            )
            await self._record_attempt(attempt)
            return attempt

        try:
            # Create branch, apply patch, run tests
            await self._apply_and_test(attempt, patches, branch_name)
        except Exception as exc:
            attempt.status = BackfillStatus.PATCH_FAILED
            attempt.error = str(exc)
            logger.exception("Backfill attempt failed for signal %s", signal.id)
        finally:
            # Always return to original branch for safety.
            # Delete the candidate branch only if NOT accepted AND cleanup requested.
            try:
                current = (
                    await self._run_safe_cmd(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        cwd=self._repo_path,
                    )
                ).stdout.strip()
                if current == branch_name:
                    await self._run_git("checkout", "-")
                if attempt.status != BackfillStatus.ACCEPTED and not keep_branch_on_failure:
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

    async def _try_backfill(
        self,
        signal: Signal,
        *,
        dry_run: bool = False,
    ) -> BackfillAttempt:
        """Legacy path used by run_backfill — delete candidate branch on failure."""
        return await self.apply_signal(
            signal.id,
            dry_run=dry_run,
            keep_branch_on_failure=False,
        )

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
                if path.is_file():
                    try:
                        test_file_contents[tf] = path.read_text(encoding="utf-8", errors="replace")
                    except OSError as exc:
                        logger.warning("Could not read test file %s: %s", tf, exc)

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
                    target = (self._repo_path / edit.path).resolve()
                    repo_root = self._repo_path.resolve()
                    if not target.is_relative_to(repo_root):
                        logger.warning("Path escapes repo root: %s, skipping", edit.path)
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(edit.content, encoding="utf-8")
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

    @staticmethod
    def _row_to_attempt(row: dict) -> BackfillAttempt:
        """Convert a backfill_attempts DB row dict into a BackfillAttempt model."""
        files = json.loads(row["files_patched"]) if row["files_patched"] else []
        return BackfillAttempt(
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

    async def list_attempts(
        self,
        repo_id: str | None = None,
        status: str | None = None,
    ) -> list[BackfillAttempt]:
        """List backfill attempts, optionally filtered."""
        rows = await self._db.list_backfill_attempts(repo_id=repo_id, status=status)
        return [self._row_to_attempt(row) for row in rows]

    async def get_attempt(self, attempt_id: str) -> BackfillAttempt | None:
        """Fetch and hydrate a single BackfillAttempt by id. None if not found."""
        row = await self._db.get_backfill_attempt(attempt_id)
        if row is None:
            return None
        return self._row_to_attempt(row)

    async def record_outcome(
        self,
        attempt_id: str,
        *,
        status: BackfillStatus,
        score: float | None = None,
        notes: str | None = None,
    ) -> BackfillAttempt:
        """Update an attempt's final outcome.

        Used by external agents after they've driven their own fix loop.
        Notes are appended to patch_summary with a [note: ...] marker.
        Raises ValueError if the attempt is not found.
        """
        attempt = await self.get_attempt(attempt_id)
        if attempt is None:
            raise ValueError(f"Backfill attempt not found: {attempt_id}")

        attempt.status = status
        if score is not None:
            attempt.score = score
        if notes:
            existing = attempt.patch_summary or ""
            attempt.patch_summary = f"{existing}\n[note: {notes}]".strip()

        # Persist via update_backfill_attempt (insert uses INSERT, update uses UPDATE)
        attempt_dict = attempt.model_dump()
        attempt_dict["files_patched"] = json.dumps(attempt.files_patched)
        # update_backfill_attempt doesn't touch created_at; remove it from payload
        attempt_dict.pop("created_at", None)
        await self._db.update_backfill_attempt(attempt_dict)
        return attempt

    async def cleanup_attempt(
        self,
        attempt_id: str,
        *,
        keep_branch: bool = False,
    ) -> dict[str, Any]:
        """Return to original branch and optionally delete the candidate branch.

        Returns a dict with {attempt_id, branch_name, branch_deleted, checked_out}.
        Idempotent: does nothing surprising if the branch is already gone.
        Raises ValueError if the attempt is not found.
        """
        attempt = await self.get_attempt(attempt_id)
        if attempt is None:
            raise ValueError(f"Backfill attempt not found: {attempt_id}")

        branch_name = attempt.branch_name
        result: dict[str, Any] = {
            "attempt_id": attempt_id,
            "branch_name": branch_name,
            "branch_deleted": False,
            "checked_out": None,
        }

        if branch_name is None:
            return result

        # Return to original branch if we're currently on the candidate
        current = (
            await self._run_safe_cmd(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self._repo_path,
            )
        ).stdout.strip()
        if current == branch_name:
            try:
                await self._run_git("checkout", "-")
                result["checked_out"] = (
                    await self._run_safe_cmd(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        cwd=self._repo_path,
                    )
                ).stdout.strip()
            except subprocess.CalledProcessError as exc:
                logger.warning("Failed to checkout previous branch: %s", exc)
        else:
            result["checked_out"] = current

        if keep_branch:
            return result

        # Delete the candidate branch if it still exists
        check = await self._run_safe_cmd(
            ["git", "rev-parse", "--verify", branch_name],
            cwd=self._repo_path,
        )
        if check.returncode == 0:
            try:
                await self._run_git("branch", "-D", branch_name)
                result["branch_deleted"] = True
            except subprocess.CalledProcessError as exc:
                logger.warning("Failed to delete candidate branch %s: %s", branch_name, exc)

        return result

    async def run_test_command(self) -> subprocess.CompletedProcess:
        """Run the configured test command. Public wrapper over _run_tests."""
        return await self._run_tests()

    async def read_failing_test_files(
        self,
        test_output: str | None = None,
    ) -> dict[str, Any]:
        """Run tests (if no output passed), parse failing test files, read contents.

        Returns {returncode, test_output, files: [{path, content}]}.
        Only files that pass _is_test_file are included — never production code.
        """
        if test_output is None:
            proc = await self._run_tests()
            returncode = proc.returncode
            output = proc.stdout or ""
        else:
            returncode = 1  # assume failing since caller passed stored output
            output = test_output

        failing = _parse_failing_test_files(output)
        files: list[dict[str, str]] = []
        for tf in failing:
            if not _is_test_file(tf):
                continue
            path = self._repo_path / tf
            if path.is_file():
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                    files.append({"path": tf, "content": content})
                except OSError as exc:
                    logger.warning("Could not read test file %s: %s", tf, exc)

        return {
            "returncode": returncode,
            "test_output": output,
            "files": files,
        }

    def write_test_file(self, path: str, content: str) -> Path:
        """Write content to a test file after safety validation.

        Validates via _is_test_file (rejects '..', absolute paths, non-test
        patterns) AND resolves the final path inside repo_path to catch any
        symlink-based escapes. Raises ValueError if the path is not acceptable.
        """
        if not _is_test_file(path):
            raise ValueError(
                f"Path '{path}' is not a valid test file location. "
                "Must be under tests/ or match test_*.py / *_test.py (no '..' or absolute paths)."
            )

        target = (self._repo_path / path).resolve()
        repo_root = self._repo_path.resolve()
        if not target.is_relative_to(repo_root):
            raise ValueError(f"Resolved path '{target}' escapes repo root '{repo_root}'")

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target


# ── Module-level helpers ─────────────────────────────────────


# Regex for pytest --tb=short failure lines: "tests/test_foo.py:42: AssertionError"
_PYTEST_FILE_RE = re.compile(r"^([\w./\\-]+\.py):\d+:", re.MULTILINE)


def _is_test_file(path: str) -> bool:
    """Check if a file path looks like a test file (safety gate for edits).

    Rejects absolute paths and paths containing '..' to prevent traversal
    attacks where an agent could write to production code via paths like
    'tests/../src/forkhub/models.py'.
    """
    from pathlib import PurePosixPath

    p = PurePosixPath(path)
    # Reject absolute paths and path traversal
    if p.is_absolute() or ".." in p.parts:
        return False
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

# ABOUTME: Targeted coverage tests for services/backfill.py and cli/config_cmd.py.
# ABOUTME: Exercises error paths, git failure modes, and auto-fix branches.

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from forkhub.models import BackfillAttempt, BackfillStatus, FixEdit, FixSuggestion
from forkhub.services.backfill import BackfillService

from .stubs import StubGitProvider, StubTestFixer, make_fork, make_signal, make_tracked_repo

if TYPE_CHECKING:
    from pathlib import Path

    from forkhub.database import Database


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_repo(db: Database) -> dict:
    repo = make_tracked_repo(owner="upstream", name="proj", full_name="upstream/proj")
    await db.insert_tracked_repo(repo)
    return repo


async def _insert_fork(db: Database, repo_id: str, owner: str = "forker1") -> dict:
    fork = make_fork(repo_id, owner=owner, full_name=f"{owner}/proj", vitality="active")
    await db.insert_fork(fork)
    return fork


async def _insert_signal(
    db: Database,
    repo_id: str,
    fork_id: str | None,
    *,
    files: list[str] | None = None,
    significance: int = 8,
    summary: str = "adds caching",
) -> dict:
    sig = make_signal(
        fork_id or "unused",
        repo_id,
        significance=significance,
        summary=summary,
        files_involved=json.dumps(files or ["src/cache.py"]),
    )
    if fork_id is None:
        sig["fork_id"] = None
    await db.insert_signal(sig)
    return sig


def _init_git_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit."""
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    for cmd in [
        ["git", "config", "user.email", "test@test.com"],
        ["git", "config", "user.name", "Test"],
        ["git", "config", "commit.gpgsign", "false"],
    ]:
        subprocess.run(cmd, cwd=str(path), check=True, capture_output=True)
    (path / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=str(path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(path), check=True, capture_output=True)


def _make_failing_result(
    stdout: str = "tests/test_foo.py:1: AssertionError\n",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["pytest"], returncode=1, stdout=stdout, stderr="")


# ---------------------------------------------------------------------------
# run_backfill status aggregation — lines 96-98 (ACCEPTED) and 102 (TESTS_FAILED)
# ---------------------------------------------------------------------------


class TestRunBackfillStatusAggregation:
    async def test_accepted_increments_result_and_records_branch(
        self, tmp_path: Path, db: Database, provider: StubGitProvider
    ) -> None:
        """run_backfill must aggregate ACCEPTED attempts into result.accepted."""
        _init_git_repo(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "cache.py").write_text("old\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add file"], cwd=str(tmp_path), check=True, capture_output=True
        )

        repo = await _insert_repo(db)
        fork = await _insert_fork(db, repo["id"])
        await _insert_signal(db, repo["id"], fork["id"], files=["src/cache.py"])

        valid_diff = "--- a/src/cache.py\n+++ b/src/cache.py\n@@ -1 +1 @@\n-old\n+new\n"
        provider.set_file_diff("forker1", "src/cache.py", valid_diff)

        service = BackfillService(
            db=db,
            provider=provider,
            repo_path=tmp_path,
            min_significance=5,
            test_command="true",
        )
        result = await service.run_backfill(repo["id"])

        assert result.accepted == 1
        assert len(result.branches_created) == 1

    async def test_tests_failed_increments_result(
        self, tmp_path: Path, db: Database, provider: StubGitProvider
    ) -> None:
        """run_backfill must aggregate TESTS_FAILED attempts into result.tests_failed."""
        _init_git_repo(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "cache.py").write_text("old\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add file"], cwd=str(tmp_path), check=True, capture_output=True
        )

        repo = await _insert_repo(db)
        fork = await _insert_fork(db, repo["id"])
        await _insert_signal(db, repo["id"], fork["id"], files=["src/cache.py"])

        valid_diff = "--- a/src/cache.py\n+++ b/src/cache.py\n@@ -1 +1 @@\n-old\n+new\n"
        provider.set_file_diff("forker1", "src/cache.py", valid_diff)

        service = BackfillService(
            db=db,
            provider=provider,
            repo_path=tmp_path,
            min_significance=5,
            test_command="false",
        )
        result = await service.run_backfill(repo["id"])

        assert result.tests_failed == 1


# ---------------------------------------------------------------------------
# apply_signal — line 235 (signal has no fork_id)
# ---------------------------------------------------------------------------


class TestApplySignalNoForkId:
    async def test_raises_when_signal_has_no_fork_id(
        self, db: Database, provider: StubGitProvider
    ) -> None:
        """apply_signal must raise ValueError when the signal has no fork_id."""
        repo = await _insert_repo(db)
        sig = await _insert_signal(db, repo["id"], fork_id=None)

        service = BackfillService(db=db, provider=provider)
        with pytest.raises(ValueError, match="has no associated fork"):
            await service.apply_signal(sig["id"])


# ---------------------------------------------------------------------------
# apply_signal — lines 246-261 (fork not in DB)
# ---------------------------------------------------------------------------


class TestApplySignalForkMissing:
    async def test_returns_patch_failed_when_fork_not_in_db(
        self, db: Database, provider: StubGitProvider
    ) -> None:
        """apply_signal returns PATCH_FAILED when the signal's fork is gone from DB."""
        repo = await _insert_repo(db)
        # Insert signal with a fork_id that does NOT correspond to any fork row.
        # SQLite allows NULL FK values; a non-NULL but unmatched FK needs FK off.
        # Use a fresh UUID that was never inserted into forks.
        import uuid

        fake_fork_id = str(uuid.uuid4())
        sig = make_signal(
            fake_fork_id,
            repo["id"],
            significance=8,
            files_involved=json.dumps(["src/cache.py"]),
        )
        # Temporarily disable FK enforcement so the signal can reference a missing fork.
        await db._db.execute("PRAGMA foreign_keys=OFF")
        await db.insert_signal(sig)
        await db._db.execute("PRAGMA foreign_keys=ON")

        service = BackfillService(db=db, provider=provider)
        attempt = await service.apply_signal(sig["id"])

        assert attempt.status == BackfillStatus.PATCH_FAILED
        assert "Fork not found" in (attempt.error or "")


# ---------------------------------------------------------------------------
# apply_signal — lines 265-275 (tracked_repo not in DB)
# ---------------------------------------------------------------------------


class TestApplySignalTrackedRepoMissing:
    async def test_returns_patch_failed_when_tracked_repo_gone(
        self, db: Database, provider: StubGitProvider
    ) -> None:
        """apply_signal returns PATCH_FAILED when the tracked_repo is gone from DB."""
        import uuid

        repo = await _insert_repo(db)
        fork = await _insert_fork(db, repo["id"])

        # Signal points to a valid fork but a non-existent tracked_repo_id.
        fake_repo_id = str(uuid.uuid4())
        sig = make_signal(
            fork["id"],
            fake_repo_id,
            significance=8,
            files_involved=json.dumps(["src/cache.py"]),
        )
        await db._db.execute("PRAGMA foreign_keys=OFF")
        await db.insert_signal(sig)
        await db._db.execute("PRAGMA foreign_keys=ON")

        service = BackfillService(db=db, provider=provider)
        attempt = await service.apply_signal(sig["id"])

        assert attempt.status == BackfillStatus.PATCH_FAILED
        assert "Tracked repo not found" in (attempt.error or "")


# ---------------------------------------------------------------------------
# apply_signal — lines 290-291 (diff fetch raises exception)
# ---------------------------------------------------------------------------


class TestApplySignalDiffFetchError:
    async def test_exception_during_diff_fetch_is_swallowed(
        self, db: Database, provider: StubGitProvider
    ) -> None:
        """When get_file_diff raises, the exception is caught and patch fails gracefully."""
        repo = await _insert_repo(db)
        fork = await _insert_fork(db, repo["id"])
        await _insert_signal(db, repo["id"], fork["id"], files=["src/cache.py"])

        # Make the stub raise RuntimeError for this file path.
        provider._error_files.add("src/cache.py")

        service = BackfillService(db=db, provider=provider, min_significance=5)
        # All files raised → no patches → PATCH_FAILED
        attempts_before = await db.list_backfill_attempts(repo_id=repo["id"])
        result = await service.run_backfill(repo["id"])

        assert result.patch_failed == 1
        attempts_after = await db.list_backfill_attempts(repo_id=repo["id"])
        assert len(attempts_after) == len(attempts_before) + 1


# ---------------------------------------------------------------------------
# apply_signal — lines 328-331 (_apply_and_test raises outer exception)
# ---------------------------------------------------------------------------


class TestApplySignalOuterExcept:
    async def test_outer_except_caught_when_git_fails_in_apply_and_test(
        self, tmp_path: Path, db: Database, provider: StubGitProvider
    ) -> None:
        """When _apply_and_test raises (git in non-repo dir), apply_signal handles it."""
        # tmp_path is NOT a git repo — git commands will fail with non-zero returncode
        # which causes _run_git to raise CalledProcessError, caught by the outer except.
        repo = await _insert_repo(db)
        fork = await _insert_fork(db, repo["id"])
        await _insert_signal(db, repo["id"], fork["id"], files=["src/cache.py"])

        # Provide a real diff so we pass the patches-empty check and reach _apply_and_test.
        provider.set_file_diff("forker1", "src/cache.py", "some diff content")

        service = BackfillService(db=db, provider=provider, repo_path=tmp_path, min_significance=5)
        attempt = await service.apply_signal((await db.list_signals(repo["id"]))[0]["id"])

        # The outer except sets PATCH_FAILED and records the error message.
        assert attempt.status == BackfillStatus.PATCH_FAILED
        assert attempt.error is not None


# ---------------------------------------------------------------------------
# _apply_and_test — lines 436-446 (auto_fix_tests paths)
# ---------------------------------------------------------------------------


class TestApplyAndTestAutoFix:
    async def test_auto_fix_accepted_when_fixer_succeeds(
        self, tmp_path: Path, db: Database, provider: StubGitProvider
    ) -> None:
        """When auto_fix_tests=True and _attempt_test_fix returns True, status is ACCEPTED (0.8)."""
        _init_git_repo(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "cache.py").write_text("old\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add file"], cwd=str(tmp_path), check=True, capture_output=True
        )

        # Create test file on disk that will be "identified" from test output.
        (tmp_path / "tests").mkdir()
        test_file = tmp_path / "tests" / "test_cache.py"
        test_file.write_text("def test_cache(): assert False\n")

        # State file: first run fails (outputs parseable test failure), second passes.
        state_file = tmp_path / ".run_count"
        state_file.write_text("0")
        runner_script = tmp_path / "_run_tests.py"
        runner_script.write_text(
            f"import sys; from pathlib import Path\n"
            f"p = Path(r'{state_file}')\n"
            f"n = int(p.read_text()) + 1; p.write_text(str(n))\n"
            f"if n == 1:\n"
            f"    print('tests/test_cache.py:1: AssertionError', flush=True); sys.exit(1)\n"
            f"sys.exit(0)\n"
        )

        # Fixer returns an edit that writes the same file content (triggers git commit no-op).
        # We need git commit to succeed, so write DIFFERENT content.
        fixer = StubTestFixer(
            suggestions=[
                FixSuggestion(
                    reasoning="Fixed assertion",
                    edits=[FixEdit(path="tests/test_cache.py", content="def test_cache(): pass\n")],
                )
            ]
        )

        repo = await _insert_repo(db)
        fork = await _insert_fork(db, repo["id"])
        await _insert_signal(db, repo["id"], fork["id"], files=["src/cache.py"])

        valid_diff = "--- a/src/cache.py\n+++ b/src/cache.py\n@@ -1 +1 @@\n-old\n+new\n"
        provider.set_file_diff("forker1", "src/cache.py", valid_diff)

        service = BackfillService(
            db=db,
            provider=provider,
            repo_path=tmp_path,
            min_significance=5,
            auto_fix_tests=True,
            test_fixer=fixer,
            test_command=f"{sys.executable} {runner_script}",
        )
        sig_id = (await db.list_signals(repo["id"]))[0]["id"]
        attempt = await service.apply_signal(sig_id)

        assert attempt.status == BackfillStatus.ACCEPTED
        assert attempt.score == 0.8

    async def test_auto_fix_tests_failed_when_fixer_returns_false(
        self, tmp_path: Path, db: Database, provider: StubGitProvider
    ) -> None:
        """When auto_fix_tests is True and fixer returns False, status is TESTS_FAILED."""
        _init_git_repo(tmp_path)
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "cache.py").write_text("old\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add file"], cwd=str(tmp_path), check=True, capture_output=True
        )

        # test_command always fails with empty output → no parseable failing files
        # → _attempt_test_fix returns False immediately → TESTS_FAILED
        repo = await _insert_repo(db)
        fork = await _insert_fork(db, repo["id"])
        await _insert_signal(db, repo["id"], fork["id"], files=["src/cache.py"])

        valid_diff = "--- a/src/cache.py\n+++ b/src/cache.py\n@@ -1 +1 @@\n-old\n+new\n"
        provider.set_file_diff("forker1", "src/cache.py", valid_diff)

        fixer = StubTestFixer()  # no suggestions → will reject by default
        service = BackfillService(
            db=db,
            provider=provider,
            repo_path=tmp_path,
            min_significance=5,
            auto_fix_tests=True,
            test_fixer=fixer,
            test_command="false",
        )
        sig_id = (await db.list_signals(repo["id"]))[0]["id"]
        attempt = await service.apply_signal(sig_id)

        assert attempt.status == BackfillStatus.TESTS_FAILED
        assert attempt.score == 0.0


# ---------------------------------------------------------------------------
# _attempt_test_fix — lines 491-492 (OSError reading test file)
# ---------------------------------------------------------------------------


class TestAttemptTestFixOSError:
    async def test_oserror_reading_test_file_is_swallowed(
        self, tmp_path: Path, db: Database, provider: StubGitProvider
    ) -> None:
        """OSError reading a test file is caught; test_file_contents stays empty."""
        (tmp_path / "tests").mkdir()
        test_file = tmp_path / "tests" / "test_oserror.py"
        test_file.write_text("content")
        # Make the file unreadable
        test_file.chmod(0o000)

        fixer = StubTestFixer()
        service = BackfillService(
            db=db,
            provider=provider,
            repo_path=tmp_path,
            auto_fix_tests=True,
            test_fixer=fixer,
        )
        attempt = BackfillAttempt(
            signal_id="sig-1",
            fork_id="fork-1",
            tracked_repo_id="repo-1",
            files_patched=["src/cache.py"],
        )
        failing_result = _make_failing_result("tests/test_oserror.py:1: AssertionError\n")

        try:
            result = await service._attempt_test_fix(attempt, failing_result)
            # File unreadable → test_file_contents empty → returns False
            assert result is False
        finally:
            test_file.chmod(0o644)


# ---------------------------------------------------------------------------
# _attempt_test_fix — lines 495-496 (no readable test files)
# ---------------------------------------------------------------------------


class TestAttemptTestFixNoReadableFiles:
    async def test_returns_false_when_test_files_do_not_exist(
        self, tmp_path: Path, db: Database, provider: StubGitProvider
    ) -> None:
        """Returns False when failing test files don't exist on disk."""
        fixer = StubTestFixer()
        service = BackfillService(
            db=db,
            provider=provider,
            repo_path=tmp_path,
            auto_fix_tests=True,
            test_fixer=fixer,
        )
        attempt = BackfillAttempt(
            signal_id="sig-1",
            fork_id="fork-1",
            tracked_repo_id="repo-1",
            files_patched=["src/cache.py"],
        )
        # Output references a test file that doesn't exist in tmp_path.
        failing_result = _make_failing_result("tests/test_nonexistent.py:1: AssertionError\n")
        result = await service._attempt_test_fix(attempt, failing_result)

        assert result is False


# ---------------------------------------------------------------------------
# _attempt_test_fix — lines 506-511 (test_fixer raises)
# ---------------------------------------------------------------------------


class TestAttemptTestFixFixerRaises:
    async def test_returns_false_when_fixer_raises(
        self, tmp_path: Path, db: Database, provider: StubGitProvider
    ) -> None:
        """Returns False when suggest_fixes raises an exception."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_raises.py").write_text("def test_x(): pass\n")

        fixer = StubTestFixer(raise_error=RuntimeError("Simulated fixer failure"))
        service = BackfillService(
            db=db,
            provider=provider,
            repo_path=tmp_path,
            auto_fix_tests=True,
            test_fixer=fixer,
        )
        attempt = BackfillAttempt(
            signal_id="sig-1",
            fork_id="fork-1",
            tracked_repo_id="repo-1",
            patch_summary="caching",
            files_patched=["src/cache.py"],
        )
        failing_result = _make_failing_result("tests/test_raises.py:1: AssertionError\n")
        result = await service._attempt_test_fix(attempt, failing_result)

        assert result is False
        assert "Agent error" in (attempt.patch_summary or "")


# ---------------------------------------------------------------------------
# _attempt_test_fix — lines 530-531 (path escapes repo root via symlink)
# ---------------------------------------------------------------------------


class TestAttemptTestFixPathEscape:
    @pytest.mark.skipif(sys.platform == "win32", reason="symlinks require Unix")
    async def test_symlink_outside_repo_is_skipped(
        self, tmp_path: Path, db: Database, provider: StubGitProvider
    ) -> None:
        """An edit whose resolved path escapes repo_root is skipped silently."""
        (tmp_path / "tests").mkdir()
        test_file = tmp_path / "tests" / "test_escape.py"
        test_file.write_text("original")

        # Create a symlink that resolves outside tmp_path.
        escape_link = tmp_path / "tests" / "test_bad_link.py"
        os.symlink("/tmp", escape_link)

        fixer = StubTestFixer(
            suggestions=[
                FixSuggestion(
                    reasoning="escape attempt",
                    edits=[FixEdit(path="tests/test_bad_link.py", content="evil")],
                )
            ]
        )
        service = BackfillService(
            db=db,
            provider=provider,
            repo_path=tmp_path,
            auto_fix_tests=True,
            test_fixer=fixer,
        )
        attempt = BackfillAttempt(
            signal_id="sig-1",
            fork_id="fork-1",
            tracked_repo_id="repo-1",
            files_patched=["src/cache.py"],
        )
        failing_result = _make_failing_result("tests/test_escape.py:1: AssertionError\n")
        result = await service._attempt_test_fix(attempt, failing_result)

        # Path escape → no applied_files → returns False
        assert result is False


# ---------------------------------------------------------------------------
# _attempt_test_fix — lines 535-536 (OSError writing file)
# ---------------------------------------------------------------------------


class TestAttemptTestFixWriteError:
    async def test_oserror_writing_edit_is_caught(
        self, tmp_path: Path, db: Database, provider: StubGitProvider
    ) -> None:
        """OSError writing an edit file is caught; applied_files stays empty → False."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_write_err.py").write_text("source content\n")

        # Create a directory at the target edit path so write_text fails.
        target_dir = tmp_path / "tests" / "test_oserror_write.py"
        target_dir.mkdir()

        fixer = StubTestFixer(
            suggestions=[
                FixSuggestion(
                    reasoning="write error path",
                    edits=[FixEdit(path="tests/test_oserror_write.py", content="new content")],
                )
            ]
        )
        service = BackfillService(
            db=db,
            provider=provider,
            repo_path=tmp_path,
            auto_fix_tests=True,
            test_fixer=fixer,
        )
        attempt = BackfillAttempt(
            signal_id="sig-1",
            fork_id="fork-1",
            tracked_repo_id="repo-1",
            files_patched=["src/cache.py"],
        )
        failing_result = _make_failing_result("tests/test_write_err.py:1: AssertionError\n")
        result = await service._attempt_test_fix(attempt, failing_result)

        # Write failed → no applied_files → returns False
        assert result is False


# ---------------------------------------------------------------------------
# _attempt_test_fix — lines 550-552 (git commit fails during fix round)
# ---------------------------------------------------------------------------


class TestAttemptTestFixGitCommitFails:
    async def test_git_commit_failure_continues_loop(
        self, tmp_path: Path, db: Database, provider: StubGitProvider
    ) -> None:
        """CalledProcessError from git commit is swallowed and the loop continues."""
        _init_git_repo(tmp_path)
        (tmp_path / "tests").mkdir()
        # Write a test file and commit it so its content is known.
        test_file = tmp_path / "tests" / "test_commit_fail.py"
        test_file.write_text("original_content\n")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add test"],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
        )

        # Identical content → git finds nothing to commit → exit 1 → CalledProcessError.
        fixer = StubTestFixer(
            suggestions=[
                FixSuggestion(
                    reasoning="no-op edit",
                    edits=[FixEdit(path="tests/test_commit_fail.py", content="original_content\n")],
                )
            ]
        )
        service = BackfillService(
            db=db,
            provider=provider,
            repo_path=tmp_path,
            auto_fix_tests=True,
            test_fixer=fixer,
        )
        attempt = BackfillAttempt(
            signal_id="sig-1",
            fork_id="fork-1",
            tracked_repo_id="repo-1",
            files_patched=["src/cache.py"],
        )
        failing_result = _make_failing_result("tests/test_commit_fail.py:1: AssertionError\n")
        result = await service._attempt_test_fix(attempt, failing_result)

        # Commit fails → continue loop → exhausts MAX_FIX_ROUNDS → returns False.
        assert result is False


# ---------------------------------------------------------------------------
# _run_safe_cmd — lines 625-627 (spawn failure)
# ---------------------------------------------------------------------------


class TestRunSafeCmdSpawnFailure:
    async def test_spawn_failure_returns_minus_one_returncode(
        self, tmp_path: Path, db: Database, provider: StubGitProvider
    ) -> None:
        """When the binary does not exist, _run_safe_cmd returns returncode=-1."""
        service = BackfillService(db=db, provider=provider, repo_path=tmp_path)
        result = await service._run_safe_cmd(["/nonexistent_binary_xyz_abc_123"])

        assert result.returncode == -1
        assert "nonexistent_binary" in result.stderr


# ---------------------------------------------------------------------------
# cleanup_attempt — lines 765-768 (rev-parse fails in non-git directory)
# ---------------------------------------------------------------------------


class TestCleanupAttemptGitFails:
    async def test_returns_warning_when_git_rev_parse_fails(
        self, tmp_path: Path, db: Database, provider: StubGitProvider
    ) -> None:
        """cleanup_attempt returns a warnings dict when git rev-parse HEAD fails."""
        repo = await _insert_repo(db)
        fork = await _insert_fork(db, repo["id"])
        sig = await _insert_signal(db, repo["id"], fork["id"])

        attempt = BackfillAttempt(
            signal_id=sig["id"],
            fork_id=fork["id"],
            tracked_repo_id=repo["id"],
            branch_name="backfill/feature/forker1-deadbeef",
        )
        d = attempt.model_dump()
        d["created_at"] = attempt.created_at.isoformat()
        d["files_patched"] = json.dumps(attempt.files_patched)
        await db.insert_backfill_attempt(d)

        # tmp_path is NOT a git repo — rev-parse --abbrev-ref HEAD will fail.
        service = BackfillService(db=db, provider=provider, repo_path=tmp_path)
        result = await service.cleanup_attempt(attempt.id)

        assert len(result["warnings"]) > 0
        assert result["branch_deleted"] is False


# ---------------------------------------------------------------------------
# cleanup_attempt — lines 772-779 (current == branch_name → checkout -)
# ---------------------------------------------------------------------------


class TestCleanupAttemptOnBranch:
    async def test_checks_out_previous_branch_when_on_candidate(
        self, tmp_path: Path, db: Database, provider: StubGitProvider
    ) -> None:
        """When currently on the candidate branch, cleanup_attempt checks out the previous."""
        _init_git_repo(tmp_path)

        branch_name = "backfill/feature/forker1-aabbccdd"
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
        )

        repo = await _insert_repo(db)
        fork = await _insert_fork(db, repo["id"])
        sig = await _insert_signal(db, repo["id"], fork["id"])

        attempt = BackfillAttempt(
            signal_id=sig["id"],
            fork_id=fork["id"],
            tracked_repo_id=repo["id"],
            branch_name=branch_name,
        )
        d = attempt.model_dump()
        d["created_at"] = attempt.created_at.isoformat()
        d["files_patched"] = json.dumps(attempt.files_patched)
        await db.insert_backfill_attempt(d)

        service = BackfillService(db=db, provider=provider, repo_path=tmp_path)
        result = await service.cleanup_attempt(attempt.id, keep_branch=True)

        # Should have checked out the previous branch (main).
        assert result["checked_out"] is not None
        assert result["checked_out"] != branch_name


# ---------------------------------------------------------------------------
# read_failing_test_files — lines 857-858 (OSError reading file)
# ---------------------------------------------------------------------------


class TestReadFailingTestFilesOSError:
    async def test_oserror_reading_file_is_swallowed(
        self, tmp_path: Path, db: Database, provider: StubGitProvider
    ) -> None:
        """OSError reading a failing test file is caught; files list stays empty."""
        (tmp_path / "tests").mkdir()
        unreadable = tmp_path / "tests" / "test_unreadable.py"
        unreadable.write_text("content")
        unreadable.chmod(0o000)

        service = BackfillService(db=db, provider=provider, repo_path=tmp_path)
        try:
            result = await service.read_failing_test_files(
                test_output="tests/test_unreadable.py:1: AssertionError\n",
                returncode=1,
            )
            assert result["files"] == []
        finally:
            unreadable.chmod(0o644)


# ---------------------------------------------------------------------------
# write_test_file — line 882 (path resolves outside repo root via symlink)
# ---------------------------------------------------------------------------


class TestWriteTestFilePathEscape:
    @pytest.mark.skipif(sys.platform == "win32", reason="symlinks require Unix")
    def test_raises_when_path_escapes_repo_root(
        self, tmp_path: Path, db: Database, provider: StubGitProvider
    ) -> None:
        """write_test_file raises ValueError when the resolved path escapes repo_root."""
        (tmp_path / "tests").mkdir()
        # Symlink tests/escape_link.py → /tmp (resolves outside tmp_path).
        os.symlink("/tmp", tmp_path / "tests" / "test_escape_link.py")

        service = BackfillService(db=db, provider=provider, repo_path=tmp_path)
        with pytest.raises(ValueError, match="escapes repo root"):
            service.write_test_file("tests/test_escape_link.py", "content")


# ---------------------------------------------------------------------------
# config_cmd.py — line 106 (config file not found branch)
# ---------------------------------------------------------------------------


class TestConfigPathImplMissingFile:
    async def test_shows_not_found_when_config_file_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """_config_path_impl outputs 'not found' when forkhub.toml doesn't exist."""
        from forkhub.cli.config_cmd import _config_path_impl

        # _config_path_impl imports get_config_dir from forkhub.config at call time.
        # Patch at the source module so the dynamic import picks up the stub.
        monkeypatch.setattr("forkhub.config.get_config_dir", lambda: tmp_path)

        output_lines: list[str] = []
        await _config_path_impl(capture_output=output_lines)

        combined = "\n".join(output_lines)
        assert "not found" in combined.lower()

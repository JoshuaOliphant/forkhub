# ABOUTME: Tests for the agentic test-fixer loop in BackfillService.
# ABOUTME: Uses StubTestFixerClient for all tests — no real API calls.

from __future__ import annotations

import asyncio
import subprocess
from typing import TYPE_CHECKING

from forkhub.models import BackfillAttempt, FixEdit, FixSuggestion
from forkhub.services.backfill import BackfillService, _is_test_file, _parse_failing_test_files

from .stubs import StubTestFixerClient

if TYPE_CHECKING:
    from pathlib import Path

    from forkhub.database import Database


# ---------------------------------------------------------------------------
# _is_test_file
# ---------------------------------------------------------------------------


class TestIsTestFile:
    def test_tests_directory(self):
        assert _is_test_file("tests/test_foo.py") is True

    def test_nested_tests_directory(self):
        assert _is_test_file("tests/unit/test_bar.py") is True

    def test_test_prefix_at_root(self):
        assert _is_test_file("test_something.py") is True

    def test_test_suffix(self):
        assert _is_test_file("something_test.py") is True

    def test_production_file_rejected(self):
        assert _is_test_file("src/forkhub/services/backfill.py") is False

    def test_non_python_rejected(self):
        assert _is_test_file("tests/conftest.yaml") is False

    def test_testing_utils_rejected(self):
        assert _is_test_file("src/testing_utils.py") is False

    def test_conftest_in_tests_accepted(self):
        assert _is_test_file("tests/conftest.py") is True


# ---------------------------------------------------------------------------
# _parse_failing_test_files
# ---------------------------------------------------------------------------


class TestParseFailingTestFiles:
    def test_parses_short_traceback(self):
        output = (
            "FAILED tests/test_foo.py::test_bar - AssertionError\n"
            "tests/test_foo.py:42: AssertionError\n"
            "tests/test_baz.py:10: ValueError\n"
        )
        result = _parse_failing_test_files(output)
        assert result == ["tests/test_foo.py", "tests/test_baz.py"]

    def test_deduplicates_files(self):
        output = "tests/test_foo.py:10: AssertionError\ntests/test_foo.py:20: AssertionError\n"
        result = _parse_failing_test_files(output)
        assert result == ["tests/test_foo.py"]

    def test_excludes_non_test_files(self):
        output = "src/forkhub/models.py:5: TypeError\ntests/test_foo.py:10: AssertionError\n"
        result = _parse_failing_test_files(output)
        assert result == ["tests/test_foo.py"]

    def test_empty_output(self):
        assert _parse_failing_test_files("") == []

    def test_no_failures(self):
        output = "3 passed in 0.5s\n"
        assert _parse_failing_test_files(output) == []


# ---------------------------------------------------------------------------
# Helper: init a git repo in tmp_path
# ---------------------------------------------------------------------------


async def _init_git_repo(path: Path) -> None:
    """Initialize a git repo with an initial commit so git add/commit work."""
    for cmd in [
        ["git", "init"],
        ["git", "config", "user.email", "test@test.com"],
        ["git", "config", "user.name", "Test"],
        ["git", "add", "-A"],
        ["git", "commit", "-m", "initial", "--allow-empty"],
    ]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()


def _make_failing_result(test_file: str = "tests/test_example.py") -> subprocess.CompletedProcess:
    """Create a fake failing test result with parseable pytest output."""
    return subprocess.CompletedProcess(
        args=["pytest"],
        returncode=1,
        stdout=f"{test_file}:1: AssertionError\nFAILED\n",
        stderr="",
    )


# ---------------------------------------------------------------------------
# _attempt_test_fix — happy path
# ---------------------------------------------------------------------------


class TestAttemptTestFixHappyPath:
    async def test_fix_succeeds_round_one(self, db: Database, provider, tmp_path: Path):
        """Agent returns valid edits, tests pass after round 1."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_example.py").write_text("def test_old(): assert 1 == 1\n")

        suggestion = FixSuggestion(
            reasoning="Updated assertion to match new behavior",
            edits=[
                FixEdit(path="tests/test_example.py", content="def test_new(): assert 2 == 2\n")
            ],
        )
        fixer = StubTestFixerClient(suggestions=[suggestion])

        service = BackfillService(
            db=db,
            provider=provider,
            repo_path=tmp_path,
            auto_fix_tests=True,
            test_fixer=fixer,
            test_command="true",
        )

        attempt = BackfillAttempt(
            signal_id="sig-1",
            fork_id="fork-1",
            tracked_repo_id="repo-1",
            patch_summary="Adds caching",
            files_patched=["src/cache.py"],
        )

        await _init_git_repo(tmp_path)
        result = await service._attempt_test_fix(attempt, _make_failing_result())
        assert result is True
        assert fixer.calls[0]["patch_summary"] == "Adds caching"
        assert "[fix-round-1]" in (attempt.patch_summary or "")


# ---------------------------------------------------------------------------
# _attempt_test_fix — rejection
# ---------------------------------------------------------------------------


class TestAttemptTestFixRejection:
    async def test_agent_recommends_rejection(self, db: Database, provider, tmp_path: Path):
        """Agent says should_reject=True, loop bails immediately."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_r.py").write_text("def test_r(): pass\n")

        fixer = StubTestFixerClient(
            suggestions=[FixSuggestion(reasoning="Patch is broken", should_reject=True)]
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
            patch_summary="Bad patch",
            files_patched=["src/b.py"],
        )

        result = await service._attempt_test_fix(attempt, _make_failing_result("tests/test_r.py"))
        assert result is False
        assert "Rejected" in (attempt.patch_summary or "")
        assert "Patch is broken" in (attempt.patch_summary or "")


# ---------------------------------------------------------------------------
# _attempt_test_fix — exhaustion
# ---------------------------------------------------------------------------


class TestAttemptTestFixExhaustion:
    async def test_returns_false_after_max_rounds(self, db: Database, provider, tmp_path: Path):
        """After 3 failed rounds, returns False."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_x.py").write_text("def test_x(): pass\n")

        suggestions = [
            FixSuggestion(
                reasoning=f"Attempt {i}",
                edits=[FixEdit(path="tests/test_x.py", content=f"def test_x(): assert {i}\n")],
            )
            for i in range(3)
        ]
        fixer = StubTestFixerClient(suggestions=suggestions)

        # Test command that always fails but produces parseable pytest-like output
        fail_script = tmp_path / "fail_test.sh"
        fail_script.write_text(
            '#!/bin/sh\necho "tests/test_x.py:1: AssertionError"\necho "FAILED"\nexit 1\n'
        )
        fail_script.chmod(0o755)

        service = BackfillService(
            db=db,
            provider=provider,
            repo_path=tmp_path,
            auto_fix_tests=True,
            test_fixer=fixer,
            test_command=str(fail_script),
        )

        attempt = BackfillAttempt(
            signal_id="sig-1",
            fork_id="fork-1",
            tracked_repo_id="repo-1",
            patch_summary="Change",
            files_patched=["src/a.py"],
        )

        await _init_git_repo(tmp_path)
        result = await service._attempt_test_fix(attempt, _make_failing_result("tests/test_x.py"))
        assert result is False
        assert len(fixer.calls) == 3


# ---------------------------------------------------------------------------
# _attempt_test_fix — safety gate
# ---------------------------------------------------------------------------


class TestAttemptTestFixSafety:
    async def test_production_file_edit_skipped(self, db: Database, provider, tmp_path: Path):
        """Agent tries to edit a production file — edit is rejected."""
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        (test_dir / "test_s.py").write_text("def test_s(): pass\n")

        fixer = StubTestFixerClient(
            suggestions=[
                FixSuggestion(
                    reasoning="Need to fix production code",
                    edits=[FixEdit(path="src/forkhub/models.py", content="# hacked\n")],
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
            patch_summary="Change",
            files_patched=["src/a.py"],
        )

        result = await service._attempt_test_fix(attempt, _make_failing_result("tests/test_s.py"))
        assert result is False
        assert not (tmp_path / "src" / "forkhub" / "models.py").exists()


# ---------------------------------------------------------------------------
# _attempt_test_fix — no fixer configured
# ---------------------------------------------------------------------------


class TestAttemptTestFixNoFixer:
    async def test_returns_false_without_fixer(self, db: Database, provider):
        """If no test_fixer is set, returns False immediately."""
        service = BackfillService(
            db=db,
            provider=provider,
            auto_fix_tests=True,
            test_fixer=None,
        )

        attempt = BackfillAttempt(
            signal_id="sig-1",
            fork_id="fork-1",
            tracked_repo_id="repo-1",
        )
        test_result = subprocess.CompletedProcess(
            args=["pytest"],
            returncode=1,
            stdout="fail\n",
            stderr="",
        )

        result = await service._attempt_test_fix(attempt, test_result)
        assert result is False


# ---------------------------------------------------------------------------
# _attempt_test_fix — no test files identified
# ---------------------------------------------------------------------------


class TestAttemptTestFixNoFiles:
    async def test_returns_false_when_no_files_parsed(self, db: Database, provider, tmp_path: Path):
        """If pytest output doesn't contain test file paths, returns False."""
        fixer = StubTestFixerClient(suggestions=[])

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
        )
        test_result = subprocess.CompletedProcess(
            args=["pytest"],
            returncode=1,
            stdout="ERROR: no tests found\n",
            stderr="",
        )

        result = await service._attempt_test_fix(attempt, test_result)
        assert result is False
        assert len(fixer.calls) == 0


# ---------------------------------------------------------------------------
# FixSuggestion model
# ---------------------------------------------------------------------------


class TestFixSuggestionModel:
    def test_defaults(self):
        s = FixSuggestion(reasoning="test")
        assert s.edits == []
        assert s.should_reject is False

    def test_with_edits(self):
        s = FixSuggestion(
            reasoning="fix",
            edits=[FixEdit(path="tests/test_a.py", content="pass")],
        )
        assert len(s.edits) == 1
        assert s.edits[0].path == "tests/test_a.py"

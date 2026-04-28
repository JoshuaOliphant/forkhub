# ABOUTME: Tests for the agentic test-fixer loop in BackfillService.
# ABOUTME: Uses StubTestFixer for all tests — no real API calls.

from __future__ import annotations

import asyncio
import subprocess
from typing import TYPE_CHECKING

import pytest

from forkhub.models import BackfillAttempt, FixEdit, FixSuggestion
from forkhub.services.backfill import BackfillService, _is_test_file, _parse_failing_test_files

from .stubs import StubAnalyzer, StubTestFixer

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

    def test_path_traversal_rejected(self):
        assert _is_test_file("tests/../src/forkhub/models.py") is False

    def test_absolute_path_rejected(self):
        assert _is_test_file("/etc/passwd") is False

    def test_double_dot_in_middle_rejected(self):
        assert _is_test_file("tests/unit/../../src/bad.py") is False


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
        ["git", "config", "commit.gpgsign", "false"],
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
        fixer = StubTestFixer(suggestions=[suggestion])

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

        fixer = StubTestFixer(
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
        fixer = StubTestFixer(suggestions=suggestions)

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

        fixer = StubTestFixer(
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
        fixer = StubTestFixer(suggestions=[])

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


# ---------------------------------------------------------------------------
# TestFixer protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_stub_conforms_to_protocol(self):
        """StubTestFixer must be recognized as a TestFixer at runtime."""
        from forkhub.interfaces import TestFixer

        stub = StubTestFixer()
        assert isinstance(stub, TestFixer)

    def test_claude_fixer_conforms_to_protocol(self):
        """ClaudeTestFixer must be recognized as a TestFixer at runtime.

        Skipped when the [claude] extra isn't installed (ClaudeTestFixer
        raises ImportError in __init__ in that case).
        """
        pytest.importorskip("claude_agent_sdk")

        from forkhub.agent.test_fixer import ClaudeTestFixer
        from forkhub.interfaces import TestFixer

        fixer = ClaudeTestFixer()
        assert isinstance(fixer, TestFixer)


class TestAnalyzerProtocolConformance:
    def test_stub_analyzer_conforms_to_protocol(self):
        """StubAnalyzer must be recognized as an Analyzer at runtime."""
        from forkhub.interfaces import Analyzer

        stub = StubAnalyzer()
        assert isinstance(stub, Analyzer)

    async def test_claude_analyzer_conforms_to_protocol(self, db):
        """ClaudeAnalyzer must be recognized as an Analyzer at runtime.

        Skipped when the [claude] extra isn't installed (ClaudeAnalyzer
        raises ImportError in __init__ in that case).
        """
        pytest.importorskip("claude_agent_sdk")

        from forkhub.agent.runner import ClaudeAnalyzer
        from forkhub.config import ForkHubSettings
        from forkhub.interfaces import Analyzer

        from .stubs import StubEmbeddingProvider, StubGitProvider

        analyzer = ClaudeAnalyzer(
            db=db,
            provider=StubGitProvider(),
            embedding_provider=StubEmbeddingProvider(),
            settings=ForkHubSettings(),
        )
        assert isinstance(analyzer, Analyzer)

    def test_analysis_runner_back_compat_alias(self):
        """The old `AnalysisRunner` name must still point at ClaudeAnalyzer."""
        pytest.importorskip("claude_agent_sdk")

        from forkhub.agent.runner import AnalysisRunner, ClaudeAnalyzer

        assert AnalysisRunner is ClaudeAnalyzer


# ---------------------------------------------------------------------------
# Optional claude extra — graceful degradation
# ---------------------------------------------------------------------------


class TestOptionalClaudeExtra:
    def test_claude_fixer_raises_helpful_error_without_sdk(self, monkeypatch):
        """ClaudeTestFixer should raise ImportError with install instructions
        when claude-agent-sdk is not available."""
        import forkhub.agent.test_fixer as tf_mod

        # Simulate the SDK being unavailable
        monkeypatch.setattr(tf_mod, "_CLAUDE_SDK_AVAILABLE", False)

        with pytest.raises(ImportError, match="claude"):
            tf_mod.ClaudeTestFixer()

    def test_claude_analyzer_raises_helpful_error_without_sdk(self, monkeypatch):
        """ClaudeAnalyzer should raise ImportError with install instructions
        when claude-agent-sdk is not available."""
        import forkhub.agent.runner as runner_mod

        monkeypatch.setattr(runner_mod, "_CLAUDE_SDK_AVAILABLE", False)

        with pytest.raises(ImportError, match="claude"):
            runner_mod.ClaudeAnalyzer(
                db=None,  # type: ignore[arg-type]
                provider=None,  # type: ignore[arg-type]
                embedding_provider=None,  # type: ignore[arg-type]
                settings=None,  # type: ignore[arg-type]
            )

    async def test_forkhub_facade_degrades_when_sdk_unavailable(self, monkeypatch):
        """ForkHub() with auto_analyze=True must not crash when the SDK
        isn't installed — analyzer should silently be None."""
        import forkhub.agent.runner as runner_mod

        monkeypatch.setattr(runner_mod, "_CLAUDE_SDK_AVAILABLE", False)

        from forkhub import ForkHub
        from forkhub.config import ForkHubSettings
        from forkhub.database import Database

        db = Database(":memory:")
        hub = ForkHub(settings=ForkHubSettings(), db=db, auto_analyze=True)
        assert hub._analyzer is None

    def test_core_modules_importable_without_sdk(self):
        """Core forkhub modules must import without claude-agent-sdk.

        This test verifies nothing in the main import path eagerly imports
        claude_agent_sdk at module load time.
        """
        # These imports must all succeed regardless of SDK availability
        import forkhub  # noqa: F401
        from forkhub import ForkHub  # noqa: F401
        from forkhub.interfaces import (  # noqa: F401
            EmbeddingProvider,
            GitProvider,
            NotificationBackend,
            TestFixer,
        )
        from forkhub.models import FixEdit, FixSuggestion  # noqa: F401
        from forkhub.services.backfill import BackfillService  # noqa: F401

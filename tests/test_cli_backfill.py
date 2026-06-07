# ABOUTME: CLI integration tests for the forkhub backfill sub-app primitives.
# ABOUTME: Exercises candidates/apply/status/record/cleanup/read-failures/write-test/run-tests.

from __future__ import annotations

import json
import subprocess as sp
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from forkhub.cli.app import app
from forkhub.cli.backfill_cmd import (
    _apply_impl,
    _candidates_impl,
    _cleanup_impl,
    _read_failures_impl,
    _record_impl,
    _run_tests_impl,
    _status_impl,
    _write_test_impl,
)
from forkhub.models import BackfillAttempt, BackfillStatus

if TYPE_CHECKING:
    from pathlib import Path

    from forkhub.database import Database
    from tests.stubs import StubGitProvider

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers — reused from test_backfill.py patterns
# ---------------------------------------------------------------------------


def _init_git_repo(tmp_path: Path) -> None:
    """Initialize a git repo with an initial commit."""
    sp.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    sp.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    sp.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    sp.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=str(tmp_path),
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("hello\n")
    sp.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
    sp.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), check=True, capture_output=True)


async def _seed_tracked_repo(db: Database, owner: str = "upstream", name: str = "project") -> dict:
    from tests.stubs import make_tracked_repo

    repo = make_tracked_repo(owner=owner, name=name, full_name=f"{owner}/{name}", github_id=1001)
    await db.insert_tracked_repo(repo)
    return repo


async def _seed_fork(
    db: Database, tracked_repo_id: str, owner: str = "forker1", github_id: int = 5001
) -> dict:
    from datetime import UTC, datetime

    from tests.stubs import make_fork

    fork = make_fork(
        tracked_repo_id,
        owner=owner,
        full_name=f"{owner}/project",
        github_id=github_id,
        vitality="active",
        stars=10,
        last_pushed_at=datetime(2025, 5, 1, tzinfo=UTC).isoformat(),
    )
    await db.insert_fork(fork)
    return fork


async def _seed_signal(
    db: Database,
    tracked_repo_id: str,
    fork_id: str,
    significance: int = 7,
    files: list[str] | None = None,
    summary: str = "Adds caching",
) -> dict:
    from tests.stubs import make_signal

    sig = make_signal(
        fork_id,
        tracked_repo_id,
        significance=significance,
        summary=summary,
        files_involved=json.dumps(files or ["src/cache.py"]),
    )
    await db.insert_signal(sig)
    return sig


async def _seed_attempt(
    db: Database,
    signal_id: str,
    fork_id: str,
    tracked_repo_id: str,
    status: BackfillStatus = BackfillStatus.PENDING,
    branch_name: str | None = None,
) -> BackfillAttempt:
    attempt = BackfillAttempt(
        signal_id=signal_id,
        fork_id=fork_id,
        tracked_repo_id=tracked_repo_id,
        status=status,
        branch_name=branch_name,
        patch_summary="test attempt",
    )
    d = attempt.model_dump()
    d["created_at"] = attempt.created_at.isoformat()
    d["files_patched"] = json.dumps(attempt.files_patched)
    await db.insert_backfill_attempt(d)
    return attempt


# ---------------------------------------------------------------------------
# Smoke tests — CliRunner for help output
# ---------------------------------------------------------------------------


class TestBackfillSubcommandHelp:
    """Verify every subcommand is wired up and renders help without error."""

    @pytest.mark.parametrize(
        "subcommand",
        [
            "run",
            "list",
            "candidates",
            "apply",
            "status",
            "record",
            "cleanup",
            "read-failures",
            "write-test",
            "run-tests",
        ],
    )
    def test_subcommand_help(self, subcommand):
        result = runner.invoke(app, ["backfill", subcommand, "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# candidates
# ---------------------------------------------------------------------------


class TestCandidatesCommand:
    async def test_empty_repo_no_candidates_json(self, db: Database, provider: StubGitProvider):
        """With no signals, --json returns an empty candidates list."""
        await _seed_tracked_repo(db)

        output: list[str] = []
        await _candidates_impl(as_json=True, db=db, provider=provider, capture_output=output)
        payload = json.loads(output[0])
        assert payload["count"] == 0
        assert payload["candidates"] == []

    async def test_returns_signals_above_threshold(self, db: Database, provider: StubGitProvider):
        """Signals at/above min_significance are returned."""
        repo = await _seed_tracked_repo(db)
        fork = await _seed_fork(db, repo["id"])
        await _seed_signal(db, repo["id"], fork["id"], significance=7)
        await _seed_signal(db, repo["id"], fork["id"], significance=3)  # below default 5

        output: list[str] = []
        await _candidates_impl(
            as_json=True,
            min_significance=5,
            db=db,
            provider=provider,
            capture_output=output,
        )
        payload = json.loads(output[0])
        assert payload["count"] == 1
        assert payload["candidates"][0]["significance"] == 7

    async def test_marks_already_attempted(self, db: Database, provider: StubGitProvider):
        """Signals with prior attempts are flagged."""
        repo = await _seed_tracked_repo(db)
        fork = await _seed_fork(db, repo["id"])
        signal = await _seed_signal(db, repo["id"], fork["id"])
        await _seed_attempt(db, signal["id"], fork["id"], repo["id"])

        output: list[str] = []
        await _candidates_impl(as_json=True, db=db, provider=provider, capture_output=output)
        payload = json.loads(output[0])
        assert payload["candidates"][0]["already_attempted"] is True


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


class TestStatusCommand:
    async def test_not_found_returns_1(self, db: Database, provider: StubGitProvider):
        output: list[str] = []
        exit_code = await _status_impl(
            attempt_id="nonexistent",
            db=db,
            provider=provider,
            capture_output=output,
        )
        assert exit_code == 1
        assert any("not found" in line.lower() for line in output)

    async def test_returns_attempt_as_json(self, db: Database, provider: StubGitProvider):
        repo = await _seed_tracked_repo(db)
        fork = await _seed_fork(db, repo["id"])
        signal = await _seed_signal(db, repo["id"], fork["id"])
        attempt = await _seed_attempt(
            db, signal["id"], fork["id"], repo["id"], status=BackfillStatus.TESTS_FAILED
        )

        output: list[str] = []
        exit_code = await _status_impl(
            attempt_id=attempt.id,
            as_json=True,
            db=db,
            provider=provider,
            capture_output=output,
        )
        assert exit_code == 0
        payload = json.loads(output[0])
        assert payload["id"] == attempt.id
        assert payload["status"] == "tests_failed"


# ---------------------------------------------------------------------------
# record
# ---------------------------------------------------------------------------


class TestRecordCommand:
    async def test_invalid_status_returns_2(self, db: Database, provider: StubGitProvider):
        output: list[str] = []
        exit_code = await _record_impl(
            attempt_id="whatever",
            status="not_a_real_status",
            db=db,
            provider=provider,
            capture_output=output,
        )
        assert exit_code == 2

    async def test_unknown_attempt_returns_1(self, db: Database, provider: StubGitProvider):
        output: list[str] = []
        exit_code = await _record_impl(
            attempt_id="nonexistent",
            status="accepted",
            db=db,
            provider=provider,
            capture_output=output,
        )
        assert exit_code == 1

    async def test_updates_status_and_score(self, db: Database, provider: StubGitProvider):
        repo = await _seed_tracked_repo(db)
        fork = await _seed_fork(db, repo["id"])
        signal = await _seed_signal(db, repo["id"], fork["id"])
        attempt = await _seed_attempt(db, signal["id"], fork["id"], repo["id"])

        output: list[str] = []
        exit_code = await _record_impl(
            attempt_id=attempt.id,
            status="accepted",
            score=0.9,
            notes="looks good",
            as_json=True,
            db=db,
            provider=provider,
            capture_output=output,
        )
        assert exit_code == 0
        payload = json.loads(output[0])
        assert payload["status"] == "accepted"
        assert payload["score"] == 0.9
        assert "looks good" in (payload["patch_summary"] or "")


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


class TestApplyCommand:
    async def test_signal_not_found_returns_4(
        self, db: Database, provider: StubGitProvider, tmp_path: Path
    ):
        output: list[str] = []
        exit_code = await _apply_impl(
            signal_id="nonexistent",
            repo_path=str(tmp_path),
            db=db,
            provider=provider,
            capture_output=output,
        )
        assert exit_code == 4

    async def test_fetch_error_returns_3(
        self, db: Database, provider: StubGitProvider, tmp_path: Path
    ):
        """When a file's diff fetch raises, exit code is 3 (fetch_error)."""
        _init_git_repo(tmp_path)
        repo = await _seed_tracked_repo(db)
        fork = await _seed_fork(db, repo["id"])
        signal = await _seed_signal(
            db, repo["id"], fork["id"], significance=8, files=["src/cache.py"]
        )
        # Make the fetch raise for this file → partial-fetch fetch_error (exit 3),
        # distinct from an empty diff (which is a terminal patch_failed).
        provider._error_files.add("src/cache.py")

        output: list[str] = []
        exit_code = await _apply_impl(
            signal_id=signal["id"],
            repo_path=str(tmp_path),
            as_json=True,
            db=db,
            provider=provider,
            capture_output=output,
        )
        assert exit_code == 3
        payload = json.loads(output[0])
        assert payload["exit_reason"] == "fetch_error"


class TestApplyExitCodeMapping:
    """Lock the public exit-code contract for external agents.

    `_apply_exit_code_and_reason` is the single source of truth for how
    BackfillAttempt status translates to CLI exit codes. This table
    guards against any silent renumbering or collapsing of codes.
    """

    @pytest.mark.parametrize(
        ("status", "error", "expected_code", "expected_reason"),
        [
            (BackfillStatus.ACCEPTED, None, 0, "accepted"),
            (BackfillStatus.NEEDS_REVIEW, None, 5, "needs_review"),
            (BackfillStatus.PENDING, None, 0, "pending"),
            (BackfillStatus.TESTS_FAILED, None, 1, "tests_failed"),
            (BackfillStatus.CONFLICT, "branch already exists", 2, "conflict"),
            (BackfillStatus.PATCH_FAILED, "patch did not apply cleanly", 2, "patch_failed"),
            (
                BackfillStatus.PATCH_FAILED,
                "No diffs could be fetched for signal files",
                3,
                "fetch_error",
            ),
            (
                BackfillStatus.PATCH_FAILED,
                "Partial fetch: could not fetch diffs for: src/b.py",
                3,
                "fetch_error",
            ),
            (
                BackfillStatus.PATCH_FAILED,
                "No applicable diffs (all involved files are binary, pure renames, or unchanged)",
                2,
                "patch_failed",
            ),
            (BackfillStatus.REJECTED, None, 1, "rejected"),
        ],
    )
    def test_exit_code_mapping(self, status, error, expected_code, expected_reason):
        from forkhub.cli.backfill_cmd import _apply_exit_code_and_reason

        attempt = BackfillAttempt(
            signal_id="s1",
            fork_id="f1",
            tracked_repo_id="r1",
            status=status,
            error=error,
        )
        code, reason = _apply_exit_code_and_reason(attempt)
        assert code == expected_code
        assert reason == expected_reason


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


class TestCleanupCommand:
    async def test_unknown_attempt_returns_1(
        self, db: Database, provider: StubGitProvider, tmp_path: Path
    ):
        _init_git_repo(tmp_path)
        output: list[str] = []
        exit_code = await _cleanup_impl(
            attempt_id="nonexistent",
            repo_path=str(tmp_path),
            db=db,
            provider=provider,
            capture_output=output,
        )
        assert exit_code == 1

    async def test_deletes_existing_branch(
        self, db: Database, provider: StubGitProvider, tmp_path: Path
    ):
        _init_git_repo(tmp_path)
        branch_name = "backfill/feature/forker1-clean123"
        sp.run(
            ["git", "branch", branch_name],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
        )

        repo = await _seed_tracked_repo(db)
        fork = await _seed_fork(db, repo["id"])
        signal = await _seed_signal(db, repo["id"], fork["id"])
        attempt = await _seed_attempt(
            db, signal["id"], fork["id"], repo["id"], branch_name=branch_name
        )

        output: list[str] = []
        exit_code = await _cleanup_impl(
            attempt_id=attempt.id,
            repo_path=str(tmp_path),
            as_json=True,
            db=db,
            provider=provider,
            capture_output=output,
        )
        assert exit_code == 0
        payload = json.loads(output[0])
        assert payload["branch_deleted"] is True

        # Verify branch is gone
        result = sp.run(["git", "branch"], cwd=str(tmp_path), capture_output=True, text=True)
        assert branch_name not in result.stdout


# ---------------------------------------------------------------------------
# write-test
# ---------------------------------------------------------------------------


class TestWriteTestCommand:
    async def test_writes_valid_test_file(
        self, db: Database, provider: StubGitProvider, tmp_path: Path
    ):
        output: list[str] = []
        exit_code = await _write_test_impl(
            path="tests/test_new.py",
            content="def test_new(): assert True\n",
            repo_path=str(tmp_path),
            as_json=True,
            db=db,
            provider=provider,
            capture_output=output,
        )
        assert exit_code == 0
        payload = json.loads(output[0])
        assert payload["bytes_written"] > 0
        assert (tmp_path / "tests" / "test_new.py").exists()

    async def test_rejects_production_path(
        self, db: Database, provider: StubGitProvider, tmp_path: Path
    ):
        output: list[str] = []
        exit_code = await _write_test_impl(
            path="src/forkhub/models.py",
            content="# hacked\n",
            repo_path=str(tmp_path),
            db=db,
            provider=provider,
            capture_output=output,
        )
        assert exit_code == 1
        assert not (tmp_path / "src" / "forkhub" / "models.py").exists()

    async def test_rejects_parent_traversal(
        self, db: Database, provider: StubGitProvider, tmp_path: Path
    ):
        output: list[str] = []
        exit_code = await _write_test_impl(
            path="tests/../src/bad.py",
            content="# hacked\n",
            repo_path=str(tmp_path),
            db=db,
            provider=provider,
            capture_output=output,
        )
        assert exit_code == 1

    async def test_content_via_stdin(self, db: Database, provider: StubGitProvider, tmp_path: Path):
        output: list[str] = []
        exit_code = await _write_test_impl(
            path="tests/test_stdin.py",
            content=None,
            stdin_content="def test_from_stdin(): pass\n",
            repo_path=str(tmp_path),
            db=db,
            provider=provider,
            capture_output=output,
        )
        assert exit_code == 0
        assert (tmp_path / "tests" / "test_stdin.py").read_text() == (
            "def test_from_stdin(): pass\n"
        )


# ---------------------------------------------------------------------------
# read-failures
# ---------------------------------------------------------------------------


class TestReadFailuresCommand:
    async def test_returns_json_with_failing_files(
        self, db: Database, provider: StubGitProvider, tmp_path: Path
    ):
        """Exercise the full read-failures pipeline: test output is parsed, failing
        test files are identified, and their contents are returned."""
        _init_git_repo(tmp_path)
        (tmp_path / "tests").mkdir()
        failing_test = tmp_path / "tests" / "test_fail.py"
        failing_test.write_text("def test_x(): assert False\n")

        # Use a shell script that deterministically produces pytest-like output
        # pointing at the real test file, then exits non-zero.
        fake_pytest = tmp_path / "fake_pytest.sh"
        fake_pytest.write_text(
            "#!/bin/sh\n"
            'echo "tests/test_fail.py:1: AssertionError"\n'
            'echo "FAILED tests/test_fail.py::test_x"\n'
            "exit 1\n"
        )
        fake_pytest.chmod(0o755)

        output: list[str] = []
        exit_code = await _read_failures_impl(
            repo_path=str(tmp_path),
            test_command=str(fake_pytest),
            as_json=True,
            db=db,
            provider=provider,
            capture_output=output,
        )
        # Tests failed, so CLI returns exit 1 (was 0 before — now propagates outcome)
        assert exit_code == 1
        payload = json.loads(output[0])
        assert payload["returncode"] == 1
        assert len(payload["files"]) == 1
        assert payload["files"][0]["path"] == "tests/test_fail.py"
        assert "assert False" in payload["files"][0]["content"]


# ---------------------------------------------------------------------------
# run-tests
# ---------------------------------------------------------------------------


class TestRunTestsCommand:
    async def test_returns_zero_for_passing_command(
        self, db: Database, provider: StubGitProvider, tmp_path: Path
    ):
        output: list[str] = []
        exit_code = await _run_tests_impl(
            repo_path=str(tmp_path),
            test_command="true",
            as_json=True,
            db=db,
            provider=provider,
            capture_output=output,
        )
        assert exit_code == 0
        payload = json.loads(output[0])
        assert payload["returncode"] == 0

    async def test_returns_nonzero_for_failing_command(
        self, db: Database, provider: StubGitProvider, tmp_path: Path
    ):
        output: list[str] = []
        exit_code = await _run_tests_impl(
            repo_path=str(tmp_path),
            test_command="false",
            as_json=True,
            db=db,
            provider=provider,
            capture_output=output,
        )
        assert exit_code != 0
        payload = json.loads(output[0])
        assert payload["returncode"] != 0


# ---------------------------------------------------------------------------
# list with --json
# ---------------------------------------------------------------------------


class TestListJsonOutput:
    async def test_list_empty_json(self, db: Database, provider: StubGitProvider):
        from forkhub.cli.backfill_cmd import _backfill_list_impl

        output: list[str] = []
        await _backfill_list_impl(as_json=True, db=db, provider=provider, capture_output=output)
        payload = json.loads(output[0])
        assert payload == []

    async def test_list_with_attempts_json(self, db: Database, provider: StubGitProvider):
        from forkhub.cli.backfill_cmd import _backfill_list_impl

        repo = await _seed_tracked_repo(db)
        fork = await _seed_fork(db, repo["id"])
        signal = await _seed_signal(db, repo["id"], fork["id"])
        attempt = await _seed_attempt(db, signal["id"], fork["id"], repo["id"])

        output: list[str] = []
        await _backfill_list_impl(as_json=True, db=db, provider=provider, capture_output=output)
        payload = json.loads(output[0])
        assert len(payload) == 1
        assert payload[0]["id"] == attempt.id

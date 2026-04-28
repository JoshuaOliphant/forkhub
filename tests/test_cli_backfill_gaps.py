# ABOUTME: Coverage gap tests for cli/backfill_cmd.py — exercises run, list, output paths, errors.
# ABOUTME: Targets non-JSON pretty-print branches, autonomous run loop, and CLI wrappers.

from __future__ import annotations

import json
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from forkhub.cli.app import app
from forkhub.cli.backfill_cmd import (
    _apply_impl,
    _backfill_impl,
    _backfill_list_impl,
    _candidates_impl,
    _cleanup_impl,
    _read_failures_impl,
    _record_impl,
    _run_tests_impl,
    _status_impl,
    _write_test_impl,
)
from forkhub.models import BackfillAttempt, BackfillResult, BackfillStatus
from tests.stubs import StubGitProvider, make_fork, make_signal, make_tracked_repo

if TYPE_CHECKING:
    from forkhub.database import Database


runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_tracked_repo(db, owner="upstream", name="proj", github_id=10101):
    repo = make_tracked_repo(
        owner=owner,
        name=name,
        full_name=f"{owner}/{name}",
        github_id=github_id,
        tracking_mode="watched",
    )
    await db.insert_tracked_repo(repo)
    return repo


async def _seed_fork(db, tracked_repo_id, owner="forker1", github_id=50001):
    fork = make_fork(
        tracked_repo_id,
        owner=owner,
        full_name=f"{owner}/proj",
        github_id=github_id,
    )
    await db.insert_fork(fork)
    return fork


async def _seed_signal(db, repo_id, fork_id, *, significance=8):
    sig = make_signal(
        fork_id,
        repo_id,
        significance=significance,
        files_involved=json.dumps(["src/x.py"]),
    )
    await db.insert_signal(sig)
    return sig


async def _seed_attempt(
    db,
    signal_id,
    fork_id,
    tracked_repo_id,
    *,
    status=BackfillStatus.ACCEPTED,
    branch_name="backfill/test-branch",
    error: str | None = None,
):
    attempt = BackfillAttempt(
        signal_id=signal_id,
        fork_id=fork_id,
        tracked_repo_id=tracked_repo_id,
        status=status,
        branch_name=branch_name,
        patch_summary="seeded",
        error=error,
        score=0.5,
    )
    d = attempt.model_dump()
    d["created_at"] = attempt.created_at.isoformat()
    d["files_patched"] = json.dumps(attempt.files_patched)
    await db.insert_backfill_attempt(d)
    return attempt


@pytest.fixture
def patched_get_services(monkeypatch, db: Database):
    """Monkeypatch get_services so the get_services branch in each impl is exercised."""
    from forkhub.config import ForkHubSettings

    provider = StubGitProvider()
    settings = ForkHubSettings()

    async def fake_get_services(_arg=None):
        return settings, db, provider

    import forkhub.cli.helpers as helpers_mod

    monkeypatch.setattr(helpers_mod, "get_services", fake_get_services)
    return provider


# ---------------------------------------------------------------------------
# `_output` and `_emit_json` console branches (lines 48, 61)
# ---------------------------------------------------------------------------


class TestOutputHelpers:
    def test_output_print_branch(self):
        """_output with capture=None should call console.print (line 48)."""
        from forkhub.cli.backfill_cmd import _output

        # Capturing stdout via Rich is awkward; just call it and ensure no raise.
        _output("hello world")

    def test_emit_json_print_branch(self, capsys):
        """_emit_json with capture=None should print JSON to stdout (line 61)."""
        from forkhub.cli.backfill_cmd import _emit_json

        _emit_json({"k": "v"})
        out = capsys.readouterr().out
        assert '"k"' in out

    def test_emit_json_basemodel_print_branch(self, capsys):
        """_emit_json with a BaseModel and no capture goes through model_dump_json + print."""
        from forkhub.cli.backfill_cmd import RunTestsResponse, _emit_json

        _emit_json(RunTestsResponse(returncode=0, stdout="", stderr=""))
        out = capsys.readouterr().out
        assert '"returncode"' in out


# ---------------------------------------------------------------------------
# `_backfill_impl` autonomous run loop (lines 166-255)
# ---------------------------------------------------------------------------


class TestBackfillRunImpl:
    async def test_repo_not_found_returns_none(self, db: Database):
        """Unknown repo prints an error and returns None."""
        output: list[str] = []
        result = await _backfill_impl(
            repo="nobody/missing",
            db=db,
            provider=StubGitProvider(),
            capture_output=output,
        )
        assert result is None
        assert any("not found" in line.lower() for line in output)

    async def test_no_tracked_repos_message(self, db: Database):
        """When repo is None and no tracked repos, prints a yellow warning."""
        output: list[str] = []
        result = await _backfill_impl(
            db=db,
            provider=StubGitProvider(),
            capture_output=output,
        )
        assert result is None
        assert any("No tracked" in line for line in output)

    async def test_runs_summary_for_known_repo(self, db: Database, monkeypatch):
        """When the repo is tracked, prints the full summary block."""
        repo = await _seed_tracked_repo(db)

        # Patch run_backfill_all to return a result with branches_created.
        from forkhub.services.backfill import BackfillService

        async def fake_run_backfill_all(
            self, *, since=None, dry_run=False, repo_id=None, on_repo_start=None
        ):
            if on_repo_start is not None:
                on_repo_start("upstream/proj")
            return BackfillResult(
                total_evaluated=5,
                attempted=2,
                accepted=1,
                patch_failed=0,
                tests_failed=1,
                conflicts=0,
                branches_created=["backfill/cool-feature"],
            )

        monkeypatch.setattr(BackfillService, "run_backfill_all", fake_run_backfill_all)

        output: list[str] = []
        result = await _backfill_impl(
            repo="upstream/proj",
            db=db,
            provider=StubGitProvider(),
            capture_output=output,
        )
        del repo
        assert result is not None
        joined = "\n".join(output)
        assert "Backfill Summary" in joined
        assert "Signals evaluated: 5" in joined
        assert "backfill/cool-feature" in joined
        assert "Backfilling upstream/proj" in joined  # on_repo_start

    async def test_dry_run_on_repo_start_message(self, db: Database, monkeypatch):
        """The on_repo_start callback in dry-run mode prints the dim variant."""
        await _seed_tracked_repo(db)

        from forkhub.services.backfill import BackfillService

        async def fake_run_backfill_all(
            self, *, since=None, dry_run=False, repo_id=None, on_repo_start=None
        ):
            if on_repo_start is not None:
                on_repo_start("upstream/proj")
            return BackfillResult(total_evaluated=0, attempted=0)

        monkeypatch.setattr(BackfillService, "run_backfill_all", fake_run_backfill_all)

        output: list[str] = []
        await _backfill_impl(
            repo="upstream/proj",
            db=db,
            provider=StubGitProvider(),
            capture_output=output,
            dry_run=True,
        )
        joined = "\n".join(output)
        assert "dry run" in joined.lower()

    async def test_auto_fix_tests_constructs_test_fixer(self, db: Database, monkeypatch):
        """auto_fix_tests=True must construct a ClaudeTestFixer."""
        pytest.importorskip("claude_agent_sdk")
        await _seed_tracked_repo(db)

        constructed: list[dict] = []

        class RecorderFixer:
            def __init__(self, **kw):
                constructed.append(kw)

            async def suggest_fixes(self, *a, **kw):
                return None

        from forkhub.agent import test_fixer as tf_mod

        monkeypatch.setattr(tf_mod, "ClaudeTestFixer", RecorderFixer)

        from forkhub.services.backfill import BackfillService

        async def fake_run_backfill_all(self, **_kw):
            return BackfillResult()

        monkeypatch.setattr(BackfillService, "run_backfill_all", fake_run_backfill_all)

        await _backfill_impl(
            repo="upstream/proj",
            db=db,
            provider=StubGitProvider(),
            capture_output=[],
            auto_fix_tests=True,
        )
        assert len(constructed) == 1

    async def test_db_none_uses_get_services(self, patched_get_services, db: Database):
        """When db is None, the get_services branch runs."""
        await _seed_tracked_repo(db)
        output: list[str] = []
        await _backfill_impl(repo="upstream/proj", db=None, capture_output=output)


# ---------------------------------------------------------------------------
# CLI wrapper: `run` command (line 289)
# ---------------------------------------------------------------------------


class TestRunCommandWrapper:
    def test_run_command_invokes_impl(self, monkeypatch):
        from forkhub.cli import backfill_cmd

        async def fake(**_kw):
            return None

        monkeypatch.setattr(backfill_cmd, "_backfill_impl", fake)
        result = runner.invoke(app, ["backfill", "run"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# `list` command — db-None branch, errors, output paths, JSON, table
# ---------------------------------------------------------------------------


class TestListCommand:
    async def test_db_none_uses_get_services(self, patched_get_services, db: Database):
        await _backfill_list_impl(db=None, capture_output=[])

    async def test_repo_filter_not_found(self, db: Database):
        """When --repo points to an unknown repo, prints error + returns."""
        output: list[str] = []
        await _backfill_list_impl(repo="nobody/missing", db=db, capture_output=output)
        assert any("not found" in line.lower() for line in output)

    async def test_no_attempts_message(self, db: Database):
        output: list[str] = []
        await _backfill_list_impl(db=db, capture_output=output)
        assert any("No backfill attempts" in line for line in output)

    async def test_capture_output_iterates_attempts(self, db: Database):
        """capture_output != None branch lists attempts with a digest line."""
        repo = await _seed_tracked_repo(db)
        fork = await _seed_fork(db, repo["id"])
        sig = await _seed_signal(db, repo["id"], fork["id"])
        attempt = await _seed_attempt(db, sig["id"], fork["id"], repo["id"])

        output: list[str] = []
        await _backfill_list_impl(
            repo="upstream/proj",
            db=db,
            provider=StubGitProvider(),
            capture_output=output,
        )
        # The capture-branch outputs lines that include the truncated id and status.
        joined = "\n".join(output)
        assert attempt.id[:8] in joined

    async def test_table_render_branch(self, db: Database):
        """capture_output is None -> Rich table render path runs."""
        repo = await _seed_tracked_repo(db)
        fork = await _seed_fork(db, repo["id"])
        sig = await _seed_signal(db, repo["id"], fork["id"])
        await _seed_attempt(
            db, sig["id"], fork["id"], repo["id"], status=BackfillStatus.TESTS_FAILED
        )
        # No exception raised is success.
        await _backfill_list_impl(
            repo="upstream/proj",
            db=db,
            provider=StubGitProvider(),
            capture_output=None,
        )

    def test_list_command_wrapper(self, monkeypatch):
        from forkhub.cli import backfill_cmd

        async def fake(**_kw):
            return None

        monkeypatch.setattr(backfill_cmd, "_backfill_list_impl", fake)
        assert runner.invoke(app, ["backfill", "list"]).exit_code == 0


# ---------------------------------------------------------------------------
# `candidates` command — db-None, repo not found, table render, wrapper
# ---------------------------------------------------------------------------


class TestCandidatesGaps:
    async def test_db_none_uses_get_services(self, patched_get_services, db: Database):
        await _candidates_impl(db=None, capture_output=[])

    async def test_repo_not_found(self, db: Database):
        output: list[str] = []
        await _candidates_impl(repo="nobody/missing", db=db, capture_output=output)
        assert any("not found" in line.lower() for line in output)

    async def test_no_candidates_message(self, db: Database):
        repo = await _seed_tracked_repo(db)
        del repo
        output: list[str] = []
        await _candidates_impl(db=db, capture_output=output)
        assert any("No backfill candidates" in line for line in output)

    async def test_table_render_branch(self, db: Database):
        """When capture_output is None and there ARE candidates, table renders."""
        repo = await _seed_tracked_repo(db)
        fork = await _seed_fork(db, repo["id"])
        await _seed_signal(db, repo["id"], fork["id"], significance=8)
        # Pass --repo so the per-repo branch (line 425) runs.
        await _candidates_impl(
            repo="upstream/proj",
            db=db,
            provider=StubGitProvider(),
            capture_output=None,
        )

    def test_candidates_command_wrapper(self, monkeypatch):
        from forkhub.cli import backfill_cmd

        async def fake(**_kw):
            return None

        monkeypatch.setattr(backfill_cmd, "_candidates_impl", fake)
        assert runner.invoke(app, ["backfill", "candidates"]).exit_code == 0


# ---------------------------------------------------------------------------
# `apply` command — db-None, non-JSON output, wrapper
# ---------------------------------------------------------------------------


class TestApplyGaps:
    async def test_db_none_uses_get_services(self, patched_get_services, db: Database):
        await _apply_impl(signal_id="missing-id", db=None, capture_output=[])

    async def test_non_json_output_with_error(self, db: Database):
        """The non-JSON branch prints both the apply summary AND the error line."""
        repo = await _seed_tracked_repo(db)
        fork = await _seed_fork(db, repo["id"])
        sig = await _seed_signal(db, repo["id"], fork["id"])

        # No diffs from provider -> PATCH_FAILED with an error.
        output: list[str] = []
        await _apply_impl(
            signal_id=sig["id"],
            db=db,
            provider=StubGitProvider(),
            capture_output=output,
        )
        joined = "\n".join(output)
        assert "Apply" in joined
        assert "error" in joined.lower()

    def test_apply_command_wrapper(self, monkeypatch):
        from forkhub.cli import backfill_cmd

        async def fake(**_kw):
            return 0

        monkeypatch.setattr(backfill_cmd, "_apply_impl", fake)
        assert runner.invoke(app, ["backfill", "apply", "sig-id"]).exit_code == 0


# ---------------------------------------------------------------------------
# `status` command — db-None, output branches, wrapper
# ---------------------------------------------------------------------------


class TestStatusGaps:
    async def test_db_none_uses_get_services(self, patched_get_services, db: Database):
        await _status_impl(attempt_id="missing", db=None, capture_output=[])

    async def test_non_json_pretty_output(self, db: Database):
        repo = await _seed_tracked_repo(db)
        fork = await _seed_fork(db, repo["id"])
        sig = await _seed_signal(db, repo["id"], fork["id"])
        attempt = await _seed_attempt(db, sig["id"], fork["id"], repo["id"])

        output: list[str] = []
        rc = await _status_impl(
            attempt_id=attempt.id, db=db, provider=StubGitProvider(), capture_output=output
        )
        assert rc == 0
        joined = "\n".join(output)
        assert "Attempt" in joined
        assert "signal:" in joined

    def test_status_command_wrapper(self, monkeypatch):
        from forkhub.cli import backfill_cmd

        async def fake(**_kw):
            return 0

        monkeypatch.setattr(backfill_cmd, "_status_impl", fake)
        assert runner.invoke(app, ["backfill", "status", "abc"]).exit_code == 0


# ---------------------------------------------------------------------------
# `record` command — score validation, db-None, non-JSON output, wrapper
# ---------------------------------------------------------------------------


class TestRecordGaps:
    async def test_invalid_score_returns_2(self, db: Database):
        output: list[str] = []
        rc = await _record_impl(
            attempt_id="any",
            status="accepted",
            score=2.5,  # invalid
            db=db,
            provider=StubGitProvider(),
            capture_output=output,
        )
        assert rc == 2
        assert any("between 0.0 and 1.0" in line for line in output)

    async def test_db_none_uses_get_services(self, patched_get_services, db: Database):
        await _record_impl(attempt_id="missing", status="accepted", db=None, capture_output=[])

    async def test_non_json_pretty_output(self, db: Database):
        repo = await _seed_tracked_repo(db)
        fork = await _seed_fork(db, repo["id"])
        sig = await _seed_signal(db, repo["id"], fork["id"])
        attempt = await _seed_attempt(db, sig["id"], fork["id"], repo["id"])

        output: list[str] = []
        rc = await _record_impl(
            attempt_id=attempt.id,
            status="accepted",
            score=0.9,
            db=db,
            provider=StubGitProvider(),
            capture_output=output,
        )
        assert rc == 0
        assert any("Recorded attempt" in line for line in output)

    def test_record_command_wrapper(self, monkeypatch):
        from forkhub.cli import backfill_cmd

        async def fake(**_kw):
            return 0

        monkeypatch.setattr(backfill_cmd, "_record_impl", fake)
        assert (
            runner.invoke(app, ["backfill", "record", "id", "--status", "accepted"]).exit_code == 0
        )


# ---------------------------------------------------------------------------
# `cleanup` command — db-None, warnings output, wrapper
# ---------------------------------------------------------------------------


class TestCleanupGaps:
    async def test_db_none_uses_get_services(self, patched_get_services, db: Database):
        await _cleanup_impl(attempt_id="missing", db=None, capture_output=[])

    async def test_non_json_pretty_output_with_warnings(self, db: Database, monkeypatch):
        """Cleanup with warnings prints them and returns 2."""
        repo = await _seed_tracked_repo(db)
        fork = await _seed_fork(db, repo["id"])
        sig = await _seed_signal(db, repo["id"], fork["id"])
        attempt = await _seed_attempt(db, sig["id"], fork["id"], repo["id"])

        from forkhub.services.backfill import BackfillService

        async def fake_cleanup(self, attempt_id, *, keep_branch=False):
            return {
                "attempt_id": attempt_id,
                "branch_name": "backfill/test",
                "branch_deleted": False,
                "checked_out": "main",
                "warnings": ["delete failed: locked"],
            }

        monkeypatch.setattr(BackfillService, "cleanup_attempt", fake_cleanup)

        output: list[str] = []
        rc = await _cleanup_impl(
            attempt_id=attempt.id,
            db=db,
            provider=StubGitProvider(),
            capture_output=output,
        )
        assert rc == 2
        joined = "\n".join(output)
        assert "Cleanup attempt" in joined
        assert "warning" in joined.lower()

    def test_cleanup_command_wrapper(self, monkeypatch):
        from forkhub.cli import backfill_cmd

        async def fake(**_kw):
            return 0

        monkeypatch.setattr(backfill_cmd, "_cleanup_impl", fake)
        assert runner.invoke(app, ["backfill", "cleanup", "id"]).exit_code == 0


# ---------------------------------------------------------------------------
# `read-failures` command — db-None, non-JSON, returncode mappings, wrapper
# ---------------------------------------------------------------------------


class TestReadFailuresGaps:
    async def test_db_none_uses_get_services(self, patched_get_services, db: Database):
        # Patch the service to avoid actually running tests.
        from forkhub.services.backfill import BackfillService

        async def fake_read(self, *args, **kwargs):
            return {"returncode": 0, "test_output": "", "files": []}

        import forkhub.services.backfill as backfill_mod

        original = backfill_mod.BackfillService.read_failing_test_files
        BackfillService.read_failing_test_files = fake_read  # type: ignore[assignment]
        try:
            rc = await _read_failures_impl(db=None, capture_output=[])
            assert rc == 0
        finally:
            BackfillService.read_failing_test_files = original  # type: ignore[assignment]

    async def test_non_json_output_with_failing_files(self, db: Database, monkeypatch):
        from forkhub.services.backfill import BackfillService

        async def fake_read(self, *args, **kwargs):
            return {
                "returncode": 1,
                "test_output": "",
                "files": [{"path": "tests/test_x.py", "content": ""}],
            }

        monkeypatch.setattr(BackfillService, "read_failing_test_files", fake_read)

        output: list[str] = []
        rc = await _read_failures_impl(
            db=db, provider=StubGitProvider(), capture_output=output, as_json=False
        )
        assert rc == 1
        joined = "\n".join(output)
        assert "tests/test_x.py" in joined

    async def test_returncode_zero_path(self, db: Database, monkeypatch):
        from forkhub.services.backfill import BackfillService

        async def fake_read(self, *args, **kwargs):
            return {"returncode": 0, "test_output": "", "files": []}

        monkeypatch.setattr(BackfillService, "read_failing_test_files", fake_read)

        rc = await _read_failures_impl(
            db=db, provider=StubGitProvider(), capture_output=[], as_json=True
        )
        assert rc == 0

    async def test_returncode_negative_maps_to_124(self, db: Database, monkeypatch):
        from forkhub.services.backfill import BackfillService

        async def fake_read(self, *args, **kwargs):
            return {"returncode": -1, "test_output": "", "files": []}

        monkeypatch.setattr(BackfillService, "read_failing_test_files", fake_read)

        rc = await _read_failures_impl(
            db=db, provider=StubGitProvider(), capture_output=[], as_json=True
        )
        assert rc == 124

    def test_read_failures_command_wrapper(self, monkeypatch):
        from forkhub.cli import backfill_cmd

        async def fake(**_kw):
            return 0

        monkeypatch.setattr(backfill_cmd, "_read_failures_impl", fake)
        assert runner.invoke(app, ["backfill", "read-failures"]).exit_code == 0


# ---------------------------------------------------------------------------
# `write-test` command — TTY error, db-None, OSError, non-JSON, wrapper
# ---------------------------------------------------------------------------


class TestWriteTestGaps:
    async def test_tty_no_content_returns_2(self, db: Database, monkeypatch):
        """When stdin is a TTY and no content given, returns 2."""
        # Force isatty() to return True
        monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

        output: list[str] = []
        rc = await _write_test_impl(
            path="tests/test_new.py",
            content=None,
            stdin_content=None,
            db=db,
            provider=StubGitProvider(),
            capture_output=output,
        )
        assert rc == 2
        assert any("TTY" in line or "stdin" in line.lower() for line in output)

    async def test_no_content_reads_from_stdin(self, db: Database, monkeypatch, tmp_path):
        """When content is None, stdin_content is None, and stdin is NOT a TTY,
        the impl reads from sys.stdin (line 940)."""
        from io import StringIO

        # Force isatty() to return False so the read branch runs
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
        # Replace stdin with a StringIO so .read() returns canned content.
        monkeypatch.setattr(sys, "stdin", StringIO("def test_a(): pass\n"))

        rc = await _write_test_impl(
            path="tests/test_new.py",
            content=None,
            stdin_content=None,
            repo_path=str(tmp_path),
            db=db,
            provider=StubGitProvider(),
            capture_output=[],
        )
        assert rc == 0
        # Verify the file was actually written with stdin content
        assert (tmp_path / "tests/test_new.py").read_text() == "def test_a(): pass\n"

    async def test_db_none_uses_get_services(self, patched_get_services, db: Database, tmp_path):
        rc = await _write_test_impl(
            path="tests/test_new.py",
            content="def test_x(): pass\n",
            repo_path=str(tmp_path),
            db=None,
            capture_output=[],
        )
        assert rc == 0

    async def test_oserror_returns_2(self, db: Database, monkeypatch, tmp_path):
        """When write_test_file raises OSError, return 2."""
        from forkhub.services.backfill import BackfillService

        def bad_write(self, path, content):
            raise OSError("disk full")

        monkeypatch.setattr(BackfillService, "write_test_file", bad_write)

        output: list[str] = []
        rc = await _write_test_impl(
            path="tests/test_new.py",
            content="x",
            repo_path=str(tmp_path),
            db=db,
            provider=StubGitProvider(),
            capture_output=output,
        )
        assert rc == 2
        assert any("Write failed" in line for line in output)

    async def test_non_json_pretty_output(self, db: Database, tmp_path):
        output: list[str] = []
        rc = await _write_test_impl(
            path="tests/test_new.py",
            content="def test_a(): pass\n",
            repo_path=str(tmp_path),
            db=db,
            provider=StubGitProvider(),
            capture_output=output,
            as_json=False,
        )
        assert rc == 0
        joined = "\n".join(output)
        assert "Wrote" in joined

    def test_write_test_command_wrapper(self, monkeypatch):
        from forkhub.cli import backfill_cmd

        async def fake(**_kw):
            return 0

        monkeypatch.setattr(backfill_cmd, "_write_test_impl", fake)
        assert (
            runner.invoke(
                app,
                [
                    "backfill",
                    "write-test",
                    "tests/test_x.py",
                    "--content",
                    "def test_a(): pass",
                ],
            ).exit_code
            == 0
        )


# ---------------------------------------------------------------------------
# `run-tests` command — db-None, non-JSON output, returncode mappings, wrapper
# ---------------------------------------------------------------------------


class TestRunTestsGaps:
    async def test_db_none_uses_get_services(self, patched_get_services, db: Database, monkeypatch):
        from forkhub.services.backfill import BackfillService

        async def fake(self):
            return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        monkeypatch.setattr(BackfillService, "run_test_command", fake)
        rc = await _run_tests_impl(db=None, capture_output=[])
        assert rc == 0

    async def test_non_json_with_stdout_and_stderr(self, db: Database, monkeypatch):
        from forkhub.services.backfill import BackfillService

        async def fake(self):
            return subprocess.CompletedProcess(
                args=[], returncode=1, stdout="passing logs", stderr="warning"
            )

        monkeypatch.setattr(BackfillService, "run_test_command", fake)

        output: list[str] = []
        rc = await _run_tests_impl(
            db=db, provider=StubGitProvider(), capture_output=output, as_json=False
        )
        assert rc == 1
        joined = "\n".join(output)
        assert "passing logs" in joined
        assert "warning" in joined

    async def test_returncode_negative_maps_to_124(self, db: Database, monkeypatch):
        from forkhub.services.backfill import BackfillService

        async def fake(self):
            return subprocess.CompletedProcess(args=[], returncode=-1, stdout="", stderr="")

        monkeypatch.setattr(BackfillService, "run_test_command", fake)

        rc = await _run_tests_impl(
            db=db, provider=StubGitProvider(), capture_output=[], as_json=True
        )
        assert rc == 124

    async def test_returncode_clamped_to_255(self, db: Database, monkeypatch):
        from forkhub.services.backfill import BackfillService

        async def fake(self):
            return subprocess.CompletedProcess(args=[], returncode=300, stdout="", stderr="")

        monkeypatch.setattr(BackfillService, "run_test_command", fake)

        rc = await _run_tests_impl(
            db=db, provider=StubGitProvider(), capture_output=[], as_json=True
        )
        assert rc == 255

    def test_run_tests_command_wrapper(self, monkeypatch):
        from forkhub.cli import backfill_cmd

        async def fake(**_kw):
            return 0

        monkeypatch.setattr(backfill_cmd, "_run_tests_impl", fake)
        assert runner.invoke(app, ["backfill", "run-tests"]).exit_code == 0

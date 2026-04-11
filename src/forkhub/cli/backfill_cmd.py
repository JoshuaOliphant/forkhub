# ABOUTME: Backfill sub-app — autonomous loop plus primitives for external agents.
# ABOUTME: Provides candidates/apply/status/record/cleanup/read-failures/write-test/run-tests.

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table

from forkhub.cli.helpers import async_command

if TYPE_CHECKING:
    from forkhub.database import Database
    from forkhub.interfaces import GitProvider
    from forkhub.models import BackfillAttempt, BackfillResult

console = Console()

backfill_app = typer.Typer(
    name="backfill",
    help=(
        "Backfill valuable fork changes into the local repo. "
        "Use 'run' for the autonomous loop or the per-step primitives "
        "(candidates, apply, status, record, cleanup, read-failures, "
        "write-test, run-tests) to drive the loop from an external agent."
    ),
    invoke_without_command=False,
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _output(line: str, capture: list[str] | None = None) -> None:
    if capture is not None:
        capture.append(line)
    else:
        console.print(line)


def _emit_json(data: BaseModel | dict | list, capture: list[str] | None = None) -> None:
    """Emit JSON to stdout (or to capture list for tests)."""
    if isinstance(data, BaseModel):
        text = data.model_dump_json(indent=2)
    else:
        text = json.dumps(data, indent=2, default=str)
    if capture is not None:
        capture.append(text)
    else:
        # Bypass Rich to avoid markup interpretation on JSON output
        print(text)  # noqa: T201


# ---------------------------------------------------------------------------
# JSON DTOs (explicit output contracts)
# ---------------------------------------------------------------------------


class CandidateDTO(BaseModel):
    signal_id: str
    fork_id: str | None
    tracked_repo_id: str
    category: str
    summary: str
    files_involved: list[str]
    significance: int
    already_attempted: bool


class CandidatesResponse(BaseModel):
    candidates: list[CandidateDTO]
    count: int


class AttemptDTO(BaseModel):
    id: str
    signal_id: str
    fork_id: str
    tracked_repo_id: str
    status: str
    branch_name: str | None
    patch_summary: str | None
    test_output: str | None
    error: str | None
    files_patched: list[str]
    score: float | None
    created_at: str


class ApplyResponse(BaseModel):
    attempt: AttemptDTO
    exit_reason: str


class ReadFailuresResponse(BaseModel):
    returncode: int
    test_output: str
    files: list[dict[str, str]] = Field(default_factory=list)


class RunTestsResponse(BaseModel):
    returncode: int
    stdout: str
    stderr: str


class CleanupResponse(BaseModel):
    attempt_id: str
    branch_name: str | None
    branch_deleted: bool
    checked_out: str | None


class WriteTestResponse(BaseModel):
    path: str
    bytes_written: int


def _attempt_to_dto(attempt: BackfillAttempt) -> AttemptDTO:
    return AttemptDTO(
        id=attempt.id,
        signal_id=attempt.signal_id,
        fork_id=attempt.fork_id,
        tracked_repo_id=attempt.tracked_repo_id,
        status=str(attempt.status),
        branch_name=attempt.branch_name,
        patch_summary=attempt.patch_summary,
        test_output=attempt.test_output,
        error=attempt.error,
        files_patched=attempt.files_patched,
        score=attempt.score,
        created_at=attempt.created_at.isoformat(),
    )


# ---------------------------------------------------------------------------
# `run` — autonomous loop (existing behavior, moved under sub-app)
# ---------------------------------------------------------------------------


async def _backfill_impl(
    repo: str | None = None,
    since_days: int = 30,
    dry_run: bool = False,
    min_significance: int = 5,
    max_attempts: int = 10,
    auto_fix_tests: bool = False,
    repo_path: str | None = None,
    test_command: str | None = None,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
) -> BackfillResult | None:
    """Core autonomous backfill logic (the `run` subcommand)."""
    from forkhub.cli.helpers import get_services
    from forkhub.services.backfill import BackfillService

    owns_db = False
    if db is None or provider is None:
        _settings, db, provider = await get_services()
        owns_db = True

    try:
        # Resolve the target repo
        repo_id = None
        if repo is not None:
            repo_row = await db.get_tracked_repo_by_name(repo)
            if repo_row is None:
                _output(
                    f"[red]Error: Repository '{repo}' not found or not tracked.[/red]",
                    capture_output,
                )
                return None
            repo_id = repo_row["id"]
        else:
            repos = await db.list_tracked_repos()
            if not repos:
                _output("[yellow]No tracked repositories found.[/yellow]", capture_output)
                return None

        since = datetime.now(UTC) - timedelta(days=since_days)

        effective_test_cmd = test_command or "uv run pytest -x --tb=short -q"
        effective_repo_path = Path(repo_path) if repo_path else Path.cwd()

        # Wire up the test fixer when auto_fix_tests is enabled
        test_fixer = None
        if auto_fix_tests:
            from forkhub.agent.test_fixer import ClaudeTestFixer
            from forkhub.config import ForkHubSettings

            fh_settings = ForkHubSettings()
            test_fixer = ClaudeTestFixer(
                model=fh_settings.anthropic.digest_model,
                budget_usd=fh_settings.anthropic.analysis_budget_usd / 5,
            )

        backfill = BackfillService(
            db=db,
            provider=provider,
            repo_path=effective_repo_path,
            test_command=effective_test_cmd,
            min_significance=min_significance,
            max_attempts=max_attempts,
            auto_fix_tests=auto_fix_tests,
            test_fixer=test_fixer,
        )

        def _on_repo_start(name: str) -> None:
            if dry_run:
                _output(
                    f"[dim]Evaluating candidates for {name} (dry run)...[/dim]",
                    capture_output,
                )
            else:
                _output(f"Backfilling {name}...", capture_output)

        combined = await backfill.run_backfill_all(
            since=since,
            dry_run=dry_run,
            repo_id=repo_id,
            on_repo_start=_on_repo_start,
        )

        # Print summary
        _output("", capture_output)
        _output("[bold]Backfill Summary[/bold]", capture_output)
        _output(f"  Signals evaluated: {combined.total_evaluated}", capture_output)
        _output(f"  Attempts made:     {combined.attempted}", capture_output)
        _output(f"  Accepted:          [green]{combined.accepted}[/green]", capture_output)
        _output(f"  Patch failed:      [red]{combined.patch_failed}[/red]", capture_output)
        _output(f"  Tests failed:      [yellow]{combined.tests_failed}[/yellow]", capture_output)
        _output(f"  Conflicts:         [red]{combined.conflicts}[/red]", capture_output)

        if combined.branches_created:
            _output("", capture_output)
            _output("[bold]Candidate branches created:[/bold]", capture_output)
            for branch in combined.branches_created:
                _output(f"  [green]{branch}[/green]", capture_output)

        return combined
    finally:
        if owns_db:
            await db.close()


@backfill_app.command("run")
@async_command
async def run_command(
    repo: str | None = typer.Option(
        None, "--repo", "-r", help="Backfill only this repository (owner/repo)"
    ),
    since_days: int = typer.Option(
        30, "--since-days", "-s", help="Look back this many days for signals"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Evaluate candidates without applying patches"
    ),
    min_significance: int = typer.Option(
        5, "--min-significance", help="Minimum signal significance to consider"
    ),
    max_attempts: int = typer.Option(
        10, "--max-attempts", help="Maximum number of backfill attempts per run"
    ),
    auto_fix_tests: bool = typer.Option(
        False,
        "--auto-fix-tests/--no-auto-fix-tests",
        help="Attempt to fix failing tests after patch application (requires [claude] extra)",
    ),
    repo_path: str | None = typer.Option(
        None, "--repo-path", help="Path to the local repository to patch"
    ),
    test_command: str | None = typer.Option(
        None, "--test-command", help="Custom test command to run after patching"
    ),
) -> None:
    """Run the agentic backfill loop to cherry-pick valuable fork changes."""
    await _backfill_impl(
        repo=repo,
        since_days=since_days,
        dry_run=dry_run,
        min_significance=min_significance,
        max_attempts=max_attempts,
        auto_fix_tests=auto_fix_tests,
        repo_path=repo_path,
        test_command=test_command,
    )


# ---------------------------------------------------------------------------
# `list` — list prior attempts
# ---------------------------------------------------------------------------


async def _backfill_list_impl(
    repo: str | None = None,
    status: str | None = None,
    as_json: bool = False,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
) -> None:
    """List previous backfill attempts."""
    from forkhub.cli.helpers import get_services
    from forkhub.services.backfill import BackfillService

    owns_db = False
    if db is None or provider is None:
        _settings, db, provider = await get_services()
        owns_db = True

    try:
        repo_id = None
        if repo is not None:
            repo_row = await db.get_tracked_repo_by_name(repo)
            if repo_row is None:
                _output(f"[red]Error: Repository '{repo}' not found.[/red]", capture_output)
                return
            repo_id = repo_row["id"]

        service = BackfillService(db=db, provider=provider)
        attempts = await service.list_attempts(repo_id=repo_id, status=status)

        if as_json:
            payload = [_attempt_to_dto(a).model_dump() for a in attempts]
            _emit_json(payload, capture_output)
            return

        if not attempts:
            _output("[dim]No backfill attempts found.[/dim]", capture_output)
            return

        if capture_output is not None:
            for a in attempts:
                capture_output.append(f"{a.id[:8]} {a.status:15s} {a.patch_summary or 'N/A'}")
            return

        table = Table(title="Backfill Attempts")
        table.add_column("ID", style="dim", width=8)
        table.add_column("Status", width=14)
        table.add_column("Branch", width=30)
        table.add_column("Summary", width=40)
        table.add_column("Score", width=6)

        status_colors = {
            "accepted": "green",
            "pending": "dim",
            "patch_failed": "red",
            "tests_failed": "yellow",
            "conflict": "red",
            "rejected": "red",
        }

        for a in attempts:
            color = status_colors.get(str(a.status), "white")
            score_str = f"{a.score:.1f}" if a.score is not None else "-"
            table.add_row(
                a.id[:8],
                f"[{color}]{a.status}[/{color}]",
                a.branch_name or "-",
                (a.patch_summary or "-")[:40],
                score_str,
            )

        console.print(table)
    finally:
        if owns_db:
            await db.close()


@backfill_app.command("list")
@async_command
async def list_command(
    repo: str | None = typer.Option(None, "--repo", "-r", help="Filter by repository (owner/repo)"),
    status: str | None = typer.Option(
        None, "--status", help="Filter by status (accepted, tests_failed, patch_failed, etc.)"
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON array of attempts"),
) -> None:
    """List previous backfill attempts and their outcomes."""
    await _backfill_list_impl(repo=repo, status=status, as_json=as_json)


# ---------------------------------------------------------------------------
# `candidates` — list signals eligible for backfill
# ---------------------------------------------------------------------------


async def _candidates_impl(
    repo: str | None = None,
    since_days: int = 30,
    min_significance: int = 5,
    max_candidates: int = 50,
    as_json: bool = False,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
) -> None:
    from forkhub.cli.helpers import get_services
    from forkhub.services.backfill import BackfillService

    owns_db = False
    if db is None or provider is None:
        _settings, db, provider = await get_services()
        owns_db = True

    try:
        # Resolve repo ids (one or all)
        if repo is not None:
            repo_row = await db.get_tracked_repo_by_name(repo)
            if repo_row is None:
                _output(f"[red]Error: Repository '{repo}' not found.[/red]", capture_output)
                return
            repo_ids = [repo_row["id"]]
        else:
            repos = await db.list_tracked_repos()
            repo_ids = [r["id"] for r in repos]

        since = datetime.now(UTC) - timedelta(days=since_days)

        service = BackfillService(db=db, provider=provider, min_significance=min_significance)

        all_candidates: list[CandidateDTO] = []
        for rid in repo_ids:
            signals = await service.gather_candidates(rid, since=since)
            for sig in signals:
                already = await db.has_backfill_for_signal(sig.id)
                all_candidates.append(
                    CandidateDTO(
                        signal_id=sig.id,
                        fork_id=sig.fork_id,
                        tracked_repo_id=sig.tracked_repo_id,
                        category=str(sig.category),
                        summary=sig.summary,
                        files_involved=sig.files_involved,
                        significance=sig.significance,
                        already_attempted=already,
                    )
                )

        # Sort across repos by significance desc, then truncate
        all_candidates.sort(key=lambda c: -c.significance)
        all_candidates = all_candidates[:max_candidates]

        response = CandidatesResponse(candidates=all_candidates, count=len(all_candidates))

        if as_json:
            _emit_json(response, capture_output)
            return

        if not all_candidates:
            _output("[dim]No backfill candidates found.[/dim]", capture_output)
            return

        table = Table(title="Backfill Candidates")
        table.add_column("Signal ID", style="dim", width=8)
        table.add_column("Category", width=12)
        table.add_column("Sig", width=4)
        table.add_column("Summary", width=50)
        table.add_column("Attempted?", width=10)
        for c in all_candidates:
            table.add_row(
                c.signal_id[:8],
                c.category,
                str(c.significance),
                c.summary[:50],
                "yes" if c.already_attempted else "-",
            )
        console.print(table)
    finally:
        if owns_db:
            await db.close()


@backfill_app.command("candidates")
@async_command
async def candidates_command(
    repo: str | None = typer.Option(
        None, "--repo", "-r", help="Filter to this repository (owner/repo)"
    ),
    since_days: int = typer.Option(30, "--since-days", "-s"),
    min_significance: int = typer.Option(5, "--min-significance"),
    max_candidates: int = typer.Option(50, "--max", help="Maximum candidates to return"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List signals eligible for backfill."""
    await _candidates_impl(
        repo=repo,
        since_days=since_days,
        min_significance=min_significance,
        max_candidates=max_candidates,
        as_json=as_json,
    )


# ---------------------------------------------------------------------------
# `apply` — apply a signal's patches and run tests
# ---------------------------------------------------------------------------


def _apply_exit_code_and_reason(attempt: BackfillAttempt) -> tuple[int, str]:
    """Map a BackfillAttempt to (exit_code, exit_reason)."""
    from forkhub.models import BackfillStatus

    status = attempt.status
    if status == BackfillStatus.ACCEPTED:
        return 0, "accepted"
    if status == BackfillStatus.TESTS_FAILED:
        return 1, "tests_failed"
    if status == BackfillStatus.CONFLICT:
        return 2, "conflict"
    if status == BackfillStatus.PATCH_FAILED:
        if attempt.error and "No diffs" in attempt.error:
            return 3, "fetch_error"
        return 2, "patch_failed"
    if status == BackfillStatus.PENDING:
        return 0, "pending"
    return 1, "rejected"


async def _apply_impl(
    signal_id: str,
    repo_path: str | None = None,
    test_command: str | None = None,
    as_json: bool = False,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
) -> int:
    from forkhub.cli.helpers import get_services
    from forkhub.services.backfill import BackfillService

    owns_db = False
    if db is None or provider is None:
        _settings, db, provider = await get_services()
        owns_db = True

    try:
        effective_test_cmd = test_command or "uv run pytest -x --tb=short -q"
        effective_repo_path = Path(repo_path) if repo_path else Path.cwd()

        service = BackfillService(
            db=db,
            provider=provider,
            repo_path=effective_repo_path,
            test_command=effective_test_cmd,
        )

        try:
            attempt = await service.apply_signal(signal_id, keep_branch_on_failure=True)
        except ValueError as exc:
            _output(f"[red]Error: {exc}[/red]", capture_output)
            return 4

        exit_code, reason = _apply_exit_code_and_reason(attempt)

        if as_json:
            response = ApplyResponse(attempt=_attempt_to_dto(attempt), exit_reason=reason)
            _emit_json(response, capture_output)
        else:
            _output(
                f"Apply [{reason}]: attempt {attempt.id[:8]}, "
                f"status={attempt.status}, branch={attempt.branch_name or '-'}",
                capture_output,
            )
            if attempt.error:
                _output(f"  error: {attempt.error}", capture_output)

        return exit_code
    finally:
        if owns_db:
            await db.close()


@backfill_app.command("apply")
@async_command
async def apply_command(
    signal_id: str = typer.Argument(..., help="ID of the signal to apply"),
    repo_path: str | None = typer.Option(None, "--repo-path"),
    test_command: str | None = typer.Option(None, "--test-command"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Apply a signal's patches to a candidate branch and run tests.

    Exit codes: 0=tests passed, 1=tests failed, 2=conflict/patch failed,
    3=fetch error, 4=signal not found. Branch preserved on failure.
    """
    exit_code = await _apply_impl(
        signal_id=signal_id,
        repo_path=repo_path,
        test_command=test_command,
        as_json=as_json,
    )
    raise typer.Exit(exit_code)


# ---------------------------------------------------------------------------
# `status` — inspect an attempt
# ---------------------------------------------------------------------------


async def _status_impl(
    attempt_id: str,
    as_json: bool = False,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
) -> int:
    from forkhub.cli.helpers import get_services
    from forkhub.services.backfill import BackfillService

    owns_db = False
    if db is None or provider is None:
        _settings, db, provider = await get_services()
        owns_db = True

    try:
        service = BackfillService(db=db, provider=provider)
        attempt = await service.get_attempt(attempt_id)
        if attempt is None:
            _output(f"[red]Attempt not found: {attempt_id}[/red]", capture_output)
            return 1

        if as_json:
            _emit_json(_attempt_to_dto(attempt), capture_output)
        else:
            _output(
                f"Attempt {attempt.id}\n"
                f"  signal: {attempt.signal_id}\n"
                f"  status: {attempt.status}\n"
                f"  branch: {attempt.branch_name or '-'}\n"
                f"  files:  {', '.join(attempt.files_patched) or '-'}\n"
                f"  score:  {attempt.score if attempt.score is not None else '-'}\n"
                f"  error:  {attempt.error or '-'}",
                capture_output,
            )
        return 0
    finally:
        if owns_db:
            await db.close()


@backfill_app.command("status")
@async_command
async def status_command(
    attempt_id: str = typer.Argument(..., help="ID of the backfill attempt"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Inspect a backfill attempt record."""
    exit_code = await _status_impl(attempt_id=attempt_id, as_json=as_json)
    raise typer.Exit(exit_code)


# ---------------------------------------------------------------------------
# `record` — update attempt outcome
# ---------------------------------------------------------------------------


async def _record_impl(
    attempt_id: str,
    status: str,
    notes: str | None = None,
    score: float | None = None,
    as_json: bool = False,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
) -> int:
    from forkhub.cli.helpers import get_services
    from forkhub.models import BackfillStatus
    from forkhub.services.backfill import BackfillService

    try:
        status_enum = BackfillStatus(status)
    except ValueError:
        _output(
            f"[red]Error: invalid status '{status}'. "
            f"Must be one of: {', '.join(s.value for s in BackfillStatus)}[/red]",
            capture_output,
        )
        return 2

    owns_db = False
    if db is None or provider is None:
        _settings, db, provider = await get_services()
        owns_db = True

    try:
        service = BackfillService(db=db, provider=provider)
        try:
            attempt = await service.record_outcome(
                attempt_id, status=status_enum, score=score, notes=notes
            )
        except ValueError as exc:
            _output(f"[red]Error: {exc}[/red]", capture_output)
            return 1

        if as_json:
            _emit_json(_attempt_to_dto(attempt), capture_output)
        else:
            _output(
                f"Recorded attempt {attempt.id[:8]} -> {attempt.status}"
                + (f" (score={attempt.score})" if attempt.score is not None else ""),
                capture_output,
            )
        return 0
    finally:
        if owns_db:
            await db.close()


@backfill_app.command("record")
@async_command
async def record_command(
    attempt_id: str = typer.Argument(..., help="ID of the backfill attempt"),
    status: str = typer.Option(
        ..., "--status", help="New status: accepted, rejected, tests_failed, pending, etc."
    ),
    notes: str | None = typer.Option(None, "--notes", help="Notes to append to patch_summary"),
    score: float | None = typer.Option(None, "--score", help="Score 0.0-1.0"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Record the final outcome of a backfill attempt."""
    exit_code = await _record_impl(
        attempt_id=attempt_id,
        status=status,
        notes=notes,
        score=score,
        as_json=as_json,
    )
    raise typer.Exit(exit_code)


# ---------------------------------------------------------------------------
# `cleanup` — return to original branch, delete candidate branch
# ---------------------------------------------------------------------------


async def _cleanup_impl(
    attempt_id: str,
    repo_path: str | None = None,
    keep_branch: bool = False,
    as_json: bool = False,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
) -> int:
    from forkhub.cli.helpers import get_services
    from forkhub.services.backfill import BackfillService

    owns_db = False
    if db is None or provider is None:
        _settings, db, provider = await get_services()
        owns_db = True

    try:
        effective_repo_path = Path(repo_path) if repo_path else Path.cwd()
        service = BackfillService(db=db, provider=provider, repo_path=effective_repo_path)

        try:
            result = await service.cleanup_attempt(attempt_id, keep_branch=keep_branch)
        except ValueError as exc:
            _output(f"[red]Error: {exc}[/red]", capture_output)
            return 1

        response = CleanupResponse(**result)
        if as_json:
            _emit_json(response, capture_output)
        else:
            _output(
                f"Cleanup attempt {attempt_id[:8]}: "
                f"branch={response.branch_name or '-'}, "
                f"deleted={response.branch_deleted}, "
                f"checked_out={response.checked_out or '-'}",
                capture_output,
            )
        return 0
    finally:
        if owns_db:
            await db.close()


@backfill_app.command("cleanup")
@async_command
async def cleanup_command(
    attempt_id: str = typer.Argument(..., help="ID of the backfill attempt"),
    repo_path: str | None = typer.Option(None, "--repo-path"),
    keep_branch: bool = typer.Option(
        False, "--keep-branch", help="Return to original branch without deleting candidate"
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Return to the original branch and (optionally) delete the candidate branch."""
    exit_code = await _cleanup_impl(
        attempt_id=attempt_id,
        repo_path=repo_path,
        keep_branch=keep_branch,
        as_json=as_json,
    )
    raise typer.Exit(exit_code)


# ---------------------------------------------------------------------------
# `read-failures` — run tests, return failing test files
# ---------------------------------------------------------------------------


async def _read_failures_impl(
    attempt_id: str | None = None,
    repo_path: str | None = None,
    test_command: str | None = None,
    as_json: bool = True,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
) -> int:
    from forkhub.cli.helpers import get_services
    from forkhub.services.backfill import BackfillService

    owns_db = False
    if db is None or provider is None:
        _settings, db, provider = await get_services()
        owns_db = True

    try:
        effective_test_cmd = test_command or "uv run pytest -x --tb=short -q"
        effective_repo_path = Path(repo_path) if repo_path else Path.cwd()

        service = BackfillService(
            db=db,
            provider=provider,
            repo_path=effective_repo_path,
            test_command=effective_test_cmd,
        )

        # If attempt_id provided, we could use its stored output; for now we always
        # run fresh since working tree may have changed. attempt_id is accepted for
        # future use (and to let the agent scope the call) but not required.
        _ = attempt_id

        result = await service.read_failing_test_files()
        response = ReadFailuresResponse(**result)

        if as_json:
            _emit_json(response, capture_output)
        else:
            _output(
                f"returncode={response.returncode}, failing files={len(response.files)}",
                capture_output,
            )
            for f in response.files:
                _output(f"  {f['path']}", capture_output)
        return 0
    finally:
        if owns_db:
            await db.close()


@backfill_app.command("read-failures")
@async_command
async def read_failures_command(
    attempt_id: str | None = typer.Option(None, "--attempt-id"),
    repo_path: str | None = typer.Option(None, "--repo-path"),
    test_command: str | None = typer.Option(None, "--test-command"),
    as_json: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    """Run the test command and return failing test file paths + contents."""
    exit_code = await _read_failures_impl(
        attempt_id=attempt_id,
        repo_path=repo_path,
        test_command=test_command,
        as_json=as_json,
    )
    raise typer.Exit(exit_code)


# ---------------------------------------------------------------------------
# `write-test` — safety-gated test file write
# ---------------------------------------------------------------------------


async def _write_test_impl(
    path: str,
    content: str | None = None,
    repo_path: str | None = None,
    as_json: bool = False,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
    stdin_content: str | None = None,
) -> int:
    from forkhub.cli.helpers import get_services
    from forkhub.services.backfill import BackfillService

    # Resolve content
    if content is None:
        if stdin_content is not None:
            content = stdin_content
        elif sys.stdin.isatty():
            _output(
                "[red]Error: no --content given and stdin is a TTY. "
                "Pipe content via stdin or use --content.[/red]",
                capture_output,
            )
            return 2
        else:
            content = sys.stdin.read()

    owns_db = False
    if db is None or provider is None:
        _settings, db, provider = await get_services()
        owns_db = True

    try:
        effective_repo_path = Path(repo_path) if repo_path else Path.cwd()
        service = BackfillService(db=db, provider=provider, repo_path=effective_repo_path)

        try:
            target = service.write_test_file(path, content)
        except ValueError as exc:
            _output(f"[red]Error: {exc}[/red]", capture_output)
            return 1
        except OSError as exc:
            _output(f"[red]Write failed: {exc}[/red]", capture_output)
            return 2

        response = WriteTestResponse(path=str(target), bytes_written=len(content.encode("utf-8")))
        if as_json:
            _emit_json(response, capture_output)
        else:
            _output(f"Wrote {response.bytes_written} bytes to {response.path}", capture_output)
        return 0
    finally:
        if owns_db:
            await db.close()


@backfill_app.command("write-test")
@async_command
async def write_test_command(
    path: str = typer.Argument(..., help="Relative path to the test file (e.g. tests/test_foo.py)"),
    content: str | None = typer.Option(
        None, "--content", help="File content (if omitted, reads from stdin)"
    ),
    repo_path: str | None = typer.Option(None, "--repo-path"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Write a test file after validating the path against the safety gate.

    Rejects absolute paths, '..' traversal, and non-test paths.
    """
    exit_code = await _write_test_impl(
        path=path,
        content=content,
        repo_path=repo_path,
        as_json=as_json,
    )
    raise typer.Exit(exit_code)


# ---------------------------------------------------------------------------
# `run-tests` — run the test command and return structured result
# ---------------------------------------------------------------------------


async def _run_tests_impl(
    repo_path: str | None = None,
    test_command: str | None = None,
    as_json: bool = False,
    db: Database | None = None,
    provider: GitProvider | None = None,
    capture_output: list[str] | None = None,
) -> int:
    from forkhub.cli.helpers import get_services
    from forkhub.services.backfill import BackfillService

    owns_db = False
    if db is None or provider is None:
        _settings, db, provider = await get_services()
        owns_db = True

    try:
        effective_test_cmd = test_command or "uv run pytest -x --tb=short -q"
        effective_repo_path = Path(repo_path) if repo_path else Path.cwd()

        service = BackfillService(
            db=db,
            provider=provider,
            repo_path=effective_repo_path,
            test_command=effective_test_cmd,
        )
        result = await service.run_test_command()
        response = RunTestsResponse(
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )

        if as_json:
            _emit_json(response, capture_output)
        else:
            if response.stdout:
                _output(response.stdout, capture_output)
            if response.stderr:
                _output(response.stderr, capture_output)

        return max(0, min(255, response.returncode))
    finally:
        if owns_db:
            await db.close()


@backfill_app.command("run-tests")
@async_command
async def run_tests_command(
    repo_path: str | None = typer.Option(None, "--repo-path"),
    test_command: str | None = typer.Option(None, "--test-command"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Run the configured test command and return its result."""
    exit_code = await _run_tests_impl(
        repo_path=repo_path,
        test_command=test_command,
        as_json=as_json,
    )
    raise typer.Exit(exit_code)

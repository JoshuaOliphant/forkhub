# ABOUTME: Tests for the BackfillService agentic loop.
# ABOUTME: Uses stub providers and in-memory DB, no mock framework.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from forkhub.models import (
    BackfillAttempt,
    BackfillResult,
    BackfillStatus,
)
from forkhub.services.backfill import BackfillService

from .stubs import StubGitProvider, make_fork, make_signal, make_tracked_repo

if TYPE_CHECKING:
    from forkhub.database import Database

# ---------------------------------------------------------------------------
# Time constants
# ---------------------------------------------------------------------------

_NOW = datetime(2025, 6, 1, tzinfo=UTC)
_ACTIVE_DATE = _NOW - timedelta(days=30)


# ---------------------------------------------------------------------------
# Helpers: insert test data using shared factory helpers
# ---------------------------------------------------------------------------


async def _insert_tracked_repo(
    db: Database,
    owner: str = "upstream",
    name: str = "project",
    github_id: int = 1001,
) -> dict:
    """Insert a tracked repo and return the dict."""
    repo = make_tracked_repo(
        owner=owner, name=name, full_name=f"{owner}/{name}", github_id=github_id
    )
    await db.insert_tracked_repo(repo)
    return repo


async def _insert_fork(
    db: Database,
    tracked_repo_id: str,
    owner: str = "forker1",
    github_id: int = 5001,
) -> dict:
    """Insert a fork and return the dict."""
    fork = make_fork(
        tracked_repo_id,
        owner=owner,
        full_name=f"{owner}/project",
        github_id=github_id,
        vitality="active",
        stars=10,
        last_pushed_at=_ACTIVE_DATE.isoformat(),
    )
    await db.insert_fork(fork)
    return fork


async def _insert_signal(
    db: Database,
    tracked_repo_id: str,
    fork_id: str,
    category: str = "feature",
    summary: str = "Adds Redis caching layer",
    significance: int = 7,
    files: list[str] | None = None,
    is_upstream: bool = False,
) -> dict:
    """Insert a signal and return the dict."""
    sig = make_signal(
        fork_id,
        tracked_repo_id,
        category=category,
        summary=summary,
        significance=significance,
        files_involved=json.dumps(files or ["src/cache.py"]),
        is_upstream=is_upstream,
    )
    await db.insert_signal(sig)
    return sig


# ---------------------------------------------------------------------------
# Candidate gathering
# ---------------------------------------------------------------------------


class TestGatherCandidates:
    async def test_gathers_signals_above_min_significance(
        self, db: Database, provider: StubGitProvider
    ):
        """Only signals at or above min_significance should be candidates."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        await _insert_signal(db, repo["id"], fork["id"], significance=3)  # Below threshold
        await _insert_signal(db, repo["id"], fork["id"], significance=7)  # Above threshold

        service = BackfillService(db=db, provider=provider, min_significance=5)
        candidates = await service._gather_candidates(repo["id"])
        assert len(candidates) == 1
        assert candidates[0].significance == 7

    async def test_excludes_upstream_signals(self, db: Database, provider: StubGitProvider):
        """Upstream signals should not be backfill candidates."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        await _insert_signal(db, repo["id"], fork["id"], significance=8, is_upstream=True)
        await _insert_signal(db, repo["id"], fork["id"], significance=7, is_upstream=False)

        service = BackfillService(db=db, provider=provider, min_significance=5)
        candidates = await service._gather_candidates(repo["id"])
        assert len(candidates) == 1
        assert not candidates[0].is_upstream

    async def test_sorted_by_significance_descending(self, db: Database, provider: StubGitProvider):
        """Candidates should be sorted by significance, highest first."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        await _insert_signal(db, repo["id"], fork["id"], significance=6, summary="Medium")
        await _insert_signal(db, repo["id"], fork["id"], significance=9, summary="High")
        await _insert_signal(db, repo["id"], fork["id"], significance=7, summary="Notable")

        service = BackfillService(db=db, provider=provider, min_significance=5)
        candidates = await service._gather_candidates(repo["id"])
        assert len(candidates) == 3
        assert candidates[0].significance == 9
        assert candidates[1].significance == 7
        assert candidates[2].significance == 6

    async def test_empty_when_no_signals(self, db: Database, provider: StubGitProvider):
        """No signals means no candidates."""
        repo = await _insert_tracked_repo(db)
        service = BackfillService(db=db, provider=provider)
        candidates = await service._gather_candidates(repo["id"])
        assert candidates == []

    async def test_since_filter_applied(self, db: Database, provider: StubGitProvider):
        """The since parameter should filter out older signals."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        # Insert a signal — it will have created_at = now
        await _insert_signal(db, repo["id"], fork["id"], significance=8)

        service = BackfillService(db=db, provider=provider, min_significance=5)
        # Ask for signals from the future — should get none
        future = datetime.now(UTC) + timedelta(days=1)
        candidates = await service._gather_candidates(repo["id"], since=future)
        assert candidates == []

    async def test_excludes_signals_with_no_fork_id(self, db: Database, provider: StubGitProvider):
        """Signals with fork_id=None should be excluded from candidates."""
        repo = await _insert_tracked_repo(db)
        # Insert a signal directly with no fork_id
        sig = make_signal(
            "",
            repo["id"],
            significance=8,
            summary="Orphan signal",
        )
        sig["fork_id"] = None
        await db.insert_signal(sig)

        service = BackfillService(db=db, provider=provider, min_significance=5)
        candidates = await service._gather_candidates(repo["id"])
        assert candidates == []


# ---------------------------------------------------------------------------
# Backfill attempt recording (traces — principle 5)
# ---------------------------------------------------------------------------


class TestBackfillTraces:
    async def test_attempt_recorded_to_database(self, db: Database, provider: StubGitProvider):
        """Every backfill attempt should be persisted to the database."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        provider.set_file_diff("forker1", "src/cache.py", "some diff")
        await _insert_signal(db, repo["id"], fork["id"], significance=7)

        service = BackfillService(db=db, provider=provider, min_significance=5, max_attempts=1)
        # Dry run so we don't need real git
        await service.run_backfill(repo["id"], dry_run=True)

        attempts = await db.list_backfill_attempts(repo_id=repo["id"])
        assert len(attempts) == 1
        assert attempts[0]["status"] == "pending"

    async def test_skips_already_attempted_signals(self, db: Database, provider: StubGitProvider):
        """Signals that already have backfill attempts should be skipped."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        signal = await _insert_signal(db, repo["id"], fork["id"], significance=8)

        # Manually insert a prior attempt for this signal
        prior = BackfillAttempt(
            signal_id=signal["id"],
            fork_id=fork["id"],
            tracked_repo_id=repo["id"],
            status=BackfillStatus.TESTS_FAILED,
        )
        d = prior.model_dump()
        d["created_at"] = prior.created_at.isoformat()
        d["files_patched"] = json.dumps(prior.files_patched)
        await db.insert_backfill_attempt(d)

        service = BackfillService(db=db, provider=provider, min_significance=5, max_attempts=5)
        result = await service.run_backfill(repo["id"], dry_run=True)
        # The signal should be skipped since it was already attempted
        assert result.attempted == 0

    async def test_has_backfill_for_signal_returns_true(
        self, db: Database, provider: StubGitProvider
    ):
        """has_backfill_for_signal returns True when attempt exists."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        signal = await _insert_signal(db, repo["id"], fork["id"])

        assert not await db.has_backfill_for_signal(signal["id"])

        attempt = BackfillAttempt(
            signal_id=signal["id"],
            fork_id=fork["id"],
            tracked_repo_id=repo["id"],
        )
        d = attempt.model_dump()
        d["created_at"] = attempt.created_at.isoformat()
        d["files_patched"] = json.dumps(attempt.files_patched)
        await db.insert_backfill_attempt(d)

        assert await db.has_backfill_for_signal(signal["id"])


# ---------------------------------------------------------------------------
# Dry run mode
# ---------------------------------------------------------------------------


class TestDryRun:
    async def test_dry_run_does_not_apply_patches(self, db: Database, provider: StubGitProvider):
        """Dry run should evaluate candidates but not apply any patches."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        diff = "--- a/src/cache.py\n+++ b/src/cache.py\n@@ -1 +1 @@\n-old\n+new"
        provider.set_file_diff("forker1", "src/cache.py", diff)
        await _insert_signal(db, repo["id"], fork["id"], significance=7)

        service = BackfillService(db=db, provider=provider, min_significance=5, max_attempts=5)
        result = await service.run_backfill(repo["id"], dry_run=True)

        assert result.total_evaluated == 1
        assert result.attempted == 1
        assert result.accepted == 0
        assert result.branches_created == []

    async def test_dry_run_records_pending_attempt(self, db: Database, provider: StubGitProvider):
        """Dry run attempts should be recorded with 'pending' status."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        provider.set_file_diff("forker1", "src/cache.py", "some diff")
        await _insert_signal(db, repo["id"], fork["id"], significance=8)

        service = BackfillService(db=db, provider=provider, min_significance=5, max_attempts=1)
        await service.run_backfill(repo["id"], dry_run=True)

        attempts = await db.list_backfill_attempts(repo_id=repo["id"])
        assert len(attempts) == 1
        assert attempts[0]["status"] == "pending"


# ---------------------------------------------------------------------------
# Signal with missing fork
# ---------------------------------------------------------------------------


class TestMissingFork:
    async def test_signal_without_fork_id_skipped_in_candidates(
        self, db: Database, provider: StubGitProvider
    ):
        """A signal with no fork_id is filtered during candidate gathering."""
        repo = await _insert_tracked_repo(db)
        # Insert a signal directly with no fork_id
        sig = make_signal(
            "",
            repo["id"],
            significance=8,
            summary="Orphan signal",
        )
        sig["fork_id"] = None
        await db.insert_signal(sig)

        service = BackfillService(db=db, provider=provider, min_significance=5, max_attempts=1)
        result = await service.run_backfill(repo["id"])
        # Signal without fork_id is filtered out — nothing to evaluate
        assert result.total_evaluated == 0

    async def test_deleted_fork_fails_gracefully(self, db: Database, provider: StubGitProvider):
        """A signal referencing a deleted fork should fail gracefully."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        await _insert_signal(db, repo["id"], fork["id"], significance=8)

        # Delete the fork from DB to simulate it being removed.
        # ON DELETE CASCADE removes associated signals automatically.
        await db.delete_fork(fork["id"])

        service = BackfillService(db=db, provider=provider, min_significance=5, max_attempts=1)
        result = await service.run_backfill(repo["id"])
        # No signals remain after cascade, so nothing to attempt
        assert result.total_evaluated == 0


# ---------------------------------------------------------------------------
# Empty diff handling
# ---------------------------------------------------------------------------


class TestEmptyDiffs:
    async def test_no_diffs_available_results_in_patch_failed(
        self, db: Database, provider: StubGitProvider
    ):
        """When no diffs can be fetched, the attempt should be patch_failed."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        # Don't register any diffs in the provider
        await _insert_signal(db, repo["id"], fork["id"], significance=7)

        service = BackfillService(db=db, provider=provider, min_significance=5, max_attempts=1)
        result = await service.run_backfill(repo["id"])
        assert result.patch_failed == 1


# ---------------------------------------------------------------------------
# BackfillResult aggregation
# ---------------------------------------------------------------------------


class TestBackfillResult:
    async def test_result_counts_multiple_signals(self, db: Database, provider: StubGitProvider):
        """BackfillResult should aggregate counts across multiple signals."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        # Insert multiple signals
        for i in range(5):
            await _insert_signal(
                db,
                repo["id"],
                fork["id"],
                significance=6 + i % 3,
                summary=f"Signal {i}",
                files=[f"src/file_{i}.py"],
            )

        service = BackfillService(db=db, provider=provider, min_significance=5, max_attempts=10)
        result = await service.run_backfill(repo["id"], dry_run=True)
        assert result.total_evaluated == 5
        assert result.attempted == 5

    async def test_max_attempts_limits_processing(self, db: Database, provider: StubGitProvider):
        """max_attempts should cap how many signals are processed."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        for i in range(10):
            await _insert_signal(
                db,
                repo["id"],
                fork["id"],
                significance=7,
                summary=f"Signal {i}",
                files=[f"src/file_{i}.py"],
            )

        service = BackfillService(db=db, provider=provider, min_significance=5, max_attempts=3)
        result = await service.run_backfill(repo["id"], dry_run=True)
        assert result.total_evaluated == 10
        assert result.attempted == 3


# ---------------------------------------------------------------------------
# list_attempts
# ---------------------------------------------------------------------------


class TestListAttempts:
    async def test_list_attempts_returns_all(self, db: Database, provider: StubGitProvider):
        """list_attempts should return all recorded attempts."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        signal = await _insert_signal(db, repo["id"], fork["id"])

        for status in [BackfillStatus.ACCEPTED, BackfillStatus.TESTS_FAILED]:
            attempt = BackfillAttempt(
                signal_id=signal["id"],
                fork_id=fork["id"],
                tracked_repo_id=repo["id"],
                status=status,
            )
            d = attempt.model_dump()
            d["created_at"] = attempt.created_at.isoformat()
            d["files_patched"] = json.dumps(attempt.files_patched)
            await db.insert_backfill_attempt(d)

        service = BackfillService(db=db, provider=provider)
        attempts = await service.list_attempts(repo_id=repo["id"])
        assert len(attempts) == 2

    async def test_list_attempts_filters_by_status(self, db: Database, provider: StubGitProvider):
        """list_attempts should filter by status when provided."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        sig1 = await _insert_signal(db, repo["id"], fork["id"], summary="S1")
        sig2 = await _insert_signal(db, repo["id"], fork["id"], summary="S2")
        sig3 = await _insert_signal(db, repo["id"], fork["id"], summary="S3")

        for signal, status in [
            (sig1, BackfillStatus.ACCEPTED),
            (sig2, BackfillStatus.TESTS_FAILED),
            (sig3, BackfillStatus.ACCEPTED),
        ]:
            attempt = BackfillAttempt(
                signal_id=signal["id"],
                fork_id=fork["id"],
                tracked_repo_id=repo["id"],
                status=status,
            )
            d = attempt.model_dump()
            d["created_at"] = attempt.created_at.isoformat()
            d["files_patched"] = json.dumps(attempt.files_patched)
            await db.insert_backfill_attempt(d)

        service = BackfillService(db=db, provider=provider)
        accepted = await service.list_attempts(repo_id=repo["id"], status="accepted")
        assert len(accepted) == 2


# ---------------------------------------------------------------------------
# Database CRUD for backfill_attempts
# ---------------------------------------------------------------------------


class TestBackfillDatabase:
    async def test_insert_and_get(self, db: Database):
        """Should insert and retrieve a backfill attempt."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        signal = await _insert_signal(db, repo["id"], fork["id"])

        attempt = BackfillAttempt(
            signal_id=signal["id"],
            fork_id=fork["id"],
            tracked_repo_id=repo["id"],
            status=BackfillStatus.ACCEPTED,
            branch_name="backfill/feature/forker1-abc12345",
            patch_summary="Adds Redis caching",
            score=0.95,
            files_patched=["src/cache.py", "src/config.py"],
        )
        d = attempt.model_dump()
        d["created_at"] = attempt.created_at.isoformat()
        d["files_patched"] = json.dumps(attempt.files_patched)
        await db.insert_backfill_attempt(d)

        retrieved = await db.get_backfill_attempt(attempt.id)
        assert retrieved is not None
        assert retrieved["status"] == "accepted"
        assert retrieved["branch_name"] == "backfill/feature/forker1-abc12345"
        assert retrieved["score"] == 0.95

    async def test_update_attempt(self, db: Database):
        """Should update a backfill attempt's status and fields."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        signal = await _insert_signal(db, repo["id"], fork["id"])

        attempt = BackfillAttempt(
            signal_id=signal["id"],
            fork_id=fork["id"],
            tracked_repo_id=repo["id"],
            status=BackfillStatus.PENDING,
        )
        d = attempt.model_dump()
        d["created_at"] = attempt.created_at.isoformat()
        d["files_patched"] = json.dumps(attempt.files_patched)
        await db.insert_backfill_attempt(d)

        # Update the status
        d["status"] = "accepted"
        d["score"] = 1.0
        d["branch_name"] = "backfill/fix/forker1-abc"
        await db.update_backfill_attempt(d)

        retrieved = await db.get_backfill_attempt(attempt.id)
        assert retrieved is not None
        assert retrieved["status"] == "accepted"
        assert retrieved["score"] == 1.0

    async def test_list_with_multiple_filters(self, db: Database):
        """list_backfill_attempts should support multiple filters."""
        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])

        signals = []
        for i in range(3):
            sig = await _insert_signal(db, repo["id"], fork["id"], summary=f"Sig {i}")
            signals.append(sig)

        for sig, status in zip(
            signals,
            ["accepted", "tests_failed", "accepted"],
            strict=True,
        ):
            attempt = BackfillAttempt(
                signal_id=sig["id"],
                fork_id=fork["id"],
                tracked_repo_id=repo["id"],
                status=BackfillStatus(status),
            )
            d = attempt.model_dump()
            d["created_at"] = attempt.created_at.isoformat()
            d["files_patched"] = json.dumps(attempt.files_patched)
            await db.insert_backfill_attempt(d)

        # Filter by repo + status
        rows = await db.list_backfill_attempts(repo_id=repo["id"], status="accepted")
        assert len(rows) == 2

        # Filter by signal_id
        rows = await db.list_backfill_attempts(signal_id=signals[1]["id"])
        assert len(rows) == 1
        assert rows[0]["status"] == "tests_failed"


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestBackfillModels:
    def test_backfill_status_enum_values(self):
        """BackfillStatus should have all expected values."""
        assert BackfillStatus.PENDING == "pending"
        assert BackfillStatus.PATCH_FAILED == "patch_failed"
        assert BackfillStatus.TESTS_FAILED == "tests_failed"
        assert BackfillStatus.CONFLICT == "conflict"
        assert BackfillStatus.ACCEPTED == "accepted"
        assert BackfillStatus.REJECTED == "rejected"

    def test_backfill_attempt_default_values(self):
        """BackfillAttempt should have sensible defaults."""
        attempt = BackfillAttempt(
            signal_id="sig-1",
            fork_id="fork-1",
            tracked_repo_id="repo-1",
        )
        assert attempt.status == BackfillStatus.PENDING
        assert attempt.branch_name is None
        assert attempt.files_patched == []
        assert attempt.score is None
        assert attempt.id  # UUID should be generated

    def test_backfill_result_default_values(self):
        """BackfillResult should start with zero counts."""
        result = BackfillResult()
        assert result.total_evaluated == 0
        assert result.attempted == 0
        assert result.accepted == 0
        assert result.patch_failed == 0
        assert result.tests_failed == 0
        assert result.conflicts == 0
        assert result.branches_created == []


# ---------------------------------------------------------------------------
# Security: exec-based subprocess (Issue 1)
# ---------------------------------------------------------------------------


class TestRunExec:
    async def test_run_exec_runs_command_and_returns_stdout(self, tmp_path, db, provider):
        """_run_exec should run a command and capture stdout without shell."""
        import subprocess

        service = BackfillService(db=db, provider=provider, repo_path=tmp_path)
        result = await service._run_exec(["echo", "hello"], cwd=tmp_path)
        assert isinstance(result, subprocess.CompletedProcess)
        assert result.stdout.strip() == "hello"
        assert result.returncode == 0

    async def test_run_exec_does_not_expand_shell_metacharacters(self, tmp_path, db, provider):
        """_run_exec must not expand shell metacharacters — args are literal."""
        service = BackfillService(db=db, provider=provider, repo_path=tmp_path)
        result = await service._run_exec(["echo", "$HOME"], cwd=tmp_path)
        assert result.stdout.strip() == "$HOME"

    async def test_run_exec_passes_stdin_data(self, tmp_path, db, provider):
        """_run_exec should pass stdin_data bytes to the process stdin."""
        service = BackfillService(db=db, provider=provider, repo_path=tmp_path)
        result = await service._run_exec(["cat"], cwd=tmp_path, stdin_data=b"patch content")
        assert result.stdout == "patch content"

    async def test_run_exec_times_out_and_returns_error(self, tmp_path, db, provider):
        """_run_exec should return returncode -1 when command times out."""
        service = BackfillService(db=db, provider=provider, repo_path=tmp_path)
        result = await service._run_exec(["sleep", "10"], cwd=tmp_path, timeout=1)
        assert result.returncode == -1
        assert "timed out" in result.stderr.lower()

    async def test_run_shell_no_longer_exists(self, db, provider):
        """_run_shell must be removed — exec-based approach replaces it."""
        service = BackfillService(db=db, provider=provider)
        assert not hasattr(service, "_run_shell"), (
            "_run_shell must be deleted; use _run_exec instead"
        )

    async def test_shell_quote_no_longer_exists(self, db, provider):
        """_shell_quote module-level function must be removed."""
        import forkhub.services.backfill as backfill_mod

        assert not hasattr(backfill_mod, "_shell_quote"), (
            "_shell_quote must be deleted along with _run_shell"
        )


# ---------------------------------------------------------------------------
# Security: branch cleanup on exception (Issue 8)
# ---------------------------------------------------------------------------


class TestBranchLeakOnException:
    async def test_candidate_branch_cleaned_up_on_patch_failure(self, tmp_path, db, provider):
        """When _apply_and_test raises, the candidate branch must not linger."""
        import subprocess

        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path),
            check=True,
            capture_output=True,
        )
        (tmp_path / "README.md").write_text("hello")
        subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=str(tmp_path), check=True, capture_output=True
        )

        repo = await _insert_tracked_repo(db)
        fork = await _insert_fork(db, repo["id"])
        signal = await _insert_signal(
            db, repo["id"], fork["id"], significance=8, files=["src/cache.py"]
        )
        provider.set_file_diff(
            "forker1",
            "src/cache.py",
            "--- a/src/cache.py\n+++ b/src/cache.py\n@@ -1 +1 @@\n-old\n+new",
        )

        service = BackfillService(db=db, provider=provider, repo_path=tmp_path, min_significance=5)
        await service.run_backfill(repo["id"])

        result = subprocess.run(
            ["git", "branch"], cwd=str(tmp_path), capture_output=True, text=True
        )
        branch_name = f"backfill/{signal['category']}/{fork['owner']}-{signal['id'][:8]}"
        assert branch_name not in result.stdout, (
            f"Candidate branch '{branch_name}' was not cleaned up after failure"
        )


# ---------------------------------------------------------------------------
# Security: targeted git add (Issue 6)
# ---------------------------------------------------------------------------


class TestTargetedGitAdd:
    async def test_run_git_uses_exec_not_shell(self, tmp_path, db, provider):
        """_run_git must delegate to _run_exec, not _run_shell."""
        import inspect

        service = BackfillService(db=db, provider=provider, repo_path=tmp_path)
        source = inspect.getsource(service._run_git)
        assert "_run_exec" in source or "_run_safe_cmd" in source, (
            "_run_git must call _run_exec or _run_safe_cmd"
        )
        assert "_run_shell" not in source, "_run_git must not call _run_shell"

    async def test_apply_and_test_uses_targeted_add(self, db, provider):
        """_apply_and_test must stage only files_patched, not git add -A."""
        import inspect

        service = BackfillService(db=db, provider=provider)
        source = inspect.getsource(service._apply_and_test)
        assert '"add", "--"' in source or '"add", "--", *' in source, (
            "_apply_and_test must use 'git add -- <files>' not 'git add -A'"
        )
        assert '"add", "-A"' not in source, "_apply_and_test must not use 'git add -A'"


# ---------------------------------------------------------------------------
# run_backfill_all
# ---------------------------------------------------------------------------


class TestRunBackfillAll:
    async def test_single_repo_mode(self, db: Database, provider: StubGitProvider):
        """run_backfill_all with repo_id should only process that repo."""
        repo1 = await _insert_tracked_repo(db, owner="owner1", name="proj1", github_id=1001)
        repo2 = await _insert_tracked_repo(db, owner="owner2", name="proj2", github_id=1002)
        fork1 = await _insert_fork(db, repo1["id"], owner="forkerA", github_id=5001)
        fork2 = await _insert_fork(db, repo2["id"], owner="forkerB", github_id=5002)
        await _insert_signal(db, repo1["id"], fork1["id"], significance=8, summary="S1")
        await _insert_signal(db, repo2["id"], fork2["id"], significance=8, summary="S2")

        service = BackfillService(db=db, provider=provider, min_significance=5, max_attempts=10)
        result = await service.run_backfill_all(repo_id=repo1["id"], dry_run=True)

        # Should only evaluate signals from repo1
        assert result.total_evaluated == 1

    async def test_all_repos_mode(self, db: Database, provider: StubGitProvider):
        """run_backfill_all without repo_id should process all tracked repos."""
        repo1 = await _insert_tracked_repo(db, owner="owner1", name="proj1", github_id=1001)
        repo2 = await _insert_tracked_repo(db, owner="owner2", name="proj2", github_id=1002)
        fork1 = await _insert_fork(db, repo1["id"], owner="forkerA", github_id=5001)
        fork2 = await _insert_fork(db, repo2["id"], owner="forkerB", github_id=5002)
        await _insert_signal(db, repo1["id"], fork1["id"], significance=8, summary="S1")
        await _insert_signal(db, repo2["id"], fork2["id"], significance=8, summary="S2")

        service = BackfillService(db=db, provider=provider, min_significance=5, max_attempts=10)
        result = await service.run_backfill_all(dry_run=True)

        # Should evaluate signals from both repos
        assert result.total_evaluated == 2

    async def test_on_repo_start_callback(self, db: Database, provider: StubGitProvider):
        """on_repo_start should be called with repo full_name before each repo."""
        repo = await _insert_tracked_repo(db, owner="upstream", name="project")
        fork = await _insert_fork(db, repo["id"])
        await _insert_signal(db, repo["id"], fork["id"], significance=8)

        called_with: list[str] = []
        service = BackfillService(db=db, provider=provider, min_significance=5)
        await service.run_backfill_all(
            dry_run=True,
            on_repo_start=lambda name: called_with.append(name),
        )

        assert called_with == ["upstream/project"]

    async def test_aggregates_results_across_repos(self, db: Database, provider: StubGitProvider):
        """Results from multiple repos should be aggregated correctly."""
        repo1 = await _insert_tracked_repo(db, owner="o1", name="p1", github_id=1001)
        repo2 = await _insert_tracked_repo(db, owner="o2", name="p2", github_id=1002)
        fork1 = await _insert_fork(db, repo1["id"], owner="f1", github_id=5001)
        fork2 = await _insert_fork(db, repo2["id"], owner="f2", github_id=5002)
        for i in range(3):
            await _insert_signal(
                db,
                repo1["id"],
                fork1["id"],
                significance=7,
                summary=f"R1-S{i}",
                files=[f"r1_{i}.py"],
            )
        for i in range(2):
            await _insert_signal(
                db,
                repo2["id"],
                fork2["id"],
                significance=6,
                summary=f"R2-S{i}",
                files=[f"r2_{i}.py"],
            )

        service = BackfillService(db=db, provider=provider, min_significance=5, max_attempts=10)
        result = await service.run_backfill_all(dry_run=True)

        assert result.total_evaluated == 5
        assert result.attempted == 5

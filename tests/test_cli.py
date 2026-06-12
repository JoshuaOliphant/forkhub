# ABOUTME: Tests for all CLI commands in ForkHub Wave 5.
# ABOUTME: Uses Typer CliRunner for smoke tests and direct async function tests with stubs.

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

    from forkhub.database import Database
from typer.testing import CliRunner

from forkhub.cli.app import app
from forkhub.models import (
    Cluster,
    Fork,
    ForkVitality,
    Signal,
    SignalCategory,
)
from tests.stubs import StubGitProvider

runner = CliRunner()

_NOW = datetime(2025, 6, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def provider() -> StubGitProvider:
    """CLI tests need the testuser data pre-loaded."""
    return StubGitProvider.with_testuser_data()


# ---------------------------------------------------------------------------
# Smoke tests via CliRunner
# ---------------------------------------------------------------------------


class TestCLISmoke:
    """Basic CliRunner smoke tests for --version, --help, and subcommand help."""

    def test_version_and_help(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "forkhub" in result.output
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Monitor GitHub fork constellations" in result.output

    @pytest.mark.parametrize(
        "subcommand",
        [
            "init",
            "track",
            "untrack",
            "exclude",
            "include",
            "forks",
            "inspect",
            "clusters",
            "sync",
            "digest",
            "config",
            "repos",
            "backfill",
        ],
    )
    def test_subcommand_help(self, subcommand):
        result = runner.invoke(app, [subcommand, "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------


class TestInitCommand:
    async def test_init_detects_upstream_repos(
        self, db: Database, provider: StubGitProvider, tmp_path: Path
    ):
        """init should also detect upstream repos."""
        from forkhub.cli.init_cmd import _init_impl

        await _init_impl(
            username="testuser",
            token="ghp_faketoken123",
            config_dir=tmp_path,
            db=db,
            provider=provider,
        )

        # Should have detected upstream repos too
        repos = await db.list_tracked_repos()
        modes = [r["tracking_mode"] for r in repos]
        assert "upstream" in modes

    async def test_init_fails_without_token(
        self,
        db: Database,
        provider: StubGitProvider,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """init should error when no token is provided and GITHUB_TOKEN is unset."""
        from forkhub.cli.init_cmd import _init_impl

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        output_lines: list[str] = []
        await _init_impl(
            username="testuser",
            token=None,
            config_dir=tmp_path,
            db=db,
            provider=provider,
            capture_output=output_lines,
        )

        output = "\n".join(output_lines)
        assert "GITHUB_TOKEN" in output or "token" in output.lower()


# ---------------------------------------------------------------------------
# track / untrack / exclude / include commands
# ---------------------------------------------------------------------------


class TestTrackCommands:
    async def test_track_already_tracked_shows_error(self, db: Database, provider: StubGitProvider):
        """Tracking an already tracked repo should show an error message."""
        from forkhub.cli.track_cmd import _track_impl

        await _track_impl(repo="testuser/alpha", db=db, provider=provider)

        output_lines: list[str] = []
        await _track_impl(
            repo="testuser/alpha",
            db=db,
            provider=provider,
            capture_output=output_lines,
        )

        output = "\n".join(output_lines)
        assert "already tracked" in output.lower() or "error" in output.lower()

    async def test_untrack_removes_repo(self, db: Database, provider: StubGitProvider):
        """untrack should remove a repo."""
        from forkhub.cli.track_cmd import _track_impl, _untrack_impl

        await _track_impl(repo="testuser/alpha", db=db, provider=provider)
        output_lines: list[str] = []
        await _untrack_impl(
            repo="testuser/alpha",
            db=db,
            capture_output=output_lines,
        )

        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is None

        output = "\n".join(output_lines)
        assert "untracked" in output.lower() or "removed" in output.lower()

    async def test_include_clears_flag(self, db: Database, provider: StubGitProvider):
        """include should clear the excluded flag."""
        from forkhub.cli.track_cmd import _exclude_impl, _include_impl, _track_impl

        await _track_impl(repo="testuser/alpha", db=db, provider=provider)
        await _exclude_impl(repo="testuser/alpha", db=db)
        output_lines: list[str] = []
        await _include_impl(
            repo="testuser/alpha",
            db=db,
            capture_output=output_lines,
        )

        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is not None
        assert row["excluded"] == 0


# ---------------------------------------------------------------------------
# repos command
# ---------------------------------------------------------------------------


class TestReposCommand:
    async def test_repos_empty_shows_message(self, db: Database, provider: StubGitProvider):
        """repos with no tracked repos should show a helpful message."""
        from forkhub.cli.repos_cmd import _repos_impl

        output_lines: list[str] = []
        await _repos_impl(db=db, provider=provider, mode=None, capture_output=output_lines)

        output = "\n".join(output_lines)
        assert "no" in output.lower() or "empty" in output.lower()


# ---------------------------------------------------------------------------
# forks command
# ---------------------------------------------------------------------------


class TestForksCommand:
    async def test_forks_lists_forks(self, db: Database, provider: StubGitProvider):
        """forks should list forks for a tracked repo."""
        from forkhub.cli.forks_cmd import _forks_impl
        from forkhub.cli.track_cmd import _track_impl

        await _track_impl(repo="testuser/alpha", db=db, provider=provider)

        # Insert a fork for this repo
        repo_row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert repo_row is not None
        fork = Fork(
            tracked_repo_id=repo_row["id"],
            github_id=9001,
            owner="someone",
            full_name="someone/alpha",
            default_branch="main",
            stars=42,
            commits_ahead=5,
            commits_behind=2,
            vitality=ForkVitality.ACTIVE,
        )
        fork_dict = fork.model_dump()
        fork_dict["created_at"] = fork.created_at.isoformat()
        fork_dict["updated_at"] = fork.updated_at.isoformat()
        fork_dict["last_pushed_at"] = None
        await db.insert_fork(fork_dict)

        output_lines: list[str] = []
        await _forks_impl(
            repo="testuser/alpha",
            active=False,
            sort="stars",
            limit=10,
            db=db,
            capture_output=output_lines,
        )

        output = "\n".join(output_lines)
        assert "someone/alpha" in output

    async def test_forks_repo_not_found(self, db: Database):
        """forks for non-tracked repo should show an error."""
        from forkhub.cli.forks_cmd import _forks_impl

        output_lines: list[str] = []
        await _forks_impl(
            repo="nobody/nothing",
            active=False,
            sort="stars",
            limit=10,
            db=db,
            capture_output=output_lines,
        )

        output = "\n".join(output_lines)
        assert "not found" in output.lower() or "not tracked" in output.lower()


# ---------------------------------------------------------------------------
# inspect command
# ---------------------------------------------------------------------------


class TestInspectCommand:
    async def test_inspect_shows_fork_details(self, db: Database, provider: StubGitProvider):
        """inspect should show detailed fork info with signals."""
        from forkhub.cli.forks_cmd import _inspect_impl
        from forkhub.cli.track_cmd import _track_impl

        await _track_impl(repo="testuser/alpha", db=db, provider=provider)
        repo_row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert repo_row is not None

        # Insert a fork
        fork = Fork(
            tracked_repo_id=repo_row["id"],
            github_id=9001,
            owner="someone",
            full_name="someone/alpha",
            default_branch="main",
            stars=42,
            vitality=ForkVitality.ACTIVE,
        )
        fork_dict = fork.model_dump()
        fork_dict["created_at"] = fork.created_at.isoformat()
        fork_dict["updated_at"] = fork.updated_at.isoformat()
        fork_dict["last_pushed_at"] = None
        await db.insert_fork(fork_dict)

        # Insert a signal for this fork
        signal = Signal(
            fork_id=fork.id,
            tracked_repo_id=repo_row["id"],
            category=SignalCategory.FEATURE,
            summary="Added dark mode support",
            significance=8,
            files_involved=["src/theme.py"],
        )
        signal_dict = signal.model_dump()
        signal_dict["created_at"] = signal.created_at.isoformat()
        signal_dict["files_involved"] = json.dumps(signal.files_involved)
        signal_dict["embedding"] = None
        await db.insert_signal(signal_dict)

        output_lines: list[str] = []
        await _inspect_impl(
            fork_name="someone/alpha",
            db=db,
            capture_output=output_lines,
        )

        output = "\n".join(output_lines)
        assert "someone/alpha" in output
        assert "dark mode" in output.lower() or "feature" in output.lower()

    async def test_inspect_fork_not_found(self, db: Database):
        """inspect for non-existent fork should show error."""
        from forkhub.cli.forks_cmd import _inspect_impl

        output_lines: list[str] = []
        await _inspect_impl(
            fork_name="nobody/nothing",
            db=db,
            capture_output=output_lines,
        )

        output = "\n".join(output_lines)
        assert "not found" in output.lower()

    async def test_inspect_signal_preserves_created_at(
        self, db: Database, provider: StubGitProvider, monkeypatch: pytest.MonkeyPatch
    ):
        """The Signal hydrated for rendering must keep the row's stored created_at.

        inspect builds a Signal per signal row to render. If it constructs the
        model field-by-field and omits created_at, the field silently defaults
        to read time. This pins the round-trip: a signal stored with an explicit
        historic created_at must surface that same value on the rendered model.
        """
        from forkhub.cli import forks_cmd
        from forkhub.cli.forks_cmd import _inspect_impl
        from forkhub.cli.track_cmd import _track_impl

        await _track_impl(repo="testuser/alpha", db=db, provider=provider)
        repo_row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert repo_row is not None

        fork = Fork(
            tracked_repo_id=repo_row["id"],
            github_id=9101,
            owner="someone",
            full_name="someone/alpha",
            default_branch="main",
            vitality=ForkVitality.ACTIVE,
        )
        fork_dict = fork.model_dump()
        fork_dict["created_at"] = fork.created_at.isoformat()
        fork_dict["updated_at"] = fork.updated_at.isoformat()
        fork_dict["last_pushed_at"] = None
        await db.insert_fork(fork_dict)

        stored_at = datetime(2024, 2, 3, 4, 5, 6, tzinfo=UTC)
        signal = Signal(
            fork_id=fork.id,
            tracked_repo_id=repo_row["id"],
            category=SignalCategory.FEATURE,
            summary="Added dark mode support",
            significance=8,
            files_involved=["src/theme.py"],
            created_at=stored_at,
        )
        signal_dict = signal.model_dump()
        signal_dict["created_at"] = signal.created_at.isoformat()
        signal_dict["files_involved"] = json.dumps(signal.files_involved)
        signal_dict["embedding"] = None
        await db.insert_signal(signal_dict)

        # Capture the Signal the impl builds for rendering (non-capture branch).
        rendered: list[Signal] = []
        monkeypatch.setattr(
            forks_cmd, "render_signal", lambda _console, sig: rendered.append(sig)
        )

        await _inspect_impl(fork_name="someone/alpha", db=db)

        assert len(rendered) == 1
        assert rendered[0].created_at == stored_at
        assert rendered[0].files_involved == ["src/theme.py"]


# ---------------------------------------------------------------------------
# clusters command
# ---------------------------------------------------------------------------


class TestClustersCommand:
    async def test_clusters_shows_clusters(self, db: Database, provider: StubGitProvider):
        """clusters should show cluster info for a repo."""
        from forkhub.cli.clusters_cmd import _clusters_impl
        from forkhub.cli.track_cmd import _track_impl

        await _track_impl(repo="testuser/alpha", db=db, provider=provider)
        repo_row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert repo_row is not None

        # Insert a cluster
        cluster_dict = {
            "id": "cluster-1",
            "tracked_repo_id": repo_row["id"],
            "label": "feature in theme",
            "description": "Cluster of 3 forks with similar changes",
            "files_pattern": json.dumps(["src/theme.py"]),
            "fork_count": 3,
            "created_at": _NOW.isoformat(),
            "updated_at": _NOW.isoformat(),
        }
        await db.insert_cluster(cluster_dict)

        output_lines: list[str] = []
        await _clusters_impl(
            repo="testuser/alpha",
            min_size=2,
            db=db,
            capture_output=output_lines,
        )

        output = "\n".join(output_lines)
        assert "theme" in output.lower() or "cluster" in output.lower()

    async def test_clusters_preserve_created_at(
        self, db: Database, provider: StubGitProvider, monkeypatch: pytest.MonkeyPatch
    ):
        """The Cluster hydrated for rendering must keep the row's stored created_at.

        clusters builds a Cluster per row to render. Field-by-field construction
        that omits created_at silently defaults it to read time. This pins the
        round-trip on the rendered model.
        """
        from forkhub.cli import clusters_cmd
        from forkhub.cli.clusters_cmd import _clusters_impl
        from forkhub.cli.track_cmd import _track_impl

        await _track_impl(repo="testuser/alpha", db=db, provider=provider)
        repo_row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert repo_row is not None

        stored_at = datetime(2024, 5, 6, 7, 8, 9, tzinfo=UTC)
        cluster_dict = {
            "id": "cluster-rt",
            "tracked_repo_id": repo_row["id"],
            "label": "feature in theme",
            "description": "Cluster of 3 forks with similar changes",
            "files_pattern": json.dumps(["src/theme.py"]),
            "fork_count": 3,
            "created_at": stored_at.isoformat(),
            "updated_at": stored_at.isoformat(),
        }
        await db.insert_cluster(cluster_dict)

        # Capture the Cluster the impl builds for rendering (non-capture branch).
        rendered: list[Cluster] = []
        monkeypatch.setattr(
            clusters_cmd, "render_cluster", lambda _console, cl: rendered.append(cl)
        )

        await _clusters_impl(repo="testuser/alpha", min_size=2, db=db)

        assert len(rendered) == 1
        assert rendered[0].created_at == stored_at
        assert rendered[0].files_pattern == ["src/theme.py"]

    async def test_clusters_no_clusters(self, db: Database, provider: StubGitProvider):
        """clusters with no results should show a message."""
        from forkhub.cli.clusters_cmd import _clusters_impl
        from forkhub.cli.track_cmd import _track_impl

        await _track_impl(repo="testuser/alpha", db=db, provider=provider)

        output_lines: list[str] = []
        await _clusters_impl(
            repo="testuser/alpha",
            min_size=2,
            db=db,
            capture_output=output_lines,
        )

        output = "\n".join(output_lines)
        assert "no cluster" in output.lower() or "none" in output.lower()


# ---------------------------------------------------------------------------
# sync command
# ---------------------------------------------------------------------------


class TestSyncCommand:
    async def test_sync_single_repo(self, db: Database, provider: StubGitProvider):
        """sync --repo should sync only that repo."""
        from forkhub.cli.sync_cmd import _sync_impl
        from forkhub.cli.track_cmd import _track_impl
        from forkhub.config import SyncSettings

        await _track_impl(repo="testuser/alpha", db=db, provider=provider)
        await _track_impl(repo="testuser/beta", db=db, provider=provider)

        output_lines: list[str] = []
        await _sync_impl(
            repo="testuser/alpha",
            db=db,
            provider=provider,
            sync_settings=SyncSettings(),
            capture_output=output_lines,
        )

        output = "\n".join(output_lines)
        assert "testuser/alpha" in output

    async def test_sync_repo_not_found(self, db: Database, provider: StubGitProvider):
        """sync --repo with non-tracked repo should show error."""
        from forkhub.cli.sync_cmd import _sync_impl
        from forkhub.config import SyncSettings

        output_lines: list[str] = []
        await _sync_impl(
            repo="nobody/nothing",
            db=db,
            provider=provider,
            sync_settings=SyncSettings(),
            capture_output=output_lines,
        )

        output = "\n".join(output_lines)
        assert "not found" in output.lower() or "not tracked" in output.lower()

    async def test_sync_no_analyze_flag_skips_auto_built_analyzer(
        self, db: Database, provider: StubGitProvider
    ):
        """With `auto_analyze=False` and no injected analyzer, `_sync_impl`
        must NOT attempt to construct a ClaudeAnalyzer. Sync should still
        complete successfully."""
        from forkhub.cli.sync_cmd import _sync_impl
        from forkhub.cli.track_cmd import _track_impl
        from forkhub.config import SyncSettings

        await _track_impl(repo="testuser/alpha", db=db, provider=provider)

        output_lines: list[str] = []
        await _sync_impl(
            repo="testuser/alpha",
            db=db,
            provider=provider,
            sync_settings=SyncSettings(),
            capture_output=output_lines,
            auto_analyze=False,
        )

        output = "\n".join(output_lines)
        # With no analyzer wired, the CLI must distinguish "skipped"
        # from a real "0 signals" result so the user isn't misled.
        assert "New signals: skipped (no analyzer)" in output

    async def test_sync_output_shows_new_signals_count(
        self, db: Database, provider: StubGitProvider
    ):
        """The single-repo sync output must include a 'New signals:' line."""
        from forkhub.cli.sync_cmd import _sync_impl
        from forkhub.cli.track_cmd import _track_impl
        from forkhub.config import SyncSettings

        from .stubs import StubAnalyzer

        await _track_impl(repo="testuser/alpha", db=db, provider=provider)

        output_lines: list[str] = []
        await _sync_impl(
            repo="testuser/alpha",
            db=db,
            provider=provider,
            sync_settings=SyncSettings(),
            capture_output=output_lines,
            auto_analyze=False,
            analyzer=StubAnalyzer(),
        )

        output = "\n".join(output_lines)
        assert "New signals:" in output


# ---------------------------------------------------------------------------
# digest command
# ---------------------------------------------------------------------------


class TestDigestCommand:
    async def test_digest_generates_and_shows(self, db: Database, provider: StubGitProvider):
        """digest should generate a digest and show it."""
        from forkhub.cli.digest_cmd import _digest_impl
        from forkhub.cli.track_cmd import _track_impl

        await _track_impl(repo="testuser/alpha", db=db, provider=provider)

        output_lines: list[str] = []
        await _digest_impl(
            since=None,
            dry_run=True,
            db=db,
            capture_output=output_lines,
        )

        output = "\n".join(output_lines)
        assert "digest" in output.lower()


# ---------------------------------------------------------------------------
# config commands
# ---------------------------------------------------------------------------


class TestConfigCommands:
    async def test_config_show_and_path(self, tmp_path: Path):
        """config show and config path should display settings and directory."""
        from forkhub.cli.config_cmd import _config_path_impl, _config_show_impl

        # config show
        output_lines: list[str] = []
        await _config_show_impl(config_path=None, capture_output=output_lines)
        output = "\n".join(output_lines)
        assert "github" in output.lower() or "database" in output.lower()

        # config path
        output_lines = []
        await _config_path_impl(capture_output=output_lines)
        output = "\n".join(output_lines)
        assert "forkhub" in output.lower()
        assert ".config" in output or "config" in output.lower()

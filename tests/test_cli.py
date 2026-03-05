# ABOUTME: Tests for all CLI commands in ForkHub Wave 5.
# ABOUTME: Uses Typer CliRunner for smoke tests and direct async function tests with stubs.

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path
from typer.testing import CliRunner

from forkhub.cli.app import app
from forkhub.database import Database
from forkhub.models import (
    CommitInfo,
    CompareResult,
    Fork,
    ForkPage,
    ForkVitality,
    RateLimitInfo,
    Release,
    RepoInfo,
    Signal,
    SignalCategory,
    TrackingMode,
)

runner = CliRunner()

_NOW = datetime(2025, 6, 1, tzinfo=UTC)


# ---------------------------------------------------------------------------
# StubGitProvider for CLI tests
# ---------------------------------------------------------------------------


class StubGitProvider:
    """Stub GitProvider for CLI tests with canned data."""

    def __init__(self) -> None:
        self.user_repos: dict[str, list[RepoInfo]] = {
            "testuser": [
                RepoInfo(
                    github_id=1001,
                    owner="testuser",
                    name="alpha",
                    full_name="testuser/alpha",
                    default_branch="main",
                    description="Alpha project",
                    is_fork=False,
                    parent_full_name=None,
                    stars=10,
                    forks_count=3,
                    last_pushed_at=_NOW,
                ),
                RepoInfo(
                    github_id=1002,
                    owner="testuser",
                    name="beta",
                    full_name="testuser/beta",
                    default_branch="main",
                    description="Beta project",
                    is_fork=False,
                    parent_full_name=None,
                    stars=5,
                    forks_count=1,
                    last_pushed_at=_NOW,
                ),
                RepoInfo(
                    github_id=1003,
                    owner="testuser",
                    name="forked-lib",
                    full_name="testuser/forked-lib",
                    default_branch="main",
                    description="A forked library",
                    is_fork=True,
                    parent_full_name="upstream-org/forked-lib",
                    stars=0,
                    forks_count=0,
                    last_pushed_at=_NOW,
                ),
            ],
        }
        self.repos: dict[str, RepoInfo] = {
            "testuser/alpha": self.user_repos["testuser"][0],
            "testuser/beta": self.user_repos["testuser"][1],
            "testuser/forked-lib": self.user_repos["testuser"][2],
            "upstream-org/forked-lib": RepoInfo(
                github_id=2001,
                owner="upstream-org",
                name="forked-lib",
                full_name="upstream-org/forked-lib",
                default_branch="main",
                description="The original library",
                is_fork=False,
                parent_full_name=None,
                stars=500,
                forks_count=50,
                last_pushed_at=_NOW,
            ),
        }

    async def get_user_repos(self, username: str) -> list[RepoInfo]:
        return self.user_repos.get(username, [])

    async def get_repo(self, owner: str, repo: str) -> RepoInfo:
        full_name = f"{owner}/{repo}"
        if full_name not in self.repos:
            raise ValueError(f"Repo not found: {full_name}")
        return self.repos[full_name]

    async def get_forks(self, owner: str, repo: str, *, page: int = 1) -> ForkPage:
        return ForkPage(forks=[], total_count=0, page=1, has_next=False)

    async def compare(self, owner: str, repo: str, base: str, head: str) -> CompareResult:
        return CompareResult(ahead_by=0, behind_by=0, files=[], commits=[])

    async def get_releases(
        self, owner: str, repo: str, *, since: datetime | None = None
    ) -> list[Release]:
        return []

    async def get_commit_messages(
        self, owner: str, repo: str, *, since: str | None = None
    ) -> list[CommitInfo]:
        return []

    async def get_file_diff(self, owner: str, repo: str, base: str, head: str, path: str) -> str:
        return ""

    async def get_rate_limit(self) -> RateLimitInfo:
        return RateLimitInfo(limit=5000, remaining=4999, reset_at=_NOW)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    """Provide an in-memory Database connected and schema-created."""
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def provider() -> StubGitProvider:
    return StubGitProvider()


# ---------------------------------------------------------------------------
# Smoke tests via CliRunner
# ---------------------------------------------------------------------------


class TestCLISmoke:
    """Basic CliRunner smoke tests for --version, --help, and subcommand help."""

    def test_version(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "forkhub" in result.output

    def test_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Monitor GitHub fork constellations" in result.output

    def test_init_help(self):
        result = runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0
        assert "init" in result.output.lower() or "user" in result.output.lower()

    def test_track_help(self):
        result = runner.invoke(app, ["track", "--help"])
        assert result.exit_code == 0

    def test_untrack_help(self):
        result = runner.invoke(app, ["untrack", "--help"])
        assert result.exit_code == 0

    def test_exclude_help(self):
        result = runner.invoke(app, ["exclude", "--help"])
        assert result.exit_code == 0

    def test_include_help(self):
        result = runner.invoke(app, ["include", "--help"])
        assert result.exit_code == 0

    def test_repos_help(self):
        result = runner.invoke(app, ["repos", "--help"])
        assert result.exit_code == 0

    def test_forks_help(self):
        result = runner.invoke(app, ["forks", "--help"])
        assert result.exit_code == 0

    def test_inspect_help(self):
        result = runner.invoke(app, ["inspect", "--help"])
        assert result.exit_code == 0

    def test_clusters_help(self):
        result = runner.invoke(app, ["clusters", "--help"])
        assert result.exit_code == 0

    def test_sync_help(self):
        result = runner.invoke(app, ["sync", "--help"])
        assert result.exit_code == 0

    def test_digest_help(self):
        result = runner.invoke(app, ["digest", "--help"])
        assert result.exit_code == 0

    def test_config_help(self):
        result = runner.invoke(app, ["config", "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# init command
# ---------------------------------------------------------------------------


class TestInitCommand:
    async def test_init_creates_config_and_discovers_repos(
        self, db: Database, provider: StubGitProvider, tmp_path: Path
    ):
        """init should create config, discover repos, and show table output."""
        from forkhub.cli.init_cmd import _init_impl

        output_lines: list[str] = []
        await _init_impl(
            username="testuser",
            token="ghp_faketoken123",
            config_dir=tmp_path,
            db=db,
            provider=provider,
            capture_output=output_lines,
        )

        # Config file should exist
        config_file = tmp_path / "forkhub.toml"
        assert config_file.exists()
        content = config_file.read_text()
        assert "ghp_faketoken123" in content
        assert "testuser" in content

        # Should have discovered repos (2 owned + 1 upstream)
        repos = await db.list_tracked_repos()
        assert len(repos) == 3

        # Output should mention discovered repos
        output = "\n".join(output_lines)
        assert "testuser/alpha" in output or "alpha" in output

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

    async def test_init_token_from_env(
        self,
        db: Database,
        provider: StubGitProvider,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """init should use GITHUB_TOKEN from env when --token is not passed."""
        from forkhub.cli.init_cmd import _init_impl

        monkeypatch.setenv("GITHUB_TOKEN", "ghp_from_env")
        output_lines: list[str] = []
        await _init_impl(
            username="testuser",
            token=None,
            config_dir=tmp_path,
            db=db,
            provider=provider,
            capture_output=output_lines,
        )

        config_file = tmp_path / "forkhub.toml"
        content = config_file.read_text()
        assert "ghp_from_env" in content

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
    async def test_track_adds_repo(self, db: Database, provider: StubGitProvider):
        """track should add a repo and show confirmation."""
        from forkhub.cli.track_cmd import _track_impl

        output_lines: list[str] = []
        await _track_impl(
            repo="testuser/alpha",
            depth=1,
            db=db,
            provider=provider,
            capture_output=output_lines,
        )

        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is not None
        assert row["tracking_mode"] == "watched"

        output = "\n".join(output_lines)
        assert "testuser/alpha" in output

    async def test_track_with_depth(self, db: Database, provider: StubGitProvider):
        """track with --depth should set fork_depth."""
        from forkhub.cli.track_cmd import _track_impl

        await _track_impl(
            repo="testuser/alpha",
            depth=3,
            db=db,
            provider=provider,
        )

        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is not None
        assert row["fork_depth"] == 3

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

    async def test_exclude_sets_flag(self, db: Database, provider: StubGitProvider):
        """exclude should set the excluded flag."""
        from forkhub.cli.track_cmd import _exclude_impl, _track_impl

        await _track_impl(repo="testuser/alpha", db=db, provider=provider)
        output_lines: list[str] = []
        await _exclude_impl(
            repo="testuser/alpha",
            db=db,
            capture_output=output_lines,
        )

        row = await db.get_tracked_repo_by_name("testuser/alpha")
        assert row is not None
        assert row["excluded"] == 1

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
    async def test_repos_lists_tracked(self, db: Database, provider: StubGitProvider):
        """repos should list all tracked repos as a table."""
        from forkhub.cli.repos_cmd import _repos_impl
        from forkhub.cli.track_cmd import _track_impl

        await _track_impl(repo="testuser/alpha", db=db, provider=provider)
        await _track_impl(repo="testuser/beta", db=db, provider=provider)

        output_lines: list[str] = []
        await _repos_impl(db=db, mode=None, capture_output=output_lines)

        output = "\n".join(output_lines)
        assert "testuser/alpha" in output
        assert "testuser/beta" in output

    async def test_repos_filters_by_mode(self, db: Database, provider: StubGitProvider):
        """repos --owned should filter by tracking mode."""
        from forkhub.services.tracker import TrackerService

        tracker = TrackerService(db=db, provider=provider)
        await tracker.discover_owned_repos("testuser")
        await tracker.track_repo("upstream-org", "forked-lib", mode=TrackingMode.UPSTREAM)

        from forkhub.cli.repos_cmd import _repos_impl

        output_lines: list[str] = []
        await _repos_impl(db=db, mode="owned", capture_output=output_lines)

        output = "\n".join(output_lines)
        assert "testuser/alpha" in output
        assert "upstream-org/forked-lib" not in output

    async def test_repos_empty_shows_message(self, db: Database):
        """repos with no tracked repos should show a helpful message."""
        from forkhub.cli.repos_cmd import _repos_impl

        output_lines: list[str] = []
        await _repos_impl(db=db, mode=None, capture_output=output_lines)

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
    async def test_sync_all_runs(self, db: Database, provider: StubGitProvider):
        """sync should run sync_all and show summary."""
        from forkhub.cli.sync_cmd import _sync_impl
        from forkhub.cli.track_cmd import _track_impl
        from forkhub.config import SyncSettings

        await _track_impl(repo="testuser/alpha", db=db, provider=provider)

        output_lines: list[str] = []
        await _sync_impl(
            repo=None,
            db=db,
            provider=provider,
            sync_settings=SyncSettings(),
            capture_output=output_lines,
        )

        output = "\n".join(output_lines)
        assert "sync" in output.lower()

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

    async def test_digest_dry_run(self, db: Database, provider: StubGitProvider):
        """digest --dry-run should generate but not deliver."""
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
        assert "dry run" in output.lower() or "preview" in output.lower()


# ---------------------------------------------------------------------------
# config commands
# ---------------------------------------------------------------------------


class TestConfigCommands:
    async def test_config_show(self, tmp_path: Path):
        """config show should display current settings."""
        from forkhub.cli.config_cmd import _config_show_impl

        output_lines: list[str] = []
        await _config_show_impl(
            config_path=None,
            capture_output=output_lines,
        )

        output = "\n".join(output_lines)
        # Should show some config keys
        assert "github" in output.lower() or "database" in output.lower()

    async def test_config_path(self):
        """config path should show the config directory."""
        from forkhub.cli.config_cmd import _config_path_impl

        output_lines: list[str] = []
        await _config_path_impl(capture_output=output_lines)

        output = "\n".join(output_lines)
        assert "forkhub" in output.lower()
        assert ".config" in output or "config" in output.lower()

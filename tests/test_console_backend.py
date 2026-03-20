# ABOUTME: Tests for the console notification backend and Rich formatting helpers.
# ABOUTME: Verifies protocol conformance, output rendering, and visual formatting utilities.

from datetime import UTC, datetime
from io import StringIO

import pytest

from forkhub.models import (
    Cluster,
    Fork,
    ForkVitality,
    Signal,
    SignalCategory,
    TrackedRepo,
    TrackingMode,
)

# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def sample_repos() -> list[TrackedRepo]:
    """A list of tracked repos for table rendering."""
    return [
        TrackedRepo(
            github_id=1,
            owner="alice",
            name="myrepo",
            full_name="alice/myrepo",
            tracking_mode=TrackingMode.OWNED,
            default_branch="main",
            last_synced_at=datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC),
        ),
        TrackedRepo(
            github_id=2,
            owner="bob",
            name="toolkit",
            full_name="bob/toolkit",
            tracking_mode=TrackingMode.WATCHED,
            default_branch="develop",
            description="A utility toolkit",
        ),
    ]


@pytest.fixture
def sample_forks() -> list[Fork]:
    """A list of forks for table rendering."""
    return [
        Fork(
            tracked_repo_id="repo-1",
            github_id=100,
            owner="charlie",
            full_name="charlie/myrepo",
            default_branch="main",
            stars=42,
            commits_ahead=15,
            commits_behind=3,
            vitality=ForkVitality.ACTIVE,
        ),
        Fork(
            tracked_repo_id="repo-1",
            github_id=101,
            owner="diana",
            full_name="diana/myrepo",
            default_branch="main",
            stars=0,
            commits_ahead=0,
            commits_behind=0,
            vitality=ForkVitality.DORMANT,
        ),
        Fork(
            tracked_repo_id="repo-1",
            github_id=102,
            owner="eve",
            full_name="eve/myrepo",
            default_branch="main",
            stars=7,
            commits_ahead=100,
            commits_behind=50,
            vitality=ForkVitality.UNKNOWN,
        ),
    ]


@pytest.fixture
def sample_signal() -> Signal:
    """A signal for rendering tests."""
    return Signal(
        tracked_repo_id="repo-1",
        fork_id="fork-1",
        category=SignalCategory.FEATURE,
        summary="Added WebSocket support for real-time notifications",
        detail="Implements full WebSocket transport with reconnection logic.",
        files_involved=["src/ws.py", "src/handler.py"],
        significance=8,
    )


@pytest.fixture
def sample_cluster() -> Cluster:
    """A cluster for rendering tests."""
    return Cluster(
        tracked_repo_id="repo-1",
        label="Auth module changes",
        description="Multiple forks independently modified the authentication module.",
        files_pattern=["src/auth/*.py"],
        fork_count=4,
    )


# ── render_repo_table ───────────────────────────────────────


class TestRenderRepoTable:
    def test_renders_table_with_repos(self, sample_repos: list[TrackedRepo]):
        """render_repo_table should produce a table with columns, repo names, and tracking modes."""
        from rich.console import Console

        from forkhub.cli.formatting import render_repo_table

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        render_repo_table(console, sample_repos)

        rendered = output.getvalue()
        # Columns
        assert "Repository" in rendered
        assert "Mode" in rendered
        assert "Last Synced" in rendered
        # Repo names
        assert "alice/myrepo" in rendered
        assert "bob/toolkit" in rendered
        # Tracking modes
        assert "owned" in rendered
        assert "watched" in rendered


# ── render_fork_table ───────────────────────────────────────


class TestRenderForkTable:
    def test_renders_table_with_forks(self, sample_forks: list[Fork]):
        """render_fork_table should produce a table with all fork data."""
        from rich.console import Console

        from forkhub.cli.formatting import render_fork_table

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        render_fork_table(console, sample_forks)

        rendered = output.getvalue()
        # Columns
        assert "Fork" in rendered
        assert "Stars" in rendered
        assert "Ahead" in rendered
        assert "Behind" in rendered
        assert "Vitality" in rendered
        # Fork names
        assert "charlie/myrepo" in rendered
        assert "diana/myrepo" in rendered
        assert "eve/myrepo" in rendered
        # Stats
        assert "42" in rendered
        assert "15" in rendered
        # Vitality labels
        assert "active" in rendered
        assert "dormant" in rendered


# ── render_signal ───────────────────────────────────────────


class TestRenderSignal:
    def test_renders_signal_content(self, sample_signal: Signal):
        """render_signal should display category, significance bar, summary, and files."""
        from rich.console import Console

        from forkhub.cli.formatting import render_signal

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)
        render_signal(console, sample_signal)

        rendered = output.getvalue()
        assert "feature" in rendered.lower()
        assert "Added WebSocket support" in rendered
        assert "\u2588" in rendered
        assert "src/ws.py" in rendered
        assert "src/handler.py" in rendered


# ── render_cluster ──────────────────────────────────────────


class TestRenderCluster:
    def test_renders_cluster_content(self, sample_cluster: Cluster):
        """render_cluster should display label, description, fork count, and file patterns."""
        from rich.console import Console

        from forkhub.cli.formatting import render_cluster

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)
        render_cluster(console, sample_cluster)

        rendered = output.getvalue()
        assert "Auth module changes" in rendered
        assert "Multiple forks independently modified" in rendered
        assert "4" in rendered
        assert "src/auth/*.py" in rendered

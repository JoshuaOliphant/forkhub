# ABOUTME: Tests for the console notification backend and Rich formatting helpers.
# ABOUTME: Verifies protocol conformance, output rendering, and visual formatting utilities.

from datetime import UTC, datetime
from io import StringIO
from unittest.mock import patch

import pytest

from forkhub.interfaces import NotificationBackend
from forkhub.models import (
    Cluster,
    Digest,
    Fork,
    ForkVitality,
    Signal,
    SignalCategory,
    TrackedRepo,
    TrackingMode,
)

# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def sample_digest() -> Digest:
    """A minimal digest for testing."""
    return Digest(
        title="Weekly Digest for alice/myrepo",
        body="3 forks showed interesting activity this week.",
        signal_ids=["sig-1", "sig-2", "sig-3"],
    )


@pytest.fixture
def sample_digest_no_signals() -> Digest:
    """A digest with no signals."""
    return Digest(
        title="Empty Digest",
        body="No notable activity this period.",
        signal_ids=[],
    )


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


# ── ConsoleBackend Protocol Conformance ─────────────────────


class TestConsoleBackendProtocol:
    def test_implements_notification_backend(self):
        """ConsoleBackend should satisfy the NotificationBackend protocol."""
        from forkhub.notifications.console import ConsoleBackend

        backend = ConsoleBackend()
        assert isinstance(backend, NotificationBackend)

    def test_backend_name_returns_console(self):
        """backend_name() should return 'console'."""
        from forkhub.notifications.console import ConsoleBackend

        backend = ConsoleBackend()
        assert backend.backend_name() == "console"

    def test_accepts_custom_console(self):
        """ConsoleBackend should accept a custom Console instance."""
        from rich.console import Console

        from forkhub.notifications.console import ConsoleBackend

        custom_console = Console(file=StringIO(), force_terminal=True, width=80)
        backend = ConsoleBackend(console=custom_console)
        assert backend._console is custom_console


# ── ConsoleBackend Delivery ─────────────────────────────────


class TestConsoleBackendDeliver:
    async def test_deliver_returns_success(self, sample_digest: Digest):
        """deliver() should return a successful DeliveryResult."""
        from forkhub.notifications.console import ConsoleBackend

        output = StringIO()
        console_obj = __import__("rich.console", fromlist=["Console"]).Console(
            file=output, force_terminal=True, width=80
        )
        backend = ConsoleBackend(console=console_obj)
        result = await backend.deliver(sample_digest)

        assert result.success is True
        assert result.backend_name == "console"
        assert result.error is None
        assert isinstance(result.delivered_at, datetime)

    async def test_deliver_renders_digest_title(self, sample_digest: Digest):
        """deliver() should output the digest title."""
        from rich.console import Console

        from forkhub.notifications.console import ConsoleBackend

        output = StringIO()
        console_obj = Console(file=output, force_terminal=True, width=80)
        backend = ConsoleBackend(console=console_obj)
        await backend.deliver(sample_digest)

        rendered = output.getvalue()
        assert "Weekly Digest for alice/myrepo" in rendered

    async def test_deliver_renders_digest_body(self, sample_digest: Digest):
        """deliver() should output the digest body."""
        from rich.console import Console

        from forkhub.notifications.console import ConsoleBackend

        output = StringIO()
        console_obj = Console(file=output, force_terminal=True, width=80)
        backend = ConsoleBackend(console=console_obj)
        await backend.deliver(sample_digest)

        rendered = output.getvalue()
        assert "3 forks showed interesting activity this week." in rendered

    async def test_deliver_shows_signal_count(self, sample_digest: Digest):
        """deliver() should show the number of signals in the digest."""
        from rich.console import Console

        from forkhub.notifications.console import ConsoleBackend

        output = StringIO()
        console_obj = Console(file=output, force_terminal=True, width=80)
        backend = ConsoleBackend(console=console_obj)
        await backend.deliver(sample_digest)

        rendered = output.getvalue()
        assert "3" in rendered

    async def test_deliver_empty_digest(self, sample_digest_no_signals: Digest):
        """deliver() should handle digests with no signals gracefully."""
        from rich.console import Console

        from forkhub.notifications.console import ConsoleBackend

        output = StringIO()
        console_obj = Console(file=output, force_terminal=True, width=80)
        backend = ConsoleBackend(console=console_obj)
        result = await backend.deliver(sample_digest_no_signals)

        assert result.success is True
        rendered = output.getvalue()
        assert "Empty Digest" in rendered

    async def test_deliver_calls_render_digest(self, sample_digest: Digest):
        """deliver() should delegate to render_digest."""
        from rich.console import Console

        from forkhub.notifications.console import ConsoleBackend

        output = StringIO()
        console_obj = Console(file=output, force_terminal=True, width=80)
        backend = ConsoleBackend(console=console_obj)

        with patch("forkhub.notifications.console.render_digest") as mock_render:
            await backend.deliver(sample_digest)
            mock_render.assert_called_once_with(console_obj, sample_digest)


# ── format_significance ─────────────────────────────────────


class TestFormatSignificance:
    def test_minimum_score(self):
        """Score of 1 should produce 1 filled block and 9 empty."""
        from forkhub.cli.formatting import format_significance

        result = format_significance(1)
        assert result == "\u2588" + "\u2591" * 9

    def test_maximum_score(self):
        """Score of 10 should produce 10 filled blocks."""
        from forkhub.cli.formatting import format_significance

        result = format_significance(10)
        assert result == "\u2588" * 10

    def test_middle_score(self):
        """Score of 5 should produce 5 filled and 5 empty."""
        from forkhub.cli.formatting import format_significance

        result = format_significance(5)
        assert result == "\u2588" * 5 + "\u2591" * 5

    def test_score_length_always_ten(self):
        """The bar should always be exactly 10 characters."""
        from forkhub.cli.formatting import format_significance

        for score in range(1, 11):
            assert len(format_significance(score)) == 10

    def test_all_scores(self):
        """Every valid score should produce the correct number of filled blocks."""
        from forkhub.cli.formatting import format_significance

        for score in range(1, 11):
            result = format_significance(score)
            filled = result.count("\u2588")
            empty = result.count("\u2591")
            assert filled == score
            assert empty == 10 - score


# ── render_digest ───────────────────────────────────────────


class TestRenderDigest:
    def test_renders_title(self, sample_digest: Digest):
        """render_digest should include the digest title."""
        from rich.console import Console

        from forkhub.cli.formatting import render_digest

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)
        render_digest(console, sample_digest)

        rendered = output.getvalue()
        assert "Weekly Digest for alice/myrepo" in rendered

    def test_renders_body(self, sample_digest: Digest):
        """render_digest should include the digest body."""
        from rich.console import Console

        from forkhub.cli.formatting import render_digest

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)
        render_digest(console, sample_digest)

        rendered = output.getvalue()
        assert "3 forks showed interesting activity this week." in rendered

    def test_renders_signal_count(self, sample_digest: Digest):
        """render_digest should display the signal count."""
        from rich.console import Console

        from forkhub.cli.formatting import render_digest

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)
        render_digest(console, sample_digest)

        rendered = output.getvalue()
        # Should contain "3 signals" or similar
        assert "3" in rendered
        assert "signal" in rendered.lower()

    def test_renders_empty_digest(self, sample_digest_no_signals: Digest):
        """render_digest should handle empty digests."""
        from rich.console import Console

        from forkhub.cli.formatting import render_digest

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)
        render_digest(console, sample_digest_no_signals)

        rendered = output.getvalue()
        assert "Empty Digest" in rendered
        assert "0" in rendered


# ── render_repo_table ───────────────────────────────────────


class TestRenderRepoTable:
    def test_renders_table_with_columns(self, sample_repos: list[TrackedRepo]):
        """render_repo_table should produce a table with the expected columns."""
        from rich.console import Console

        from forkhub.cli.formatting import render_repo_table

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        render_repo_table(console, sample_repos)

        rendered = output.getvalue()
        assert "Repository" in rendered
        assert "Mode" in rendered
        assert "Last Synced" in rendered

    def test_renders_repo_names(self, sample_repos: list[TrackedRepo]):
        """render_repo_table should display each repo's full name."""
        from rich.console import Console

        from forkhub.cli.formatting import render_repo_table

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        render_repo_table(console, sample_repos)

        rendered = output.getvalue()
        assert "alice/myrepo" in rendered
        assert "bob/toolkit" in rendered

    def test_renders_tracking_mode(self, sample_repos: list[TrackedRepo]):
        """render_repo_table should display the tracking mode."""
        from rich.console import Console

        from forkhub.cli.formatting import render_repo_table

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        render_repo_table(console, sample_repos)

        rendered = output.getvalue()
        assert "owned" in rendered
        assert "watched" in rendered

    def test_renders_empty_list(self):
        """render_repo_table should handle an empty repo list."""
        from rich.console import Console

        from forkhub.cli.formatting import render_repo_table

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        render_repo_table(console, [])

        rendered = output.getvalue()
        assert "Tracked Repositories" in rendered


# ── render_fork_table ───────────────────────────────────────


class TestRenderForkTable:
    def test_renders_table_with_columns(self, sample_forks: list[Fork]):
        """render_fork_table should produce a table with the expected columns."""
        from rich.console import Console

        from forkhub.cli.formatting import render_fork_table

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        render_fork_table(console, sample_forks)

        rendered = output.getvalue()
        assert "Fork" in rendered
        assert "Stars" in rendered
        assert "Ahead" in rendered
        assert "Behind" in rendered
        assert "Vitality" in rendered

    def test_renders_fork_names(self, sample_forks: list[Fork]):
        """render_fork_table should display each fork's full name."""
        from rich.console import Console

        from forkhub.cli.formatting import render_fork_table

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        render_fork_table(console, sample_forks)

        rendered = output.getvalue()
        assert "charlie/myrepo" in rendered
        assert "diana/myrepo" in rendered
        assert "eve/myrepo" in rendered

    def test_renders_fork_stats(self, sample_forks: list[Fork]):
        """render_fork_table should display stars, ahead, and behind counts."""
        from rich.console import Console

        from forkhub.cli.formatting import render_fork_table

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        render_fork_table(console, sample_forks)

        rendered = output.getvalue()
        assert "42" in rendered
        assert "15" in rendered

    def test_renders_vitality(self, sample_forks: list[Fork]):
        """render_fork_table should display vitality status."""
        from rich.console import Console

        from forkhub.cli.formatting import render_fork_table

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        render_fork_table(console, sample_forks)

        rendered = output.getvalue()
        assert "active" in rendered
        assert "dormant" in rendered

    def test_renders_empty_list(self):
        """render_fork_table should handle an empty fork list."""
        from rich.console import Console

        from forkhub.cli.formatting import render_fork_table

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=120)
        render_fork_table(console, [])

        rendered = output.getvalue()
        assert "Forks" in rendered


# ── render_signal ───────────────────────────────────────────


class TestRenderSignal:
    def test_renders_category(self, sample_signal: Signal):
        """render_signal should display the signal category."""
        from rich.console import Console

        from forkhub.cli.formatting import render_signal

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)
        render_signal(console, sample_signal)

        rendered = output.getvalue()
        assert "feature" in rendered.lower()

    def test_renders_summary(self, sample_signal: Signal):
        """render_signal should display the signal summary."""
        from rich.console import Console

        from forkhub.cli.formatting import render_signal

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)
        render_signal(console, sample_signal)

        rendered = output.getvalue()
        assert "Added WebSocket support" in rendered

    def test_renders_significance_bar(self, sample_signal: Signal):
        """render_signal should display the significance bar."""
        from rich.console import Console

        from forkhub.cli.formatting import render_signal

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)
        render_signal(console, sample_signal)

        rendered = output.getvalue()
        # Should contain the filled block character (significance 8)
        assert "\u2588" in rendered

    def test_renders_files_involved(self, sample_signal: Signal):
        """render_signal should display the files involved."""
        from rich.console import Console

        from forkhub.cli.formatting import render_signal

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)
        render_signal(console, sample_signal)

        rendered = output.getvalue()
        assert "src/ws.py" in rendered
        assert "src/handler.py" in rendered


# ── render_cluster ──────────────────────────────────────────


class TestRenderCluster:
    def test_renders_label(self, sample_cluster: Cluster):
        """render_cluster should display the cluster label."""
        from rich.console import Console

        from forkhub.cli.formatting import render_cluster

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)
        render_cluster(console, sample_cluster)

        rendered = output.getvalue()
        assert "Auth module changes" in rendered

    def test_renders_description(self, sample_cluster: Cluster):
        """render_cluster should display the cluster description."""
        from rich.console import Console

        from forkhub.cli.formatting import render_cluster

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)
        render_cluster(console, sample_cluster)

        rendered = output.getvalue()
        assert "Multiple forks independently modified" in rendered

    def test_renders_fork_count(self, sample_cluster: Cluster):
        """render_cluster should display the fork count."""
        from rich.console import Console

        from forkhub.cli.formatting import render_cluster

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)
        render_cluster(console, sample_cluster)

        rendered = output.getvalue()
        assert "4" in rendered

    def test_renders_file_patterns(self, sample_cluster: Cluster):
        """render_cluster should display the file patterns."""
        from rich.console import Console

        from forkhub.cli.formatting import render_cluster

        output = StringIO()
        console = Console(file=output, force_terminal=True, width=80)
        render_cluster(console, sample_cluster)

        rendered = output.getvalue()
        assert "src/auth/*.py" in rendered

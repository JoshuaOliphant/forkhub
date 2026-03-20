# ABOUTME: Tests for ForkHub Pydantic data models.
# ABOUTME: Validates all enums, domain models, API response models, defaults, and constraints.

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from forkhub.models import (
    ClusterMember,
    CommitInfo,
    CompareResult,
    DeliveryResult,
    FileChange,
    Fork,
    ForkInfo,
    ForkPage,
    ForkVitality,
    RateLimitInfo,
    Release,
    RepoInfo,
    SignalCategory,
    SyncStatus,
    TrackedRepo,
    TrackingMode,
    WebhookAction,
)

# ── StrEnum Tests ────────────────────────────────────────────


@pytest.mark.parametrize(
    "enum_cls,expected_values",
    [
        (TrackingMode, {"owned", "watched", "upstream"}),
        (
            SignalCategory,
            {
                "feature",
                "fix",
                "refactor",
                "config",
                "dependency",
                "removal",
                "adaptation",
                "release",
            },
        ),
        (ForkVitality, {"active", "dormant", "dead", "unknown"}),
        (SyncStatus, {"ok", "inaccessible", "error"}),
    ],
)
def test_strenum_values_and_type(enum_cls, expected_values):
    """All StrEnums have expected values and are string-typed."""
    assert {str(m) for m in enum_cls} == expected_values
    assert all(isinstance(m, str) for m in enum_cls)


# ── TrackedRepo Tests ────────────────────────────────────────


class TestTrackedRepo:
    def test_full_construction(self):
        now = datetime.now(tz=UTC)
        repo = TrackedRepo(
            id="custom-id",
            github_id=99999,
            owner="bob",
            name="project",
            full_name="bob/project",
            tracking_mode=TrackingMode.WATCHED,
            default_branch="develop",
            description="A great project",
            fork_depth=2,
            excluded=True,
            webhook_id=42,
            last_synced_at=now,
            created_at=now,
        )
        assert repo.id == "custom-id"
        assert repo.description == "A great project"
        assert repo.fork_depth == 2
        assert repo.excluded is True
        assert repo.webhook_id == 42
        assert repo.last_synced_at == now


# ── Fork Tests ───────────────────────────────────────────────


class TestFork:
    def test_full_construction(self):
        now = datetime.now(tz=UTC)
        fork = Fork(
            id="fork-id",
            tracked_repo_id="repo-id",
            github_id=999,
            owner="dave",
            full_name="dave/fork",
            default_branch="develop",
            description="My fork",
            vitality=ForkVitality.ACTIVE,
            stars=50,
            stars_previous=45,
            parent_fork_id="parent-fork-id",
            depth=2,
            last_pushed_at=now,
            commits_ahead=10,
            commits_behind=3,
            head_sha="abc123",
            created_at=now,
            updated_at=now,
        )
        assert fork.vitality == ForkVitality.ACTIVE
        assert fork.stars == 50
        assert fork.stars_previous == 45
        assert fork.depth == 2
        assert fork.commits_ahead == 10
        assert fork.head_sha == "abc123"


# ── ClusterMember Tests ─────────────────────────────────────


class TestClusterMember:
    def test_construction(self):
        member = ClusterMember(
            cluster_id="cluster-id",
            signal_id="signal-id",
            fork_id="fork-id",
        )
        assert member.cluster_id == "cluster-id"
        assert member.signal_id == "signal-id"
        assert member.fork_id == "fork-id"

    def test_missing_required_field_rejected(self):
        with pytest.raises(ValidationError):
            ClusterMember(cluster_id="c", signal_id="s")  # ty: ignore[missing-argument]


# ── RepoInfo Tests ───────────────────────────────────────────


class TestRepoInfo:
    def test_construction(self):
        repo = RepoInfo(
            github_id=12345,
            owner="alice",
            name="project",
            full_name="alice/project",
            default_branch="main",
            description="A project",
            is_fork=False,
            stars=100,
            forks_count=25,
        )
        assert repo.github_id == 12345
        assert repo.is_fork is False
        assert repo.parent_full_name is None
        assert repo.stars == 100
        assert repo.forks_count == 25
        assert repo.last_pushed_at is None

    def test_fork_repo(self):
        repo = RepoInfo(
            github_id=12345,
            owner="bob",
            name="project",
            full_name="bob/project",
            default_branch="main",
            description="Forked project",
            is_fork=True,
            parent_full_name="alice/project",
            stars=5,
            forks_count=0,
        )
        assert repo.is_fork is True
        assert repo.parent_full_name == "alice/project"


# ── ForkInfo Tests ───────────────────────────────────────────


class TestForkInfo:
    def test_construction(self):
        now = datetime.now(tz=UTC)
        info = ForkInfo(
            github_id=999,
            owner="charlie",
            full_name="charlie/project",
            default_branch="main",
            description="Fork desc",
            stars=10,
            last_pushed_at=now,
            has_diverged=True,
            created_at=now,
        )
        assert info.github_id == 999
        assert info.has_diverged is True
        assert info.stars == 10


# ── ForkPage Tests ───────────────────────────────────────────


class TestForkPage:
    def test_construction(self):
        now = datetime.now(tz=UTC)
        fork = ForkInfo(
            github_id=1,
            owner="a",
            full_name="a/b",
            default_branch="main",
            description=None,
            stars=0,
            last_pushed_at=None,
            has_diverged=False,
            created_at=now,
        )
        page = ForkPage(
            forks=[fork],
            total_count=50,
            page=1,
            has_next=True,
        )
        assert len(page.forks) == 1
        assert page.total_count == 50
        assert page.has_next is True

    def test_empty_page(self):
        page = ForkPage(
            forks=[],
            total_count=0,
            page=1,
            has_next=False,
        )
        assert len(page.forks) == 0
        assert page.has_next is False


# ── CompareResult Tests ──────────────────────────────────────


class TestCompareResult:
    def test_construction(self):
        now = datetime.now(tz=UTC)
        file_change = FileChange(
            filename="src/main.py",
            status="modified",
            additions=10,
            deletions=3,
        )
        commit = CommitInfo(
            sha="abc123",
            message="Fix bug",
            author="alice",
            authored_at=now,
        )
        result = CompareResult(
            ahead_by=5,
            behind_by=2,
            files=[file_change],
            commits=[commit],
        )
        assert result.ahead_by == 5
        assert result.behind_by == 2
        assert len(result.files) == 1
        assert len(result.commits) == 1


# ── FileChange Tests ─────────────────────────────────────────


class TestFileChange:
    def test_construction(self):
        change = FileChange(
            filename="README.md",
            status="added",
            additions=20,
            deletions=0,
        )
        assert change.filename == "README.md"
        assert change.status == "added"
        assert change.patch is None

    def test_with_patch(self):
        change = FileChange(
            filename="src/app.py",
            status="modified",
            additions=5,
            deletions=2,
            patch="@@ -1,5 +1,8 @@\n+import os",
        )
        assert change.patch is not None


# ── CommitInfo Tests ─────────────────────────────────────────


class TestCommitInfo:
    def test_construction(self):
        now = datetime.now(tz=UTC)
        commit = CommitInfo(
            sha="deadbeef",
            message="Add feature X",
            author="bob",
            authored_at=now,
        )
        assert commit.sha == "deadbeef"
        assert commit.message == "Add feature X"
        assert commit.author == "bob"
        assert commit.authored_at == now


# ── Release Tests ────────────────────────────────────────────


class TestRelease:
    def test_construction(self):
        now = datetime.now(tz=UTC)
        release = Release(
            tag="v1.0.0",
            name="Version 1.0.0",
            body="First stable release",
            published_at=now,
            is_prerelease=False,
        )
        assert release.tag == "v1.0.0"
        assert release.is_prerelease is False

    def test_prerelease(self):
        now = datetime.now(tz=UTC)
        release = Release(
            tag="v2.0.0-rc1",
            name="2.0.0 RC1",
            body="Release candidate",
            published_at=now,
            is_prerelease=True,
        )
        assert release.is_prerelease is True


# ── RateLimitInfo Tests ──────────────────────────────────────


class TestRateLimitInfo:
    def test_construction(self):
        now = datetime.now(tz=UTC)
        info = RateLimitInfo(
            limit=5000,
            remaining=4999,
            reset_at=now,
        )
        assert info.limit == 5000
        assert info.remaining == 4999
        assert info.reset_at == now


# ── DeliveryResult Tests ─────────────────────────────────────


class TestDeliveryResult:
    def test_success(self):
        now = datetime.now(tz=UTC)
        result = DeliveryResult(
            backend_name="console",
            success=True,
            delivered_at=now,
        )
        assert result.success is True
        assert result.error is None
        assert result.delivered_at == now

    def test_failure(self):
        now = datetime.now(tz=UTC)
        result = DeliveryResult(
            backend_name="telegram",
            success=False,
            error="Connection timeout",
            delivered_at=now,
        )
        assert result.success is False
        assert result.error == "Connection timeout"


# ── WebhookAction Tests ─────────────────────────────────────


class TestWebhookAction:
    def test_construction(self):
        action = WebhookAction(
            action_type="sync_fork",
            payload={"fork_id": "123", "event": "push"},
        )
        assert action.action_type == "sync_fork"
        assert action.payload == {"fork_id": "123", "event": "push"}

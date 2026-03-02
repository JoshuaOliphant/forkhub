# ABOUTME: Tests for ForkHub Pydantic data models.
# ABOUTME: Validates all enums, domain models, API response models, defaults, and constraints.

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from forkhub.models import (
    Annotation,
    Cluster,
    ClusterMember,
    CommitInfo,
    CompareResult,
    DeliveryResult,
    Digest,
    DigestConfig,
    FileChange,
    Fork,
    ForkInfo,
    ForkPage,
    ForkVitality,
    RateLimitInfo,
    Release,
    RepoInfo,
    Signal,
    SignalCategory,
    TrackedRepo,
    TrackingMode,
    WebhookAction,
)

# ── StrEnum Tests ────────────────────────────────────────────


class TestTrackingMode:
    def test_values(self):
        assert TrackingMode.OWNED == "owned"
        assert TrackingMode.WATCHED == "watched"
        assert TrackingMode.UPSTREAM == "upstream"

    def test_all_members(self):
        assert set(TrackingMode) == {
            TrackingMode.OWNED,
            TrackingMode.WATCHED,
            TrackingMode.UPSTREAM,
        }

    def test_is_str(self):
        assert isinstance(TrackingMode.OWNED, str)


class TestSignalCategory:
    def test_values(self):
        assert SignalCategory.FEATURE == "feature"
        assert SignalCategory.FIX == "fix"
        assert SignalCategory.REFACTOR == "refactor"
        assert SignalCategory.CONFIG == "config"
        assert SignalCategory.DEPENDENCY == "dependency"
        assert SignalCategory.REMOVAL == "removal"
        assert SignalCategory.ADAPTATION == "adaptation"
        assert SignalCategory.RELEASE == "release"

    def test_all_members(self):
        assert len(SignalCategory) == 8

    def test_is_str(self):
        assert isinstance(SignalCategory.FEATURE, str)


class TestForkVitality:
    def test_values(self):
        assert ForkVitality.ACTIVE == "active"
        assert ForkVitality.DORMANT == "dormant"
        assert ForkVitality.DEAD == "dead"
        assert ForkVitality.UNKNOWN == "unknown"

    def test_all_members(self):
        assert set(ForkVitality) == {
            ForkVitality.ACTIVE,
            ForkVitality.DORMANT,
            ForkVitality.DEAD,
            ForkVitality.UNKNOWN,
        }

    def test_is_str(self):
        assert isinstance(ForkVitality.ACTIVE, str)


# ── TrackedRepo Tests ────────────────────────────────────────


class TestTrackedRepo:
    def test_minimal_construction(self):
        repo = TrackedRepo(
            github_id=12345,
            owner="alice",
            name="myrepo",
            full_name="alice/myrepo",
            tracking_mode=TrackingMode.OWNED,
            default_branch="main",
        )
        # id should be a valid uuid4 string
        UUID(repo.id)
        assert repo.github_id == 12345
        assert repo.owner == "alice"
        assert repo.name == "myrepo"
        assert repo.full_name == "alice/myrepo"
        assert repo.tracking_mode == TrackingMode.OWNED
        assert repo.default_branch == "main"
        assert repo.description is None
        assert repo.fork_depth == 1
        assert repo.excluded is False
        assert repo.webhook_id is None
        assert repo.last_synced_at is None
        assert isinstance(repo.created_at, datetime)

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

    def test_tracking_mode_accepts_string(self):
        repo = TrackedRepo(
            github_id=1,
            owner="x",
            name="y",
            full_name="x/y",
            tracking_mode="upstream",
            default_branch="main",
        )
        assert repo.tracking_mode == TrackingMode.UPSTREAM

    def test_auto_generated_id_is_unique(self):
        repo1 = TrackedRepo(
            github_id=1,
            owner="a",
            name="b",
            full_name="a/b",
            tracking_mode=TrackingMode.OWNED,
            default_branch="main",
        )
        repo2 = TrackedRepo(
            github_id=2,
            owner="c",
            name="d",
            full_name="c/d",
            tracking_mode=TrackingMode.OWNED,
            default_branch="main",
        )
        assert repo1.id != repo2.id


# ── Fork Tests ───────────────────────────────────────────────


class TestFork:
    def test_minimal_construction(self):
        fork = Fork(
            tracked_repo_id="repo-uuid",
            github_id=54321,
            owner="charlie",
            full_name="charlie/myrepo",
            default_branch="main",
        )
        UUID(fork.id)
        assert fork.tracked_repo_id == "repo-uuid"
        assert fork.github_id == 54321
        assert fork.owner == "charlie"
        assert fork.full_name == "charlie/myrepo"
        assert fork.description is None
        assert fork.vitality == ForkVitality.UNKNOWN
        assert fork.stars == 0
        assert fork.stars_previous == 0
        assert fork.parent_fork_id is None
        assert fork.depth == 1
        assert fork.last_pushed_at is None
        assert fork.commits_ahead == 0
        assert fork.commits_behind == 0
        assert fork.head_sha is None
        assert isinstance(fork.created_at, datetime)
        assert isinstance(fork.updated_at, datetime)

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

    def test_vitality_accepts_string(self):
        fork = Fork(
            tracked_repo_id="r",
            github_id=1,
            owner="x",
            full_name="x/y",
            default_branch="main",
            vitality="active",
        )
        assert fork.vitality == ForkVitality.ACTIVE


# ── Signal Tests ─────────────────────────────────────────────


class TestSignal:
    def test_minimal_construction(self):
        signal = Signal(
            tracked_repo_id="repo-id",
            category=SignalCategory.FEATURE,
            summary="Added WebSocket support",
        )
        UUID(signal.id)
        assert signal.fork_id is None
        assert signal.tracked_repo_id == "repo-id"
        assert signal.category == SignalCategory.FEATURE
        assert signal.summary == "Added WebSocket support"
        assert signal.detail is None
        assert signal.files_involved == []
        assert signal.significance == 5
        assert signal.embedding is None
        assert signal.is_upstream is False
        assert signal.release_tag is None
        assert isinstance(signal.created_at, datetime)

    def test_significance_range_valid(self):
        signal = Signal(
            tracked_repo_id="r",
            category=SignalCategory.FIX,
            summary="Fix",
            significance=1,
        )
        assert signal.significance == 1

        signal = Signal(
            tracked_repo_id="r",
            category=SignalCategory.FIX,
            summary="Fix",
            significance=10,
        )
        assert signal.significance == 10

    def test_significance_below_minimum_rejected(self):
        with pytest.raises(ValidationError):
            Signal(
                tracked_repo_id="r",
                category=SignalCategory.FIX,
                summary="Fix",
                significance=0,
            )

    def test_significance_above_maximum_rejected(self):
        with pytest.raises(ValidationError):
            Signal(
                tracked_repo_id="r",
                category=SignalCategory.FIX,
                summary="Fix",
                significance=11,
            )

    def test_with_files_involved(self):
        signal = Signal(
            tracked_repo_id="r",
            category=SignalCategory.REFACTOR,
            summary="Restructure modules",
            files_involved=["src/main.py", "src/utils.py"],
        )
        assert signal.files_involved == ["src/main.py", "src/utils.py"]

    def test_category_accepts_string(self):
        signal = Signal(
            tracked_repo_id="r",
            category="dependency",
            summary="Bump version",
        )
        assert signal.category == SignalCategory.DEPENDENCY

    def test_upstream_signal(self):
        signal = Signal(
            tracked_repo_id="r",
            category=SignalCategory.RELEASE,
            summary="v2.0.0 released",
            is_upstream=True,
            release_tag="v2.0.0",
        )
        assert signal.is_upstream is True
        assert signal.release_tag == "v2.0.0"

    def test_with_embedding(self):
        data = b"\x00\x01\x02\x03"
        signal = Signal(
            tracked_repo_id="r",
            category=SignalCategory.FEATURE,
            summary="Test",
            embedding=data,
        )
        assert signal.embedding == data


# ── Cluster Tests ────────────────────────────────────────────


class TestCluster:
    def test_minimal_construction(self):
        cluster = Cluster(
            tracked_repo_id="repo-id",
            label="Auth module changes",
            description="Multiple forks modified auth code",
        )
        UUID(cluster.id)
        assert cluster.tracked_repo_id == "repo-id"
        assert cluster.label == "Auth module changes"
        assert cluster.files_pattern == []
        assert cluster.fork_count == 0
        assert isinstance(cluster.created_at, datetime)
        assert isinstance(cluster.updated_at, datetime)

    def test_with_files_pattern(self):
        cluster = Cluster(
            tracked_repo_id="r",
            label="DB changes",
            description="Pool mods",
            files_pattern=["src/db/*.py", "src/pool.py"],
            fork_count=3,
        )
        assert cluster.files_pattern == ["src/db/*.py", "src/pool.py"]
        assert cluster.fork_count == 3


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
            ClusterMember(cluster_id="c", signal_id="s")


# ── DigestConfig Tests ───────────────────────────────────────


class TestDigestConfig:
    def test_minimal_construction(self):
        config = DigestConfig()
        UUID(config.id)
        assert config.tracked_repo_id is None
        assert config.frequency == "weekly"
        assert config.day_of_week is None
        assert config.time_of_day == "09:00"
        assert config.min_significance == 5
        assert config.categories is None
        assert config.file_patterns is None
        assert config.backends == ["console"]
        assert isinstance(config.created_at, datetime)

    def test_full_construction(self):
        config = DigestConfig(
            tracked_repo_id="repo-id",
            frequency="daily",
            day_of_week=0,
            time_of_day="14:30",
            min_significance=7,
            categories=["feature", "fix"],
            file_patterns=["src/auth/*"],
            backends=["console", "telegram"],
        )
        assert config.tracked_repo_id == "repo-id"
        assert config.frequency == "daily"
        assert config.day_of_week == 0
        assert config.time_of_day == "14:30"
        assert config.min_significance == 7
        assert config.categories == ["feature", "fix"]
        assert config.file_patterns == ["src/auth/*"]
        assert config.backends == ["console", "telegram"]


# ── Digest Tests ─────────────────────────────────────────────


class TestDigest:
    def test_minimal_construction(self):
        digest = Digest(
            title="Weekly Digest",
            body="Here are the changes...",
        )
        UUID(digest.id)
        assert digest.config_id is None
        assert digest.title == "Weekly Digest"
        assert digest.body == "Here are the changes..."
        assert digest.signal_ids == []
        assert digest.delivered_at is None
        assert isinstance(digest.created_at, datetime)

    def test_with_signal_ids(self):
        digest = Digest(
            title="Daily",
            body="Updates",
            signal_ids=["sig-1", "sig-2", "sig-3"],
            config_id="config-id",
        )
        assert digest.signal_ids == ["sig-1", "sig-2", "sig-3"]
        assert digest.config_id == "config-id"


# ── Annotation Tests ─────────────────────────────────────────


class TestAnnotation:
    def test_construction(self):
        annotation = Annotation(
            fork_id="fork-id",
            title="Note about this fork",
            body="This fork focuses on performance improvements.",
        )
        UUID(annotation.id)
        assert annotation.fork_id == "fork-id"
        assert annotation.title == "Note about this fork"
        assert isinstance(annotation.created_at, datetime)
        assert isinstance(annotation.updated_at, datetime)


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

    def test_empty_payload(self):
        action = WebhookAction(
            action_type="noop",
            payload={},
        )
        assert action.payload == {}


# ── Serialization / Round-Trip Tests ────────────────────────


class TestSerialization:
    def test_tracked_repo_round_trip(self):
        repo = TrackedRepo(
            github_id=1,
            owner="a",
            name="b",
            full_name="a/b",
            tracking_mode=TrackingMode.OWNED,
            default_branch="main",
        )
        data = repo.model_dump()
        restored = TrackedRepo(**data)
        assert restored.id == repo.id
        assert restored.tracking_mode == repo.tracking_mode

    def test_signal_round_trip(self):
        signal = Signal(
            tracked_repo_id="r",
            category=SignalCategory.FEATURE,
            summary="Added websockets",
            files_involved=["ws.py", "handler.py"],
            significance=8,
        )
        data = signal.model_dump()
        restored = Signal(**data)
        assert restored.files_involved == ["ws.py", "handler.py"]
        assert restored.significance == 8

    def test_model_dump_json(self):
        """Models should be JSON serializable."""
        repo = TrackedRepo(
            github_id=1,
            owner="a",
            name="b",
            full_name="a/b",
            tracking_mode=TrackingMode.OWNED,
            default_branch="main",
        )
        json_str = repo.model_dump_json()
        assert isinstance(json_str, str)
        assert '"tracking_mode":"owned"' in json_str

    def test_fork_round_trip(self):
        fork = Fork(
            tracked_repo_id="r",
            github_id=1,
            owner="x",
            full_name="x/y",
            default_branch="main",
            vitality=ForkVitality.ACTIVE,
            stars=42,
        )
        data = fork.model_dump()
        restored = Fork(**data)
        assert restored.vitality == ForkVitality.ACTIVE
        assert restored.stars == 42

    def test_digest_config_round_trip(self):
        config = DigestConfig(
            frequency="daily",
            categories=["feature", "fix"],
            backends=["console", "email"],
        )
        data = config.model_dump()
        restored = DigestConfig(**data)
        assert restored.categories == ["feature", "fix"]
        assert restored.backends == ["console", "email"]

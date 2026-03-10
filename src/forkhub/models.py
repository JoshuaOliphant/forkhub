# ABOUTME: Pydantic data models for all ForkHub domain objects.
# ABOUTME: Pure data structures — no ORM, no database coupling.

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

# ── Enums ────────────────────────────────────────────────────


class TrackingMode(StrEnum):
    """How a repository is being tracked."""

    OWNED = "owned"
    WATCHED = "watched"
    UPSTREAM = "upstream"


class SignalCategory(StrEnum):
    """Classification of a detected change signal."""

    FEATURE = "feature"
    FIX = "fix"
    REFACTOR = "refactor"
    CONFIG = "config"
    DEPENDENCY = "dependency"
    REMOVAL = "removal"
    ADAPTATION = "adaptation"
    RELEASE = "release"


class ForkVitality(StrEnum):
    """Activity state of a fork."""

    ACTIVE = "active"
    DORMANT = "dormant"
    DEAD = "dead"
    UNKNOWN = "unknown"


class BackfillStatus(StrEnum):
    """Outcome of a backfill attempt for a fork signal."""

    PENDING = "pending"
    PATCH_FAILED = "patch_failed"
    TESTS_FAILED = "tests_failed"
    CONFLICT = "conflict"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


# ── Helper ───────────────────────────────────────────────────


def _utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(tz=UTC)


def _new_uuid() -> str:
    """Generate a new UUID4 string for use as a primary key."""
    return str(uuid4())


# ── Domain Models (Database-backed) ─────────────────────────


class TrackedRepo(BaseModel):
    """A GitHub repository being monitored by ForkHub."""

    id: str = Field(default_factory=_new_uuid)
    github_id: int
    owner: str
    name: str
    full_name: str
    tracking_mode: TrackingMode
    default_branch: str
    description: str | None = None
    fork_depth: int = Field(default=1)
    excluded: bool = Field(default=False)
    webhook_id: int | None = None
    last_synced_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utc_now)


class Fork(BaseModel):
    """A fork of a tracked repository."""

    id: str = Field(default_factory=_new_uuid)
    tracked_repo_id: str
    github_id: int
    owner: str
    full_name: str
    default_branch: str
    description: str | None = None
    vitality: ForkVitality = Field(default=ForkVitality.UNKNOWN)
    stars: int = Field(default=0)
    stars_previous: int = Field(default=0)
    parent_fork_id: str | None = None
    depth: int = Field(default=1)
    last_pushed_at: datetime | None = None
    commits_ahead: int = Field(default=0)
    commits_behind: int = Field(default=0)
    head_sha: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class Signal(BaseModel):
    """A classified change detected by the analysis agent."""

    id: str = Field(default_factory=_new_uuid)
    fork_id: str | None = None
    tracked_repo_id: str
    category: SignalCategory
    summary: str
    detail: str | None = None
    files_involved: list[str] = Field(default_factory=list)
    significance: int = Field(default=5, ge=1, le=10)
    embedding: bytes | None = None
    is_upstream: bool = Field(default=False)
    release_tag: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)


class Cluster(BaseModel):
    """A group of similar signals from independent forks."""

    id: str = Field(default_factory=_new_uuid)
    tracked_repo_id: str
    label: str
    description: str
    files_pattern: list[str] = Field(default_factory=list)
    fork_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class ClusterMember(BaseModel):
    """Associates a signal and fork with a cluster."""

    cluster_id: str
    signal_id: str
    fork_id: str


class DigestConfig(BaseModel):
    """Configuration for periodic digest notifications."""

    id: str = Field(default_factory=_new_uuid)
    tracked_repo_id: str | None = None
    frequency: str = Field(default="weekly")
    day_of_week: int | None = None
    time_of_day: str = Field(default="09:00")
    min_significance: int = Field(default=5)
    categories: list[str] | None = None
    file_patterns: list[str] | None = None
    backends: list[str] = Field(default_factory=lambda: ["console"])
    created_at: datetime = Field(default_factory=_utc_now)


class Digest(BaseModel):
    """A generated digest notification."""

    id: str = Field(default_factory=_new_uuid)
    config_id: str | None = None
    title: str
    body: str
    signal_ids: list[str] = Field(default_factory=list)
    delivered_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utc_now)


class Annotation(BaseModel):
    """A user-created note attached to a fork."""

    id: str = Field(default_factory=_new_uuid)
    fork_id: str
    title: str
    body: str
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class BackfillAttempt(BaseModel):
    """Record of an attempt to backfill a fork's change into the local repo."""

    id: str = Field(default_factory=_new_uuid)
    signal_id: str
    fork_id: str
    tracked_repo_id: str
    status: BackfillStatus = Field(default=BackfillStatus.PENDING)
    branch_name: str | None = None
    patch_summary: str | None = None
    test_output: str | None = None
    error: str | None = None
    files_patched: list[str] = Field(default_factory=list)
    score: float | None = None
    created_at: datetime = Field(default_factory=_utc_now)


class BackfillResult(BaseModel):
    """Summary of a backfill run across multiple signals."""

    total_evaluated: int = 0
    attempted: int = 0
    accepted: int = 0
    patch_failed: int = 0
    tests_failed: int = 0
    conflicts: int = 0
    branches_created: list[str] = Field(default_factory=list)


# ── API Response Models (from GitProvider) ──────────────────


class RepoInfo(BaseModel):
    """Repository metadata returned from the git provider."""

    github_id: int
    owner: str
    name: str
    full_name: str
    default_branch: str
    description: str | None = None
    is_fork: bool
    parent_full_name: str | None = None
    stars: int
    forks_count: int
    last_pushed_at: datetime | None = None


class ForkInfo(BaseModel):
    """Fork metadata returned from the git provider."""

    github_id: int
    owner: str
    full_name: str
    default_branch: str
    description: str | None = None
    stars: int
    last_pushed_at: datetime | None = None
    has_diverged: bool
    created_at: datetime


class ForkPage(BaseModel):
    """Paginated list of forks from the git provider."""

    forks: list[ForkInfo]
    total_count: int
    page: int
    has_next: bool


class FileChange(BaseModel):
    """A single file change within a comparison result."""

    filename: str
    status: str
    additions: int
    deletions: int
    patch: str | None = None


class CommitInfo(BaseModel):
    """Metadata for a single commit."""

    sha: str
    message: str
    author: str
    authored_at: datetime


class CompareResult(BaseModel):
    """Result of comparing two branches or refs."""

    ahead_by: int
    behind_by: int
    files: list[FileChange]
    commits: list[CommitInfo]


class Release(BaseModel):
    """A tagged release on a repository."""

    tag: str
    name: str
    body: str
    published_at: datetime
    is_prerelease: bool


class RateLimitInfo(BaseModel):
    """Current rate limit status from the git provider."""

    limit: int
    remaining: int
    reset_at: datetime


class DeliveryResult(BaseModel):
    """Result of delivering a digest notification."""

    backend_name: str
    success: bool
    error: str | None = None
    delivered_at: datetime


class WebhookAction(BaseModel):
    """An action derived from a webhook event."""

    action_type: str
    payload: dict

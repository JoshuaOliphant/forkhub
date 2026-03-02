# ABOUTME: Tests for the ClusterService that groups similar signals across forks.
# ABOUTME: Uses a StubEmbeddingProvider with deterministic embeddings for reproducibility.

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from forkhub.database import Database
from forkhub.services.cluster import ClusterService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uuid() -> str:
    return str(uuid4())


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _make_tracked_repo(**overrides) -> dict:
    defaults = {
        "id": _uuid(),
        "github_id": 123456,
        "owner": "torvalds",
        "name": "linux",
        "full_name": "torvalds/linux",
        "tracking_mode": "active",
        "default_branch": "main",
        "description": "Linux kernel source tree",
        "fork_depth": 1,
        "excluded": False,
        "webhook_id": None,
        "last_synced_at": None,
        "created_at": _now_iso(),
    }
    defaults.update(overrides)
    return defaults


def _make_fork(tracked_repo_id: str, **overrides) -> dict:
    defaults = {
        "id": _uuid(),
        "tracked_repo_id": tracked_repo_id,
        "github_id": 789012,
        "owner": "gregkh",
        "full_name": "gregkh/linux",
        "default_branch": "main",
        "description": "Greg KH's linux fork",
        "vitality": "active",
        "stars": 42,
        "stars_previous": 40,
        "parent_fork_id": None,
        "depth": 1,
        "last_pushed_at": _now_iso(),
        "commits_ahead": 10,
        "commits_behind": 5,
        "head_sha": "abc123def456",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    defaults.update(overrides)
    return defaults


def _make_signal(fork_id: str, tracked_repo_id: str, **overrides) -> dict:
    defaults = {
        "id": _uuid(),
        "fork_id": fork_id,
        "tracked_repo_id": tracked_repo_id,
        "category": "feature",
        "summary": "Added GPU support",
        "detail": "Implements CUDA acceleration for training loop",
        "files_involved": json.dumps(["src/gpu.py", "src/train.py"]),
        "significance": 7,
        "embedding": None,
        "is_upstream": False,
        "release_tag": None,
        "created_at": _now_iso(),
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Stub EmbeddingProvider
# ---------------------------------------------------------------------------


class StubEmbeddingProvider:
    """Deterministic embedding provider for testing.

    Generates embeddings based on text content using a simple hash-based
    approach. Similar texts produce similar embeddings. The first 4 dimensions
    encode a hash of the text, the rest are zeros.
    """

    def __init__(self, dims: int = 8) -> None:
        self._dims = dims
        self._call_count = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self._call_count += 1
        results = []
        for text in texts:
            embedding = self._text_to_embedding(text)
            results.append(embedding)
        return results

    def dimensions(self) -> int:
        return self._dims

    def _text_to_embedding(self, text: str) -> list[float]:
        """Convert text to a deterministic embedding vector.

        Similar texts get similar vectors by using character frequency
        distribution. This gives us predictable cosine similarity behavior.
        """
        vec = [0.0] * self._dims
        for _i, ch in enumerate(text):
            idx = ord(ch) % self._dims
            vec[idx] += 1.0
        # Normalize to unit vector
        magnitude = math.sqrt(sum(v * v for v in vec))
        if magnitude > 0:
            vec = [v / magnitude for v in vec]
        return vec


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
def embedding_provider() -> StubEmbeddingProvider:
    return StubEmbeddingProvider()


@pytest.fixture
async def repo_in_db(db: Database) -> dict:
    repo = _make_tracked_repo()
    await db.insert_tracked_repo(repo)
    return repo


@pytest.fixture
async def two_forks_in_db(db: Database, repo_in_db: dict) -> tuple[dict, dict]:
    """Create two forks under the same repo from different owners."""
    fork_a = _make_fork(
        repo_in_db["id"],
        github_id=1001,
        owner="alice",
        full_name="alice/linux",
    )
    fork_b = _make_fork(
        repo_in_db["id"],
        github_id=1002,
        owner="bob",
        full_name="bob/linux",
    )
    await db.insert_fork(fork_a)
    await db.insert_fork(fork_b)
    return fork_a, fork_b


# ---------------------------------------------------------------------------
# Cosine distance tests
# ---------------------------------------------------------------------------


class TestCosineDistance:
    def test_identical_vectors_have_zero_distance(self):
        svc = ClusterService.__new__(ClusterService)
        vec = [1.0, 0.0, 0.0, 1.0]
        assert svc._cosine_distance(vec, vec) == pytest.approx(0.0, abs=1e-9)

    def test_orthogonal_vectors_have_distance_one(self):
        svc = ClusterService.__new__(ClusterService)
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert svc._cosine_distance(a, b) == pytest.approx(1.0, abs=1e-9)

    def test_opposite_vectors_have_distance_two(self):
        svc = ClusterService.__new__(ClusterService)
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert svc._cosine_distance(a, b) == pytest.approx(2.0, abs=1e-9)

    def test_similar_vectors_have_small_distance(self):
        svc = ClusterService.__new__(ClusterService)
        a = [1.0, 0.1]
        b = [1.0, 0.2]
        dist = svc._cosine_distance(a, b)
        assert dist < 0.1

    def test_zero_vector_returns_one(self):
        """Distance with a zero vector should return 1.0 (maximally dissimilar)."""
        svc = ClusterService.__new__(ClusterService)
        a = [1.0, 0.0]
        b = [0.0, 0.0]
        assert svc._cosine_distance(a, b) == pytest.approx(1.0, abs=1e-9)


# ---------------------------------------------------------------------------
# _should_cluster tests
# ---------------------------------------------------------------------------


class TestShouldCluster:
    def test_different_forks_close_distance_overlapping_files_clusters(self):
        svc = ClusterService.__new__(ClusterService)
        sig_a = {"fork_id": "fork-a", "files_involved": '["src/gpu.py", "src/train.py"]'}
        sig_b = {"fork_id": "fork-b", "files_involved": '["src/gpu.py", "src/model.py"]'}
        assert svc._should_cluster(sig_a, sig_b, distance=0.1) is True

    def test_same_fork_does_not_cluster(self):
        svc = ClusterService.__new__(ClusterService)
        sig_a = {"fork_id": "fork-a", "files_involved": '["src/gpu.py"]'}
        sig_b = {"fork_id": "fork-a", "files_involved": '["src/gpu.py"]'}
        assert svc._should_cluster(sig_a, sig_b, distance=0.05) is False

    def test_distance_above_threshold_does_not_cluster(self):
        svc = ClusterService.__new__(ClusterService)
        sig_a = {"fork_id": "fork-a", "files_involved": '["src/gpu.py"]'}
        sig_b = {"fork_id": "fork-b", "files_involved": '["src/gpu.py"]'}
        assert svc._should_cluster(sig_a, sig_b, distance=0.5, threshold=0.3) is False

    def test_no_overlapping_files_does_not_cluster(self):
        svc = ClusterService.__new__(ClusterService)
        sig_a = {"fork_id": "fork-a", "files_involved": '["src/gpu.py"]'}
        sig_b = {"fork_id": "fork-b", "files_involved": '["docs/readme.md"]'}
        assert svc._should_cluster(sig_a, sig_b, distance=0.05) is False

    def test_overlapping_directories_clusters(self):
        """Files in the same directory count as overlapping."""
        svc = ClusterService.__new__(ClusterService)
        sig_a = {"fork_id": "fork-a", "files_involved": '["src/training/gpu.py"]'}
        sig_b = {"fork_id": "fork-b", "files_involved": '["src/training/cpu.py"]'}
        assert svc._should_cluster(sig_a, sig_b, distance=0.1) is True

    def test_custom_threshold(self):
        svc = ClusterService.__new__(ClusterService)
        sig_a = {"fork_id": "fork-a", "files_involved": '["src/gpu.py"]'}
        sig_b = {"fork_id": "fork-b", "files_involved": '["src/gpu.py"]'}
        # Distance 0.15 is below 0.2 threshold
        assert svc._should_cluster(sig_a, sig_b, distance=0.15, threshold=0.2) is True
        # Distance 0.25 is above 0.2 threshold
        assert svc._should_cluster(sig_a, sig_b, distance=0.25, threshold=0.2) is False


# ---------------------------------------------------------------------------
# Cluster label generation tests
# ---------------------------------------------------------------------------


class TestGenerateClusterLabel:
    def test_single_category_label(self):
        svc = ClusterService.__new__(ClusterService)
        signals = [
            {"category": "feature", "files_involved": '["src/gpu.py"]'},
            {"category": "feature", "files_involved": '["src/gpu.py"]'},
        ]
        label = svc._generate_cluster_label(signals)
        assert "feature" in label.lower()

    def test_mixed_categories_label(self):
        svc = ClusterService.__new__(ClusterService)
        signals = [
            {"category": "feature", "files_involved": '["src/gpu.py"]'},
            {"category": "fix", "files_involved": '["src/gpu.py"]'},
        ]
        label = svc._generate_cluster_label(signals)
        # Should contain at least one of the categories
        assert "feature" in label.lower() or "fix" in label.lower()

    def test_common_files_in_label(self):
        svc = ClusterService.__new__(ClusterService)
        signals = [
            {"category": "feature", "files_involved": '["src/gpu.py", "src/train.py"]'},
            {"category": "feature", "files_involved": '["src/gpu.py", "src/model.py"]'},
        ]
        label = svc._generate_cluster_label(signals)
        # Common file should influence the label
        assert "gpu" in label.lower() or "src" in label.lower()


# ---------------------------------------------------------------------------
# Embedding generation tests
# ---------------------------------------------------------------------------


class TestEmbeddingGeneration:
    async def test_generates_embeddings_for_unembedded_signals(
        self,
        db: Database,
        embedding_provider: StubEmbeddingProvider,
        repo_in_db: dict,
        two_forks_in_db: tuple[dict, dict],
    ):
        """Signals without embeddings should get embeddings after update_clusters."""
        fork_a, _ = two_forks_in_db
        signal = _make_signal(fork_a["id"], repo_in_db["id"], summary="GPU acceleration")
        await db.insert_signal(signal)

        svc = ClusterService(db, embedding_provider)
        await svc.update_clusters(repo_in_db["id"])

        # Verify the embedding was stored
        cursor = await db._db.execute(
            "SELECT embedding FROM signals WHERE id = ?", (signal["id"],)
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row["embedding"] is not None

    async def test_skips_already_embedded_signals(
        self,
        db: Database,
        embedding_provider: StubEmbeddingProvider,
        repo_in_db: dict,
        two_forks_in_db: tuple[dict, dict],
    ):
        """Signals that already have embeddings should not be re-embedded."""
        fork_a, _ = two_forks_in_db
        # Insert a signal that already has an embedding
        existing_embedding = json.dumps([0.5] * 8).encode("utf-8")
        signal = _make_signal(
            fork_a["id"],
            repo_in_db["id"],
            embedding=existing_embedding,
        )
        await db.insert_signal(signal)

        svc = ClusterService(db, embedding_provider)
        await svc.update_clusters(repo_in_db["id"])

        # Embed should not have been called since all signals are already embedded
        assert embedding_provider._call_count == 0


# ---------------------------------------------------------------------------
# Clustering behavior tests
# ---------------------------------------------------------------------------


class TestClusterFormation:
    async def test_similar_signals_from_different_forks_form_cluster(
        self,
        db: Database,
        embedding_provider: StubEmbeddingProvider,
        repo_in_db: dict,
        two_forks_in_db: tuple[dict, dict],
    ):
        """Two signals with similar summaries from different forks should cluster."""
        fork_a, fork_b = two_forks_in_db
        # Use identical summaries and overlapping files to guarantee clustering
        sig_a = _make_signal(
            fork_a["id"],
            repo_in_db["id"],
            summary="Added GPU acceleration for training",
            files_involved=json.dumps(["src/gpu.py", "src/train.py"]),
        )
        sig_b = _make_signal(
            fork_b["id"],
            repo_in_db["id"],
            summary="Added GPU acceleration for training",
            files_involved=json.dumps(["src/gpu.py", "src/model.py"]),
        )
        await db.insert_signal(sig_a)
        await db.insert_signal(sig_b)

        svc = ClusterService(db, embedding_provider)
        clusters = await svc.update_clusters(repo_in_db["id"])

        assert len(clusters) >= 1
        # The cluster should reference at least 2 forks
        assert clusters[0].fork_count >= 2

    async def test_similar_signals_from_same_fork_do_not_cluster(
        self,
        db: Database,
        embedding_provider: StubEmbeddingProvider,
        repo_in_db: dict,
        two_forks_in_db: tuple[dict, dict],
    ):
        """Two signals from the same fork should NOT form a cluster."""
        fork_a, _ = two_forks_in_db
        sig_a = _make_signal(
            fork_a["id"],
            repo_in_db["id"],
            summary="Added GPU acceleration for training",
            files_involved=json.dumps(["src/gpu.py"]),
        )
        sig_b = _make_signal(
            fork_a["id"],
            repo_in_db["id"],
            summary="Added GPU acceleration for training",
            files_involved=json.dumps(["src/gpu.py"]),
        )
        await db.insert_signal(sig_a)
        await db.insert_signal(sig_b)

        svc = ClusterService(db, embedding_provider)
        clusters = await svc.update_clusters(repo_in_db["id"])

        assert len(clusters) == 0

    async def test_dissimilar_signals_do_not_cluster(
        self,
        db: Database,
        embedding_provider: StubEmbeddingProvider,
        repo_in_db: dict,
        two_forks_in_db: tuple[dict, dict],
    ):
        """Signals with very different summaries should not cluster."""
        fork_a, fork_b = two_forks_in_db
        sig_a = _make_signal(
            fork_a["id"],
            repo_in_db["id"],
            summary="x" * 50,  # Repetitive text A
            category="feature",
            files_involved=json.dumps(["src/aaa.py"]),
        )
        sig_b = _make_signal(
            fork_b["id"],
            repo_in_db["id"],
            summary="y" * 50,  # Repetitive text B (totally different character distribution)
            category="fix",
            files_involved=json.dumps(["docs/zzz.md"]),
        )
        await db.insert_signal(sig_a)
        await db.insert_signal(sig_b)

        svc = ClusterService(db, embedding_provider)
        clusters = await svc.update_clusters(repo_in_db["id"])

        assert len(clusters) == 0

    async def test_cluster_growth_new_signal_joins_existing_cluster(
        self,
        db: Database,
        embedding_provider: StubEmbeddingProvider,
        repo_in_db: dict,
    ):
        """A new signal similar to an existing cluster's signals should join it."""
        # Create three forks
        fork_a = _make_fork(
            repo_in_db["id"], github_id=2001, owner="alice", full_name="alice/proj"
        )
        fork_b = _make_fork(
            repo_in_db["id"], github_id=2002, owner="bob", full_name="bob/proj"
        )
        fork_c = _make_fork(
            repo_in_db["id"], github_id=2003, owner="carol", full_name="carol/proj"
        )
        await db.insert_fork(fork_a)
        await db.insert_fork(fork_b)
        await db.insert_fork(fork_c)

        # First two signals create a cluster
        summary = "Added GPU acceleration for training"
        files = json.dumps(["src/gpu.py", "src/train.py"])
        sig_a = _make_signal(
            fork_a["id"], repo_in_db["id"], summary=summary, files_involved=files
        )
        sig_b = _make_signal(
            fork_b["id"], repo_in_db["id"], summary=summary, files_involved=files
        )
        await db.insert_signal(sig_a)
        await db.insert_signal(sig_b)

        svc = ClusterService(db, embedding_provider)
        clusters = await svc.update_clusters(repo_in_db["id"])
        assert len(clusters) == 1
        initial_count = clusters[0].fork_count

        # Third signal should join the existing cluster
        sig_c = _make_signal(
            fork_c["id"], repo_in_db["id"], summary=summary, files_involved=files
        )
        await db.insert_signal(sig_c)
        clusters = await svc.update_clusters(repo_in_db["id"])

        # Should still be 1 cluster but with increased fork count
        assert len(clusters) >= 1
        # Find the cluster with max fork_count
        max_forks = max(c.fork_count for c in clusters)
        assert max_forks > initial_count


# ---------------------------------------------------------------------------
# get_clusters tests
# ---------------------------------------------------------------------------


class TestGetClusters:
    async def test_get_clusters_returns_all_by_default(
        self,
        db: Database,
        embedding_provider: StubEmbeddingProvider,
        repo_in_db: dict,
    ):
        """get_clusters with default min_size=2 should return clusters with 2+ forks."""
        # Manually insert a cluster with fork_count=3
        cluster_dict = {
            "id": _uuid(),
            "tracked_repo_id": repo_in_db["id"],
            "label": "GPU acceleration",
            "description": "Multiple forks adding GPU support",
            "files_pattern": json.dumps(["src/gpu.py"]),
            "fork_count": 3,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        await db.insert_cluster(cluster_dict)

        svc = ClusterService(db, embedding_provider)
        clusters = await svc.get_clusters(repo_in_db["id"])
        assert len(clusters) == 1

    async def test_get_clusters_respects_min_size(
        self,
        db: Database,
        embedding_provider: StubEmbeddingProvider,
        repo_in_db: dict,
    ):
        """Clusters below min_size should be filtered out."""
        small_cluster = {
            "id": _uuid(),
            "tracked_repo_id": repo_in_db["id"],
            "label": "Small cluster",
            "description": "Only one fork",
            "files_pattern": json.dumps([]),
            "fork_count": 1,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        big_cluster = {
            "id": _uuid(),
            "tracked_repo_id": repo_in_db["id"],
            "label": "Big cluster",
            "description": "Many forks",
            "files_pattern": json.dumps([]),
            "fork_count": 5,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        await db.insert_cluster(small_cluster)
        await db.insert_cluster(big_cluster)

        svc = ClusterService(db, embedding_provider)

        # Default min_size=2 should exclude the small cluster
        clusters = await svc.get_clusters(repo_in_db["id"])
        assert len(clusters) == 1
        assert clusters[0].label == "Big cluster"

        # min_size=1 should include both
        clusters = await svc.get_clusters(repo_in_db["id"], min_size=1)
        assert len(clusters) == 2

        # min_size=10 should exclude both
        clusters = await svc.get_clusters(repo_in_db["id"], min_size=10)
        assert len(clusters) == 0

    async def test_get_clusters_empty_repo(
        self,
        db: Database,
        embedding_provider: StubEmbeddingProvider,
        repo_in_db: dict,
    ):
        """A repo with no clusters should return an empty list."""
        svc = ClusterService(db, embedding_provider)
        clusters = await svc.get_clusters(repo_in_db["id"])
        assert clusters == []


# ---------------------------------------------------------------------------
# update_clusters returns updated clusters
# ---------------------------------------------------------------------------


class TestUpdateClustersReturn:
    async def test_returns_empty_when_no_signals(
        self,
        db: Database,
        embedding_provider: StubEmbeddingProvider,
        repo_in_db: dict,
    ):
        """update_clusters on a repo with no signals should return empty list."""
        svc = ClusterService(db, embedding_provider)
        clusters = await svc.update_clusters(repo_in_db["id"])
        assert clusters == []

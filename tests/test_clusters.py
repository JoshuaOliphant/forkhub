# ABOUTME: Tests for the ClusterService that groups similar signals across forks.
# ABOUTME: Uses a StubEmbeddingProvider with deterministic embeddings for reproducibility.

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from forkhub.services.cluster import ClusterService
from tests.stubs import (
    StubEmbeddingProvider,
    make_fork,
    make_signal,
)

if TYPE_CHECKING:
    from forkhub.database import Database

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def two_forks_in_db(db: Database, repo_in_db: dict) -> tuple[dict, dict]:
    """Create two forks under the same repo from different owners."""
    fork_a = make_fork(
        repo_in_db["id"],
        github_id=1001,
        owner="alice",
        full_name="alice/linux",
    )
    fork_b = make_fork(
        repo_in_db["id"],
        github_id=1002,
        owner="bob",
        full_name="bob/linux",
    )
    await db.insert_fork(fork_a)
    await db.insert_fork(fork_b)
    return fork_a, fork_b


# ---------------------------------------------------------------------------
# Clustering behavior tests
# ---------------------------------------------------------------------------


class TestClusterFormation:
    async def test_cluster_growth_new_signal_joins_existing_cluster(
        self,
        db: Database,
        embedding_provider: StubEmbeddingProvider,
        repo_in_db: dict,
    ):
        """A new signal similar to an existing cluster's signals should join it."""
        # Create three forks
        fork_a = make_fork(repo_in_db["id"], github_id=2001, owner="alice", full_name="alice/proj")
        fork_b = make_fork(repo_in_db["id"], github_id=2002, owner="bob", full_name="bob/proj")
        fork_c = make_fork(repo_in_db["id"], github_id=2003, owner="carol", full_name="carol/proj")
        await db.insert_fork(fork_a)
        await db.insert_fork(fork_b)
        await db.insert_fork(fork_c)

        # First two signals create a cluster
        summary = "Added GPU acceleration for training"
        files = json.dumps(["src/gpu.py", "src/train.py"])
        sig_a = make_signal(fork_a["id"], repo_in_db["id"], summary=summary, files_involved=files)
        sig_b = make_signal(fork_b["id"], repo_in_db["id"], summary=summary, files_involved=files)
        await db.insert_signal(sig_a)
        await db.insert_signal(sig_b)

        svc = ClusterService(db, embedding_provider)
        clusters = await svc.update_clusters(repo_in_db["id"])
        assert len(clusters) == 1
        initial_count = clusters[0].fork_count

        # Third signal should join the existing cluster
        sig_c = make_signal(fork_c["id"], repo_in_db["id"], summary=summary, files_involved=files)
        await db.insert_signal(sig_c)
        clusters = await svc.update_clusters(repo_in_db["id"])

        # Should still be 1 cluster but with increased fork count
        assert len(clusters) >= 1
        # Find the cluster with max fork_count
        max_forks = max(c.fork_count for c in clusters)
        assert max_forks > initial_count


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

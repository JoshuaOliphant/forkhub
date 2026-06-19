# ABOUTME: Unit tests for the Explore web data mapper (build_explore_data).
# ABOUTME: Seeds an in-memory DB and asserts the frontend JSON shape + edge cases.

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from forkhub import ForkHub
from forkhub.config import ForkHubSettings
from forkhub.web.data import build_explore_data

if TYPE_CHECKING:
    from forkhub.database import Database
from tests.stubs import (
    StubEmbeddingProvider,
    StubGitProvider,
    StubNotificationBackend,
    make_cluster,
    make_cluster_member,
    make_fork,
    make_signal,
    make_tracked_repo,
)


@pytest.fixture
def hub(
    db: Database,
    provider: StubGitProvider,
    backend: StubNotificationBackend,
    embedding_provider: StubEmbeddingProvider,
) -> ForkHub:
    return ForkHub(
        settings=ForkHubSettings(),
        git_provider=provider,
        notification_backends=[backend],
        embedding_provider=embedding_provider,
        db=db,
    )


class TestBuildExploreData:
    async def test_shape_and_field_mapping(self, hub: ForkHub, db: Database):
        repo = make_tracked_repo()  # last_synced_at None -> last_sync None branch
        await db.insert_tracked_repo(repo)
        f1 = make_fork(
            repo["id"],
            github_id=1,
            full_name="alice/linux",
            owner="alice",
            head_sha="7b2e004deadbeef",
        )
        f2 = make_fork(
            repo["id"], github_id=2, full_name="bob/linux", owner="bob", head_sha="c40aa12cafef00d"
        )
        f3 = make_fork(
            repo["id"], github_id=3, full_name="carol/linux", owner="carol", head_sha=None
        )
        for f in (f1, f2, f3):
            await db.insert_fork(f)
        s1 = make_signal(f1["id"], repo["id"])
        s2 = make_signal(f2["id"], repo["id"])
        await db.insert_signal(s1)
        await db.insert_signal(s2)
        # A repo-level signal (fork_id None) must be skipped by the mapper.
        await db.insert_signal(make_signal(None, repo["id"]))
        cluster = make_cluster(repo["id"], fork_count=2)
        await db.insert_cluster(cluster)
        await db.add_cluster_member(make_cluster_member(cluster["id"], s1["id"], f1["id"]))
        await db.add_cluster_member(make_cluster_member(cluster["id"], s2["id"], f2["id"]))

        data = await build_explore_data(hub, "torvalds", "linux")

        # repo
        assert data["repo"] == {
            "name": "linux",
            "full_name": "torvalds/linux",
            "fork_count": 3,
            "last_sync": None,
        }
        # forks (indexed by id)
        forks = {f["id"]: f for f in data["forks"]}
        fa = forks[f1["id"]]
        assert fa["owner"] == "alice"
        assert fa["sha"] == "7b2e004"  # short
        assert fa["html_url"] == "https://github.com/alice/linux"  # fork's own name, rename-safe
        assert fa["signal"]["category"] == "feature"
        assert fa["signal"]["reasoning"] == s1["detail"]  # detail -> reasoning
        assert fa["signal"]["files"] == ["src/gpu.py", "src/train.py"]  # files_involved -> files
        assert fa["signal"]["significance"] == s1["significance"]
        # fork with no signal + no sha
        fc = forks[f3["id"]]
        assert fc["sha"] is None
        assert fc["signal"] is None
        # clusters
        assert len(data["clusters"]) == 1
        cl = data["clusters"][0]
        assert cl["label"] == cluster["label"]
        assert cl["summary"] == cluster["description"]
        assert set(cl["members"]) == {f1["id"], f2["id"]}

    async def test_last_sync_serialized_when_set(self, hub: ForkHub, db: Database):
        repo = make_tracked_repo(last_synced_at="2026-06-01T12:00:00+00:00")
        await db.insert_tracked_repo(repo)
        data = await build_explore_data(hub, "torvalds", "linux")
        assert data["repo"]["last_sync"].startswith("2026-06-01T12:00:00")

    async def test_untracked_repo_raises(self, hub: ForkHub):
        with pytest.raises(ValueError, match="not tracked"):
            await build_explore_data(hub, "nobody", "nothing")

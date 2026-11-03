# ABOUTME: Tests bounded upstream, downstream, and sibling relationship discovery.
# ABOUTME: Uses the shared GitProvider stub with no network access.

from __future__ import annotations

import pytest

from forkhub.models import ForkInfo, ForkPage, RepoInfo
from forkhub.providers.github import GitHubProviderError
from forkhub.services.relationships import RelationshipDirection, RelationshipService
from tests.stubs import STUB_NOW, StubGitProvider


def _fork(github_id: int, full_name: str) -> ForkInfo:
    return ForkInfo(
        github_id=github_id,
        owner=full_name.split("/")[0],
        full_name=full_name,
        default_branch="main",
        stars=0,
        last_pushed_at=STUB_NOW,
        has_diverged=True,
        created_at=STUB_NOW,
    )


class TestRelationshipDiscovery:
    async def test_owned_repo_returns_downstream_forks(self):
        provider = StubGitProvider.with_testuser_data()
        service = RelationshipService(provider)
        result = await service.discover("testuser", "testuser/alpha")
        assert result.upstream_repo is None
        assert result.complete
        assert result.pages_scanned == 1
        assert len(result.relationships) == 1
        rel = result.relationships[0]
        assert rel.direction == RelationshipDirection.DOWNSTREAM
        assert rel.source_repo == "forker1/alpha"
        assert rel.target_repo == "testuser/alpha"
        assert rel.github_id == 5001
        assert not rel.is_user_repository

    async def test_personal_fork_returns_upstream_and_siblings(self):
        provider = StubGitProvider.with_testuser_data()
        provider._forks["upstream-org/forked-lib"] = [
            _fork(1003, "testuser/forked-lib"),
            _fork(9999, "other/forked-lib"),
            _fork(9999, "other/forked-lib"),
        ]
        result = await RelationshipService(provider).discover("testuser", "testuser/forked-lib")
        assert result.upstream_repo == "upstream-org/forked-lib"
        assert result.complete
        assert [r.direction for r in result.relationships] == [
            RelationshipDirection.UPSTREAM,
            RelationshipDirection.SIBLING,
        ]
        assert [r.source_repo for r in result.relationships] == [
            "upstream-org/forked-lib",
            "other/forked-lib",
        ]
        assert not result.relationships[0].is_user_repository

    async def test_missing_parent_marks_incomplete(self):
        parentless = RepoInfo(
            github_id=20,
            owner="testuser",
            name="orphan",
            full_name="testuser/orphan",
            default_branch="main",
            is_fork=True,
            parent_full_name=None,
            stars=0,
            forks_count=0,
            last_pushed_at=STUB_NOW,
        )
        provider = StubGitProvider(user_repos={"testuser": [parentless]})
        result = await RelationshipService(provider).discover("testuser", "testuser/orphan")
        assert not result.complete
        assert result.relationships == []
        assert result.pages_scanned == 0

    async def test_missing_named_upstream_returns_partial_snapshot(self):
        provider = StubGitProvider.with_testuser_data()
        del provider.repos["upstream-org/forked-lib"]
        result = await RelationshipService(provider).discover("testuser", "testuser/forked-lib")
        assert result.upstream_repo == "upstream-org/forked-lib"
        assert not result.complete
        assert result.relationships == []

    async def test_inaccessible_named_upstream_returns_partial_snapshot(self):
        provider = StubGitProvider.with_testuser_data()

        async def forbidden(owner: str, repo: str) -> RepoInfo:
            raise GitHubProviderError(404, "not found")

        provider.get_repo = forbidden  # type: ignore[method-assign]
        result = await RelationshipService(provider).discover("testuser", "testuser/forked-lib")
        assert not result.complete
        assert result.upstream_repo == "upstream-org/forked-lib"

    async def test_upstream_rate_limit_error_propagates(self):
        provider = StubGitProvider.with_testuser_data()

        async def rate_limited(owner: str, repo: str) -> RepoInfo:
            raise GitHubProviderError(429, "rate limited")

        provider.get_repo = rate_limited  # type: ignore[method-assign]
        with pytest.raises(GitHubProviderError):
            await RelationshipService(provider).discover("testuser", "testuser/forked-lib")

    async def test_unknown_focus_repo_propagates_provider_error(self):
        with pytest.raises(ValueError, match="Repo not found"):
            await RelationshipService(StubGitProvider.with_testuser_data()).discover(
                "testuser", "nobody/missing"
            )

    async def test_untracked_public_repo_is_supported(self):
        provider = StubGitProvider.with_testuser_data()
        provider._forks["upstream-org/forked-lib"] = [_fork(1003, "testuser/forked-lib")]
        result = await RelationshipService(provider).discover("testuser", "upstream-org/forked-lib")
        assert result.focus_repo == "upstream-org/forked-lib"
        assert len(result.relationships) == 1
        assert result.relationships[0].direction == RelationshipDirection.DOWNSTREAM
        assert result.relationships[0].is_user_repository
        assert result.complete

    async def test_user_owned_fork_is_labeled(self):
        provider = StubGitProvider.with_testuser_data()
        provider._forks["testuser/alpha"] = [_fork(1003, "testuser/forked-lib")]
        result = await RelationshipService(provider).discover("testuser", "testuser/alpha")
        assert result.relationships[0].is_user_repository

    async def test_page_budget_reports_incomplete_coverage(self):
        provider = StubGitProvider.with_testuser_data()

        async def page_two(owner: str, repo: str, *, page: int = 1) -> ForkPage:
            return ForkPage(
                forks=[_fork(7000 + page, f"other{page}/alpha")],
                total_count=10,
                page=page,
                has_next=True,
            )

        provider.get_forks = page_two  # type: ignore[method-assign]
        result = await RelationshipService(provider).discover(
            "testuser", "testuser/alpha", max_pages=2
        )
        assert not result.complete
        assert result.pages_scanned == 2
        assert len(result.relationships) == 2

    @pytest.mark.parametrize("repository", ["none", "a/", "/b", "a/b/c"])
    async def test_invalid_repository(self, repository: str):
        with pytest.raises(ValueError, match="owner/name"):
            await RelationshipService(StubGitProvider()).discover("testuser", repository)

    async def test_invalid_page_budget(self):
        with pytest.raises(ValueError, match="max_pages"):
            await RelationshipService(StubGitProvider()).discover(
                "testuser", "any/repo", max_pages=0
            )

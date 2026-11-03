# ABOUTME: Read-only discovery of a developer's upstream, downstream, and sibling forks.
# ABOUTME: Builds a bounded relationship snapshot from the existing GitProvider interface.

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from forkhub.interfaces import ProviderError

if TYPE_CHECKING:
    from forkhub.interfaces import GitProvider


class RelationshipDirection(StrEnum):
    UPSTREAM = "upstream"
    DOWNSTREAM = "downstream"
    SIBLING = "sibling"


class RepositoryRelationship(BaseModel):
    # For all directions, source is the repo providing a potential change;
    # target is the focus repo whose developer is evaluating that change.
    direction: RelationshipDirection
    source_repo: str
    target_repo: str
    github_id: int
    is_user_repository: bool = False


class RelationshipSnapshot(BaseModel):
    focus_repo: str
    upstream_repo: str | None = None
    relationships: list[RepositoryRelationship] = Field(default_factory=list)
    complete: bool = True
    pages_scanned: int = 0


class RelationshipService:
    """Discover a bounded neighborhood without writing to GitHub or the database.

    For a user's fork, the parent is its upstream; other forks of that same
    parent are siblings. For an original repository, its forks are downstream.
    The result reports incomplete coverage instead of silently implying that
    every fork was inspected.
    """

    def __init__(self, provider: GitProvider) -> None:
        self._provider = provider

    async def discover(
        self, username: str, repository: str, *, max_pages: int = 3
    ) -> RelationshipSnapshot:
        if max_pages < 1:
            raise ValueError("max_pages must be at least 1")
        if repository.count("/") != 1 or not all(repository.split("/")):
            raise ValueError("repository must have the form owner/name")

        # Unknown focus repositories propagate the provider error to the caller.
        user_repos = await self._provider.get_user_repos(username)
        mine = {repo.full_name.casefold() for repo in user_repos}
        focus = next(
            (repo for repo in user_repos if repo.full_name.casefold() == repository.casefold()),
            None,
        )
        if focus is None:
            owner, name = repository.split("/")
            focus = await self._provider.get_repo(owner, name)

        snapshot = RelationshipSnapshot(focus_repo=focus.full_name)
        if focus.is_fork and focus.parent_full_name:
            snapshot.upstream_repo = focus.parent_full_name
            owner, name = focus.parent_full_name.split("/", 1)
            try:
                parent = await self._provider.get_repo(owner, name)
            except ProviderError as exc:
                # GitHub may hide inaccessible repos as 404, or return 403.
                # Do not disguise rate limits / transient server errors.
                if getattr(exc, "status_code", None) not in (403, 404):
                    raise
                snapshot.complete = False
                return snapshot
            except ValueError:
                # The shared stub uses ValueError for unknown repositories.
                snapshot.complete = False
                return snapshot
            snapshot.relationships.append(
                RepositoryRelationship(
                    direction=RelationshipDirection.UPSTREAM,
                    source_repo=parent.full_name,
                    target_repo=focus.full_name,
                    github_id=parent.github_id,
                    is_user_repository=parent.full_name.casefold() in mine,
                )
            )
            fork_source = parent
            direction = RelationshipDirection.SIBLING
        elif focus.is_fork:
            # A deleted/inaccessible parent cannot support sibling discovery.
            snapshot.complete = False
            return snapshot
        else:
            fork_source = focus
            direction = RelationshipDirection.DOWNSTREAM

        page = 1
        seen: set[int] = set()
        while page <= max_pages:
            fork_page = await self._provider.get_forks(
                fork_source.owner, fork_source.name, page=page
            )
            snapshot.pages_scanned += 1
            for fork in fork_page.forks:
                if (\n                    fork.github_id in seen\n                    or fork.full_name.casefold() == focus.full_name.casefold()\n                ):
                    continue
                seen.add(fork.github_id)
                snapshot.relationships.append(
                    RepositoryRelationship(
                        direction=direction,
                        source_repo=fork.full_name,
                        target_repo=focus.full_name,
                        github_id=fork.github_id,
                        is_user_repository=fork.full_name.casefold() in mine,
                    )
                )
            if not fork_page.has_next:
                break
            page += 1
        else:
            snapshot.complete = False
        return snapshot

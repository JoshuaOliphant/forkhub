# ABOUTME: Build the relationship-first Explore payload from the shared scan contract.
# ABOUTME: Never confuse an absent or incomplete scan with an empty fork graph.

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from forkhub import ForkHub


async def build_explore_data(forkhub: ForkHub, owner: str, repo: str) -> dict[str, Any]:
    """Read a persisted relationship snapshot without performing discovery."""
    full_name = f"{owner}/{repo}"
    tracked = next(
        (r for r in await forkhub.get_repos() if r.full_name.casefold() == full_name.casefold()),
        None,
    )
    if tracked is None:
        raise ValueError(f"Repository {full_name} is not tracked")

    # Snapshots are scoped by discovering user. For a personal repository the
    # owner is the scope; configurable identity is preferred for watched repos.
    configured_user = forkhub.github_username
    username = configured_user or owner
    relationship = await forkhub.get_relationship_view(username, tracked.full_name)
    return {
        "repo": {
            "name": tracked.name,
            "full_name": tracked.full_name,
            "last_sync": tracked.last_synced_at.isoformat() if tracked.last_synced_at else None,
        },
        "discovery_username": username,
        "relationship": relationship,
        "signals": await forkhub.get_signal_view(tracked.full_name),
    }

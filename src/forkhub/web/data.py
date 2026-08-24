# ABOUTME: Maps ForkHub library models into the Explore frontend's JSON shape.
# ABOUTME: Pure mapping over the public API; the FastAPI route serves the result.

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from forkhub import ForkHub


async def build_explore_data(forkhub: ForkHub, owner: str, repo: str) -> dict[str, Any]:
    """Assemble the Explore page data for one tracked repo.

    Returns the shape the constellation frontend reads from its embedded JSON:
    ``{repo, clusters[{id,label,members,summary}], forks[{id,owner,sha,html_url,signal?}]}``.
    Signal fields are mapped from the real model (``detail`` -> ``reasoning``,
    ``files_involved`` -> ``files``); there is no per-fork cost. A fork with no
    signal yet maps to ``signal: None``. Raises ``ValueError`` if untracked.
    """
    full_name = f"{owner}/{repo}"
    tracked = next((r for r in await forkhub.get_repos() if r.full_name == full_name), None)
    if tracked is None:
        raise ValueError(f"Repository {full_name} is not tracked")

    forks = await forkhub.get_forks(owner, repo)
    clusters = await forkhub.get_clusters(owner, repo)
    members = await forkhub.get_cluster_members(owner, repo)

    # Latest signal per fork (get_signals is created_at DESC, so first wins).
    latest: dict[str, Any] = {}
    for sig in await forkhub.get_signals(owner, repo):
        if sig.fork_id is not None:
            latest.setdefault(sig.fork_id, sig)

    def _signal(fork_id: str) -> dict[str, Any] | None:
        sig = latest.get(fork_id)
        if sig is None:
            return None
        return {
            "category": str(sig.category),
            "significance": sig.significance,
            "summary": sig.summary,
            "reasoning": sig.detail,
            "files": sig.files_involved,
        }

    return {
        "repo": {
            "name": tracked.name,
            "full_name": tracked.full_name,
            "fork_count": len(forks),
            "last_sync": tracked.last_synced_at.isoformat() if tracked.last_synced_at else None,
        },
        "clusters": [
            {
                "id": c.id,
                "label": c.label,
                "members": members.get(c.id, []),
                "summary": c.description,
            }
            for c in clusters
        ],
        "forks": [
            {
                "id": f.id,
                "owner": f.owner,
                "sha": f.head_sha[:7] if f.head_sha else None,
                "html_url": f"https://github.com/{f.full_name}",
                "signal": _signal(f.id),
            }
            for f in forks
        ],
    }

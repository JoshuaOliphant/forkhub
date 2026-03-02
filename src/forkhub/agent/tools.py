# ABOUTME: Custom tool definitions for the Agent SDK analysis agent.
# ABOUTME: Tools like list_forks, get_fork_summary, store_signal that run in-process.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import SdkMcpTool, tool

from forkhub.models import Signal, SignalCategory

if TYPE_CHECKING:
    from forkhub.database import Database
    from forkhub.interfaces import EmbeddingProvider, GitProvider


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    """Format a successful tool response."""
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def _err(message: str) -> dict[str, Any]:
    """Format an error tool response."""
    return {"content": [{"type": "text", "text": f"Error: {message}"}], "is_error": True}


def create_tools(
    db: Database,
    provider: GitProvider,
    embedding_provider: EmbeddingProvider,
    clock: datetime | None = None,
) -> list[SdkMcpTool]:
    """Create all ForkHub agent tools with injected dependencies."""

    # ------------------------------------------------------------------
    # 1. list_forks
    # ------------------------------------------------------------------
    @tool(
        "list_forks",
        "List forks of a tracked repository. Returns paginated fork info. "
        "Set only_active=True to filter to active forks from the database.",
        {"owner": str, "repo": str, "page": int, "only_active": bool},
    )
    async def list_forks(args: dict[str, Any]) -> dict[str, Any]:
        try:
            owner = args["owner"]
            repo = args["repo"]
            page = args.get("page", 1)
            only_active = args.get("only_active", False)

            if only_active:
                # Filter from DB by vitality
                tracked = await db.get_tracked_repo_by_name(f"{owner}/{repo}")
                if tracked is None:
                    return _err(f"Tracked repo {owner}/{repo} not found in database")
                db_forks = await db.list_forks(tracked["id"], vitality="active")
                fork_list = [
                    {
                        "full_name": f["full_name"],
                        "owner": f["owner"],
                        "stars": f["stars"],
                        "vitality": f["vitality"],
                        "description": f["description"],
                    }
                    for f in db_forks
                ]
                return _ok({"forks": fork_list, "page": page, "has_next": False})

            fork_page = await provider.get_forks(owner, repo, page=page)
            fork_list = [
                {
                    "full_name": fi.full_name,
                    "owner": fi.owner,
                    "stars": fi.stars,
                    "description": fi.description,
                    "has_diverged": fi.has_diverged,
                    "last_pushed_at": fi.last_pushed_at.isoformat() if fi.last_pushed_at else None,
                }
                for fi in fork_page.forks
            ]
            return _ok(
                {
                    "forks": fork_list,
                    "page": fork_page.page,
                    "has_next": fork_page.has_next,
                }
            )
        except Exception as exc:
            return _err(str(exc))

    # ------------------------------------------------------------------
    # 2. get_fork_summary
    # ------------------------------------------------------------------
    @tool(
        "get_fork_summary",
        "Get a summary of a fork including commits ahead/behind, files changed, "
        "and recent commit messages. This is the CHEAP call — use it first before "
        "fetching full diffs.",
        {"fork_full_name": str},
    )
    async def get_fork_summary(args: dict[str, Any]) -> dict[str, Any]:
        try:
            fork_full_name = args["fork_full_name"]
            fork_row = await db.get_fork_by_name(fork_full_name)
            if fork_row is None:
                return _err(f"Fork not found in database: {fork_full_name}")

            # Look up the tracked repo for upstream info
            tracked = await db.get_tracked_repo(fork_row["tracked_repo_id"])
            if tracked is None:
                return _err(f"Tracked repo not found for fork: {fork_full_name}")

            # Get compare result from provider (fork vs upstream)
            fork_owner = fork_row["owner"]
            upstream_owner = tracked["owner"]
            upstream_name = tracked["name"]
            upstream_branch = tracked["default_branch"]
            fork_branch = fork_row["default_branch"]

            compare = await provider.compare(
                upstream_owner,
                upstream_name,
                f"{upstream_owner}:{upstream_branch}",
                f"{fork_owner}:{fork_branch}",
            )

            # Get recent commit messages
            commits = await provider.get_commit_messages(fork_owner, fork_full_name.split("/")[1])

            files_changed = [f.filename for f in compare.files]
            recent_commits = [
                {"sha": c.sha, "message": c.message, "author": c.author} for c in commits[:10]
            ]

            return _ok(
                {
                    "full_name": fork_full_name,
                    "commits_ahead": compare.ahead_by,
                    "commits_behind": compare.behind_by,
                    "files_changed": files_changed,
                    "recent_commits": recent_commits,
                    "stars": fork_row["stars"],
                    "vitality": fork_row["vitality"],
                }
            )
        except Exception as exc:
            return _err(str(exc))

    # ------------------------------------------------------------------
    # 3. get_file_diff
    # ------------------------------------------------------------------
    @tool(
        "get_file_diff",
        "Get the full diff for a single file in a fork compared to upstream. "
        "This is the EXPENSIVE call — only use it for files you truly need to analyze.",
        {"fork_full_name": str, "file_path": str},
    )
    async def get_file_diff(args: dict[str, Any]) -> dict[str, Any]:
        try:
            fork_full_name = args["fork_full_name"]
            file_path = args["file_path"]

            fork_row = await db.get_fork_by_name(fork_full_name)
            if fork_row is None:
                return _err(f"Fork not found in database: {fork_full_name}")

            tracked = await db.get_tracked_repo(fork_row["tracked_repo_id"])
            if tracked is None:
                return _err(f"Tracked repo not found for fork: {fork_full_name}")

            fork_owner = fork_row["owner"]
            upstream_owner = tracked["owner"]
            upstream_name = tracked["name"]
            upstream_branch = tracked["default_branch"]
            fork_branch = fork_row["default_branch"]

            diff = await provider.get_file_diff(
                upstream_owner,
                upstream_name,
                f"{upstream_owner}:{upstream_branch}",
                f"{fork_owner}:{fork_branch}",
                file_path,
            )

            return _ok({"diff": diff})
        except Exception as exc:
            return _err(str(exc))

    # ------------------------------------------------------------------
    # 4. get_releases
    # ------------------------------------------------------------------
    @tool(
        "get_releases",
        "Fetch releases for a repository filtered by date. "
        "Use since_days to limit how far back to look.",
        {"owner": str, "repo": str, "since_days": int},
    )
    async def get_releases(args: dict[str, Any]) -> dict[str, Any]:
        try:
            owner = args["owner"]
            repo = args["repo"]
            since_days = args.get("since_days", 30)

            now = clock if clock is not None else datetime.now(tz=UTC)
            since = now - timedelta(days=since_days)
            releases = await provider.get_releases(owner, repo, since=since)

            release_list = [
                {
                    "tag": r.tag,
                    "name": r.name,
                    "published_at": r.published_at.isoformat(),
                }
                for r in releases
            ]
            return _ok({"releases": release_list})
        except Exception as exc:
            return _err(str(exc))

    # ------------------------------------------------------------------
    # 5. get_fork_stars
    # ------------------------------------------------------------------
    @tool(
        "get_fork_stars",
        "Get star count and velocity for a fork. "
        "Velocity is the change in stars since the last sync.",
        {"fork_full_name": str},
    )
    async def get_fork_stars(args: dict[str, Any]) -> dict[str, Any]:
        try:
            fork_full_name = args["fork_full_name"]
            fork_row = await db.get_fork_by_name(fork_full_name)
            if fork_row is None:
                return _err(f"Fork not found in database: {fork_full_name}")

            stars = fork_row["stars"]
            stars_previous = fork_row["stars_previous"]
            velocity = stars - stars_previous

            return _ok(
                {
                    "stars": stars,
                    "stars_previous": stars_previous,
                    "velocity": velocity,
                }
            )
        except Exception as exc:
            return _err(str(exc))

    # ------------------------------------------------------------------
    # 6. store_signal
    # ------------------------------------------------------------------
    @tool(
        "store_signal",
        "Store a classified change signal for a fork. "
        "Category must be one of: feature, fix, refactor, config, dependency, "
        "removal, adaptation, release. Significance is 1-10.",
        {
            "fork_full_name": str,
            "category": str,
            "summary": str,
            "significance": int,
            "files_involved": list,
            "detail": str,
        },
    )
    async def store_signal(args: dict[str, Any]) -> dict[str, Any]:
        try:
            fork_full_name = args["fork_full_name"]
            category_str = args["category"]
            summary = args["summary"]
            significance = args["significance"]
            files_involved = args.get("files_involved", [])
            detail = args.get("detail", "")

            # Validate category
            valid_categories = {c.value for c in SignalCategory}
            if category_str not in valid_categories:
                return _err(
                    f"Invalid category: {category_str!r}. "
                    f"Must be one of: {', '.join(sorted(valid_categories))}"
                )

            # Look up fork in DB
            fork_row = await db.get_fork_by_name(fork_full_name)
            if fork_row is None:
                return _err(f"Fork not found in database: {fork_full_name}")

            # Build and persist the signal
            signal = Signal(
                fork_id=fork_row["id"],
                tracked_repo_id=fork_row["tracked_repo_id"],
                category=SignalCategory(category_str),
                summary=summary,
                detail=detail if detail else None,
                files_involved=files_involved,
                significance=significance,
            )

            # Generate embedding for similarity search
            try:
                embeddings = await embedding_provider.embed([summary])
                import struct

                embedding_bytes = struct.pack(f"{len(embeddings[0])}f", *embeddings[0])
                signal.embedding = embedding_bytes
            except Exception:
                # Embedding generation is non-critical
                pass

            signal_dict = signal.model_dump()
            signal_dict["created_at"] = signal.created_at.isoformat()
            signal_dict["files_involved"] = json.dumps(signal.files_involved)

            await db.insert_signal(signal_dict)

            return _ok({"signal_id": signal.id})
        except Exception as exc:
            return _err(str(exc))

    # ------------------------------------------------------------------
    # 7. search_similar_signals
    # ------------------------------------------------------------------
    @tool(
        "search_similar_signals",
        "Search for signals similar to the given summary text using vector similarity. "
        "Useful for detecting clusters of similar changes across forks.",
        {"summary_text": str, "repo_id": str, "limit": int},
    )
    async def search_similar_signals(args: dict[str, Any]) -> dict[str, Any]:
        try:
            summary_text = args["summary_text"]
            repo_id = args["repo_id"]
            limit = args.get("limit", 5)

            # Generate embedding for the query text
            embeddings = await embedding_provider.embed([summary_text])
            embedding = embeddings[0]

            results = await db.search_similar_signals(embedding, repo_id, limit=limit)

            similar = [
                {
                    "id": r.get("id"),
                    "summary": r.get("summary"),
                    "category": r.get("category"),
                    "significance": r.get("significance"),
                }
                for r in results
            ]

            return _ok({"similar_signals": similar})
        except Exception as exc:
            return _err(str(exc))

    return [
        list_forks,
        get_fork_summary,
        get_file_diff,
        get_releases,
        get_fork_stars,
        store_signal,
        search_similar_signals,
    ]

# ABOUTME: Define read-only cache queries and their public MCP result contract.
# ABOUTME: Share validation and result interpretation across SQLite and D1 storage.

from __future__ import annotations

import json
import re
from datetime import datetime

TRACKED_REPOSITORIES_SQL = (
    "SELECT full_name, tracking_mode, last_synced_at, sync_status "
    "FROM tracked_repos WHERE excluded = 0 ORDER BY full_name LIMIT ?"
)
RELATIONSHIP_SNAPSHOT_SQL = (
    "SELECT focus_github_id, focus_repo, upstream_repo, complete, pages_scanned, "
    "updated_at, last_attempt_at, last_attempt_complete, "
    "last_attempt_pages_scanned, last_complete_at FROM relationship_snapshots "
    "WHERE username = ? AND focus_repo = ? COLLATE NOCASE"
)
RELATIONSHIP_EDGES_SQL = (
    "SELECT direction, source_github_id, source_repo, target_repo, "
    "is_user_repository FROM repository_relationships "
    "WHERE username = ? AND focus_github_id = ? ORDER BY rowid"
)
TRACKED_REPOSITORY_SQL = (
    "SELECT id, last_synced_at, sync_status FROM tracked_repos "
    "WHERE full_name = ? COLLATE NOCASE AND excluded = 0"
)
SIGNALS_SQL = (
    "SELECT id, summary, detail, category, significance, created_at, files_involved, "
    "evidence FROM signals "
    "WHERE tracked_repo_id = ? AND significance >= ? "
    "ORDER BY significance DESC, created_at DESC, id LIMIT ?"
)


def normalize_username(username: str) -> str:
    if not username.strip():
        raise ValueError("FORKHUB_MCP_USER must be configured")
    return username.strip().casefold()


def validate_limit(limit: int) -> None:
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50")


def validate_repository(repository: str) -> None:
    if repository.count("/") != 1 or not all(repository.split("/")):
        raise ValueError("Repository must be owner/name")


def validate_signal_query(repository: str, min_significance: int, limit: int) -> None:
    validate_repository(repository)
    if not 1 <= min_significance <= 10:
        raise ValueError("min_significance must be between 1 and 10")
    validate_limit(limit)


def tracked_repositories_result(rows: list[dict], limit: int) -> dict:
    return {
        "repositories": [
            {
                "name": row["full_name"],
                "mode": row["tracking_mode"],
                "last_synced_at": row["last_synced_at"],
                "sync_status": row["sync_status"],
            }
            for row in rows[:limit]
        ],
        "returned": min(len(rows), limit),
        "truncated": len(rows) > limit,
        "source": "forkhub_cache",
    }


def relationships_result(repository: str, row: dict | None, edges: list[dict]) -> dict:
    if row is None:
        return {
            "repository": repository,
            "status": "not_scanned",
            "message": "No cached relationship snapshot. Run local discovery first.",
        }
    complete = bool(row["complete"])
    last_attempt_complete = (
        bool(row["last_attempt_complete"]) if row["last_attempt_complete"] is not None else complete
    )
    last_attempt_at = row["last_attempt_at"] or row["updated_at"]
    last_complete_at = row["last_complete_at"] or (row["updated_at"] if complete else None)
    preserved = complete and not last_attempt_complete
    return {
        "repository": repository,
        "status": "cached",
        "last_attempt_complete": last_attempt_complete,
        "last_attempt_at": last_attempt_at,
        "last_attempt_pages_scanned": (
            row["last_attempt_pages_scanned"]
            if row["last_attempt_pages_scanned"] is not None
            else row["pages_scanned"]
        ),
        "last_complete_at": last_complete_at,
        "preserved_complete_snapshot": preserved,
        "snapshot": {
            "focus_github_id": row["focus_github_id"],
            "focus_repo": row["focus_repo"],
            "upstream_repo": row["upstream_repo"],
            "complete": complete,
            "pages_scanned": row["pages_scanned"],
            "relationships": [
                {
                    "direction": edge["direction"],
                    "github_id": edge["source_github_id"],
                    "source_repo": edge["source_repo"],
                    "target_repo": edge["target_repo"],
                    "is_user_repository": bool(edge["is_user_repository"]),
                }
                for edge in edges
            ],
        },
        "warning": (
            "Latest scan was incomplete. Showing the last complete snapshot; "
            "its relationships may now be stale."
            if preserved
            else (
                "Incomplete fork coverage; results must not be presented as exhaustive."
                if not complete
                else None
            )
        ),
    }


def _read_evidence(raw: str | None) -> tuple[dict | None, bool]:
    if not raw:
        return None, False
    try:
        evidence = json.loads(raw)
        repository = evidence["source_repository"]
        shas = evidence["commit_shas"]
        filenames = evidence["files"]
        state = evidence["verification_state"]
        warnings = evidence.get("warnings", [])
        changes = evidence.get("changes", [])
        valid = (
            re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            and isinstance(shas, list)
            and all(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) for sha in shas)
            and len(set(shas)) == len(shas)
            and isinstance(filenames, list)
            and all(isinstance(filename, str) and filename for filename in filenames)
            and len(set(filenames)) == len(filenames)
            and state in ("unavailable", "partial", "verified")
            and isinstance(warnings, list)
            and all(isinstance(warning, str) for warning in warnings)
            and isinstance(changes, list)
            and all(
                isinstance(change, dict)
                and isinstance(change.get("commit_sha"), str)
                and re.fullmatch(r"[0-9a-f]{40}", change["commit_sha"])
                and isinstance(change.get("filename"), str)
                and change["filename"]
                and isinstance(change.get("status"), str)
                and (change.get("patch") is None or isinstance(change["patch"], str))
                for change in changes
            )
        )
        if not valid:
            return None, True
        if state == "verified":
            if not shas or not filenames:
                return None, True
            if not isinstance(changes, list) or not all(
                isinstance(change["patch"], str)
                and change["patch"].strip()
                and change["commit_sha"] in shas
                and change["filename"] in filenames
                for change in changes
            ):
                return None, True
            if {change["commit_sha"] for change in changes} != set(shas) or {
                change["filename"] for change in changes
            } != set(filenames):
                return None, True
            verified_at = datetime.fromisoformat(evidence["verified_at"])
            if verified_at.tzinfo is None:
                return None, True
        return evidence, False
    except (ValueError, KeyError, TypeError):
        return None, True


def _signal_result(row: dict) -> dict:
    evidence, invalid = _read_evidence(row.get("evidence"))
    files_involved = json.loads(row["files_involved"])
    if (
        evidence
        and evidence["verification_state"] == "verified"
        and set(evidence["files"]) != set(files_involved)
    ):
        evidence, invalid = None, True
    state = evidence["verification_state"] if evidence else "unavailable"
    verified = state == "verified"
    warning = {
        "verified": (
            "Immutable commit and file evidence was checked; the model's interpretation "
            "and significance are not independently verified."
        ),
        "partial": "SHA-level evidence is partial; do not treat this interpretation as verified.",
        "unavailable": "SHA-level evidence is unavailable; this interpretation is unverified.",
    }[state]
    if invalid:
        warning += " Stored evidence is malformed and cannot be trusted."
    return {
        "id": row["id"],
        "summary": row["summary"],
        "detail": row["detail"],
        "category": row["category"],
        "significance": row["significance"],
        "created_at": row["created_at"],
        "files_involved": files_involved,
        "interpretation_is_model_generated": True,
        "verified_against_immutable_sha_evidence": verified,
        "evidence": evidence,
        "commit_links": [
            f"https://github.com/{evidence['source_repository']}/commit/{sha}"
            for sha in evidence["commit_shas"]
        ]
        if evidence
        else [],
        "warning": warning,
    }


def signals_result(
    repository: str, rows: list[dict] | None, limit: int, tracked: dict | None = None
) -> dict:
    if rows is None:
        return {
            "repository": repository,
            "status": "not_tracked",
            "signals": [],
            "message": "Repository is not tracked by ForkHub.",
        }
    last_synced_at = tracked.get("last_synced_at") if tracked else None
    sync_status = tracked.get("sync_status") if tracked else None
    freshness = (
        "stale"
        if sync_status and sync_status != "ok"
        else "last_sync_succeeded"
        if last_synced_at
        else "unknown"
    )
    signals = [_signal_result(row) for row in rows[:limit]]
    warning = (
        "Model interpretations and significance are not independently verified. "
        "Inspect each signal's SHA-level evidence and verification state. "
        "Immutable commit evidence does not establish current branch equivalence."
    )
    if freshness == "stale":
        warning += " Latest repository sync failed; cached analysis may be stale."
    elif freshness == "unknown":
        warning += " Repository sync freshness is unknown."
    return {
        "repository": repository,
        "status": "cached",
        "signals": signals,
        "truncated": len(rows) > limit,
        "source": "forkhub_cache",
        "last_synced_at": last_synced_at,
        "sync_status": sync_status,
        "freshness": freshness,
        "warning": warning,
    }

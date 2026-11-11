# ABOUTME: Prepare private schema-paired signal cache releases without changing the source.
# ABOUTME: Check complete tool-response parity and retain explicit pending hosted acceptance.

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from forkhub.mcp_cache_export import export_cache
from forkhub.mcp_preview_queries import PreviewQueries


def _create_private(path: Path) -> int:
    return os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)


def _write_json(path: Path, value: dict) -> None:
    with os.fdopen(_create_private(path), "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_equal(actual: object, expected: object, message: str) -> None:
    if actual != expected:
        raise ValueError(message)


def _responses(reader: PreviewQueries, repository: str) -> dict:
    return {
        "list_tracked_repositories": reader.list_tracked_repositories(limit=50),
        "get_cached_relationships": reader.get_cached_relationships(repository),
        "list_cached_signals": reader.list_cached_signals(repository, min_significance=1, limit=50),
    }


def prepare_signal_release(
    source: Path,
    output: Path,
    username: str,
    repository: str,
    *,
    confirm_single_user: bool = False,
) -> dict:
    """Export a current-schema single-user cache; never migrate the operational source.

    A manifest is written last, only after all local checks pass. Its existence
    does not establish deployment, website inspection or live ChatGPT acceptance.
    """
    if not confirm_single_user:
        raise ValueError("Confirm this is one user's dedicated cache before preparing a release")
    source = source.expanduser().resolve(strict=True)
    output = output.expanduser().absolute()
    sql = output / "cache.sql"
    imported = output / "cache.db"
    retained = output / "snapshot.db"
    with tempfile.TemporaryDirectory(prefix="forkhub-release-") as temporary:
        snapshot = Path(temporary) / "snapshot.db"
        os.close(_create_private(snapshot))
        with (
            closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original,
            closing(sqlite3.connect(snapshot)) as copy,
        ):
            original.backup(copy)
            if "evidence" not in {row[1] for row in copy.execute("PRAGMA table_info(signals)")}:
                raise ValueError(
                    "Source schema lacks signals.evidence; back up and migrate a disposable "
                    "application copy before preparing a release"
                )
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        with (
            snapshot.open("rb") as source_stream,
            os.fdopen(_create_private(retained), "wb") as destination,
        ):
            shutil.copyfileobj(source_stream, destination)
        expected = _responses(PreviewQueries(snapshot, username), repository)
        if any(result.get("truncated") for result in expected.values()):
            raise ValueError("Acceptance responses exceed the 50-row tool limit; narrow the cache")
        signals = expected["list_cached_signals"].get("signals", [])
        verified = [s["id"] for s in signals if s["verified_against_immutable_sha_evidence"]]
        if not verified:
            raise ValueError(
                "Target must contain a visible signal with verified immutable evidence"
            )
        counts = export_cache(snapshot, sql, username, confirm_single_user=True)
        os.close(_create_private(imported))
        with closing(sqlite3.connect(imported)) as connection:
            connection.executescript(sql.read_text(encoding="utf-8"))
            _require_equal(
                connection.execute("PRAGMA quick_check").fetchall(),
                [("ok",)],
                "Imported cache failed SQLite quick_check",
            )
        _require_equal(
            _responses(PreviewQueries(imported, username), repository),
            expected,
            "Source and exported cache tool responses differ",
        )
    _write_json(output / "expected.json", expected)
    manifest = {
        "format": 1,
        "prepared_at": datetime.now(UTC).isoformat(),
        "username": username.strip().casefold(),
        "repository": repository,
        "counts": counts,
        "verified_signal_ids": verified,
        "tool_arguments": {
            "list_tracked_repositories": {"limit": 50},
            "get_cached_relationships": {"repository": repository},
            "list_cached_signals": {"repository": repository, "min_significance": 1, "limit": 50},
        },
        "sha256": {p.name: _digest(p) for p in (sql, imported, retained, output / "expected.json")},
        "local_export_import_parity": "passed",
        "website_inspection": "pending",
        "hosted_rollout": "pending",
        "authenticated_chatgpt_acceptance": "pending",
    }
    _write_json(output / "manifest.json", manifest)
    return manifest


def compare_signal_release(bundle: Path, actual: dict) -> None:
    """Compare saved fresh tool response bodies; caller establishes their origin."""
    manifest = json.loads((bundle / "manifest.json").read_text())
    for filename in ("cache.sql", "cache.db", "snapshot.db", "expected.json"):
        if _digest(bundle / filename) != manifest["sha256"][filename]:
            raise ValueError(f"Release artifact checksum mismatch: {filename}")
    expected = json.loads((bundle / "expected.json").read_text())
    _require_equal(actual, expected, "Actual tool responses differ from the prepared release")

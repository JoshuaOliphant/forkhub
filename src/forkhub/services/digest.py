# ABOUTME: Digest generation and delivery service.
# ABOUTME: Queries signals, composes digests, and delivers via notification backends.

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatch
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forkhub.database import Database
    from forkhub.interfaces import NotificationBackend

from forkhub.models import DeliveryResult, Digest, DigestConfig


class DigestService:
    """Generates digest notifications from signals and delivers them via backends.

    Supports filtering by significance, category, file patterns, and time range.
    Dispatches delivery to one or more NotificationBackend implementations.
    """

    def __init__(self, db: Database, backends: list[NotificationBackend]) -> None:
        self._db = db
        self._backends = backends

    async def generate_digest(
        self,
        config: DigestConfig,
        since: datetime | None = None,
    ) -> Digest:
        """Generate a digest notification from signals matching the config criteria.

        Queries signals from the database, filters by config rules, composes
        a digest body, saves it to the DB, and returns it.
        """
        # Determine time range
        since_dt = since if since is not None else (datetime.now(UTC) - timedelta(days=7))

        # Gather signals from relevant repos
        all_signals: list[dict] = []
        if config.tracked_repo_id:
            signals = await self._db.list_signals(config.tracked_repo_id, since=since_dt)
            all_signals.extend(signals)
        else:
            # Global config: query all tracked repos
            repos = await self._db.list_tracked_repos()
            for repo in repos:
                signals = await self._db.list_signals(repo["id"], since=since_dt)
                all_signals.extend(signals)

        # Apply filters
        filtered: list[dict] = []
        for signal in all_signals:
            # Significance filter
            if signal["significance"] < config.min_significance:
                continue

            # Category filter
            if config.categories is not None and signal["category"] not in config.categories:
                continue

            # File pattern filter
            if config.file_patterns is not None:
                files = (
                    json.loads(signal["files_involved"])
                    if isinstance(signal["files_involved"], str)
                    else signal["files_involved"]
                )
                if not self._matches_file_patterns(files, config.file_patterns):
                    continue

            filtered.append(signal)

        # Build digest content
        today = datetime.now(UTC)
        title = f"ForkHub Digest — {today.strftime('%B %d, %Y')}"

        if filtered:
            body_lines: list[str] = []
            # Group signals by repo
            by_repo: dict[str, list[dict]] = {}
            for sig in filtered:
                repo_id = sig["tracked_repo_id"]
                by_repo.setdefault(repo_id, []).append(sig)

            for repo_id, sigs in by_repo.items():
                body_lines.append(f"## Repository {repo_id}")
                body_lines.append("")
                for sig in sigs:
                    cat = sig["category"]
                    summary = sig["summary"]
                    significance = sig["significance"]
                    body_lines.append(f"- [{cat}] {summary} (significance: {significance})")
                body_lines.append("")

            body = "\n".join(body_lines)
        else:
            body = "No significant changes detected in this period."

        signal_ids = [s["id"] for s in filtered]

        # Ensure the config is persisted so the digest FK is satisfied
        existing_config = await self._db.get_digest_config(config.id)
        if existing_config is None:
            config_dict = config.model_dump()
            config_dict["created_at"] = config.created_at.isoformat()
            config_dict["categories"] = (
                json.dumps(config.categories) if config.categories is not None else None
            )
            config_dict["file_patterns"] = (
                json.dumps(config.file_patterns) if config.file_patterns is not None else None
            )
            config_dict["backends"] = json.dumps(config.backends)
            await self._db.insert_digest_config(config_dict)

        digest = Digest(
            config_id=config.id,
            title=title,
            body=body,
            signal_ids=signal_ids,
        )

        # Save to DB
        digest_dict = digest.model_dump()
        digest_dict["created_at"] = digest.created_at.isoformat()
        digest_dict["delivered_at"] = None
        digest_dict["signal_ids"] = json.dumps(digest.signal_ids)

        await self._db.insert_digest(digest_dict)

        return digest

    async def deliver_digest(self, digest: Digest) -> list[DeliveryResult]:
        """Deliver a digest to all configured backends and update delivery timestamp."""
        results: list[DeliveryResult] = []
        for backend in self._backends:
            result = await backend.deliver(digest)
            results.append(result)

        # Update delivered_at in the database
        now_iso = datetime.now(UTC).isoformat()
        await self._db._db.execute(
            "UPDATE digests SET delivered_at = ? WHERE id = ?",
            (now_iso, digest.id),
        )
        await self._db._db.commit()

        return results

    async def generate_and_deliver(
        self,
        config: DigestConfig | None = None,
        since: datetime | None = None,
    ) -> tuple[Digest, list[DeliveryResult]]:
        """Generate a digest and deliver it in one step.

        If config is None, uses a sensible default configuration that
        includes all repos with default significance threshold.
        """
        if config is None:
            config = DigestConfig(
                tracked_repo_id=None,
                min_significance=5,
            )

        digest = await self.generate_digest(config, since=since)
        results = await self.deliver_digest(digest)
        return digest, results

    def _matches_file_patterns(self, signal_files: list[str], patterns: list[str]) -> bool:
        """Check whether any of the signal's files match any of the glob patterns.

        Returns True if patterns is empty (no filtering), False if signal_files is empty.
        Uses fnmatch for glob-style matching.
        """
        if not patterns:
            return True

        if not signal_files:
            return False

        for filepath in signal_files:
            for pattern in patterns:
                if fnmatch(filepath, pattern):
                    return True

        return False

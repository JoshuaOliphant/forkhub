# ABOUTME: Create a disposable synthetic ForkHub database for MCP transport testing.
# ABOUTME: Refuses to overwrite existing data and never accesses GitHub or AI providers.

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from forkhub.database import Database

DEMO_USER = "forkhub-demo"
DEMO_REPO = "forkhub-demo/sample-project"


async def seed(path: Path) -> None:
    """Build a separate, synthetic SQLite database, never an existing one."""
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing database: {path}")
    if not path.parent.is_dir():
        raise FileNotFoundError(f"Create the destination directory first: {path.parent}")
    timestamp = datetime.now(UTC).isoformat()
    async with Database(path) as db:
        await db.insert_tracked_repo(
            {
                "id": "forkhub-demo-repo",
                "github_id": 900001,
                "owner": DEMO_USER,
                "name": "sample-project",
                "full_name": DEMO_REPO,
                "tracking_mode": "watched",
                "default_branch": "main",
                "description": "Synthetic demonstration repository",
                "fork_depth": 1,
                "excluded": False,
                "webhook_id": None,
                "sync_status": "ok",
                "last_sync_error": None,
                "last_synced_at": timestamp,
                "created_at": timestamp,
            }
        )
        await db.save_relationship_snapshot(
            DEMO_USER,
            {
                "focus_github_id": 900001,
                "focus_repo": DEMO_REPO,
                "upstream_repo": None,
                "complete": True,
                "pages_scanned": 1,
                "relationships": [
                    {
                        "direction": "downstream",
                        "github_id": 900002,
                        "source_repo": "forkhub-demo/sample-fork",
                        "target_repo": DEMO_REPO,
                        "is_user_repository": False,
                    }
                ],
            },
        )
        await db.insert_signal(
            {
                "id": "forkhub-demo-signal",
                "fork_id": None,
                "tracked_repo_id": "forkhub-demo-repo",
                "category": "feature",
                "summary": "Synthetic example: add retry handling",
                "detail": "Illustrative classification only. No real commit was analyzed.",
                "files_involved": json.dumps(["src/retries.py"]),
                "significance": 7,
                "embedding": None,
                "is_upstream": False,
                "release_tag": None,
                "created_at": timestamp,
            }
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a synthetic ForkHub MCP demo database")
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    path = args.database.expanduser().resolve()
    await seed(path)
    print(f"Synthetic MCP demo database created: {path}")
    print(f"Set FORKHUB_MCP_DATABASE_PATH={path}")
    print(f"Set FORKHUB_MCP_USER={DEMO_USER}")


if __name__ == "__main__":
    asyncio.run(main())

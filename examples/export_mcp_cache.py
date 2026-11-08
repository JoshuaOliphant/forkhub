# ABOUTME: Write a private D1 import from one user's dedicated ForkHub cache.
# ABOUTME: Report row counts without printing repository data or SQL values.

from __future__ import annotations

import argparse
import json

from forkhub.mcp_cache_export import export_cache


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Export the read-only ForkHub MCP cache")
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--confirm-single-user", action="store_true", required=True)
    settings = parser.parse_args(arguments)
    counts = export_cache(
        settings.source,
        settings.destination,
        settings.username,
        confirm_single_user=settings.confirm_single_user,
    )
    print(json.dumps(counts, sort_keys=True))


if __name__ == "__main__":
    main()

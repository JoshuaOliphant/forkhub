# ABOUTME: Prepare a private Milestone 2 cache bundle or compare fresh hosted responses.
# ABOUTME: Keep deployment and authentication outside the local preparation command.

from __future__ import annotations

import argparse
import json
from pathlib import Path

from forkhub.services.signal_release import compare_signal_release, prepare_signal_release


def main(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Prepare or compare a signal evidence release")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--source", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--username", required=True)
    prepare.add_argument("--repository", required=True)
    prepare.add_argument("--confirm-single-user", action="store_true", required=True)
    compare = commands.add_parser("compare")
    compare.add_argument("--bundle", type=Path, required=True)
    compare.add_argument("--actual", type=Path, required=True)
    args = parser.parse_args(arguments)
    if args.command == "prepare":
        result = prepare_signal_release(
            args.source,
            args.output,
            args.username,
            args.repository,
            confirm_single_user=args.confirm_single_user,
        )
        print(json.dumps({"counts": result["counts"], "hosted_acceptance": "pending"}))
    else:
        compare_signal_release(args.bundle, json.loads(args.actual.read_text()))
        print("Tool response parity: PASS (response origin must be established separately)")


if __name__ == "__main__":
    main()

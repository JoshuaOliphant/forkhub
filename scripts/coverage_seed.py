# /// script
# requires-python = ">=3.12"
# ///
# ABOUTME: Analyze per-test coverage to find zero-unique and low-unique tests.
# ABOUTME: Uses dynamic_context coverage data to identify safe deletion candidates.

"""Analyze per-test coverage contexts to identify redundant tests.

Reads coverage JSON with --show-contexts and computes:
- Which lines each test uniquely covers (no other test covers them)
- Zero-unique tests: safe to delete without any coverage loss
- Low-unique tests (<10 unique lines): candidates for consolidation

Usage:
    uv run scripts/coverage_seed.py /tmp/cov_contexts.json
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load_contexts(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def analyze(data: dict) -> None:
    # Build line -> set of test contexts mapping
    line_to_tests: dict[str, set[str]] = defaultdict(set)
    test_to_lines: dict[str, set[str]] = defaultdict(set)

    for filename, file_data in data.get("files", {}).items():
        contexts = file_data.get("contexts", {})
        for line_str, ctx_list in contexts.items():
            line_key = f"{filename}:{line_str}"
            for ctx in ctx_list:
                # Contexts look like "test_module.py::TestClass::test_method|run"
                # Strip the "|run" suffix
                test_name = ctx.split("|")[0].strip()
                if not test_name:
                    continue
                line_to_tests[line_key].add(test_name)
                test_to_lines[test_name].add(line_key)

    # Compute unique lines per test
    test_unique_lines: dict[str, set[str]] = defaultdict(set)
    for line_key, tests in line_to_tests.items():
        if len(tests) == 1:
            sole_test = next(iter(tests))
            test_unique_lines[sole_test].add(line_key)

    # Categorize tests
    all_tests = sorted(test_to_lines.keys())
    zero_unique = []
    low_unique = []  # 1-10 unique lines
    high_value = []  # >10 unique lines

    for test in all_tests:
        unique_count = len(test_unique_lines.get(test, set()))
        total_count = len(test_to_lines[test])
        if unique_count == 0:
            zero_unique.append((test, total_count))
        elif unique_count <= 10:
            low_unique.append((test, unique_count, total_count))
        else:
            high_value.append((test, unique_count, total_count))

    # Summary stats
    total_source_lines = len(line_to_tests)
    uniquely_covered_lines = sum(1 for tests in line_to_tests.values() if len(tests) == 1)

    print("=" * 70)
    print("COVERAGE SEED ANALYSIS")
    print("=" * 70)
    print(f"\nTotal tests analyzed: {len(all_tests)}")
    print(f"Total source lines covered: {total_source_lines}")
    print(f"Lines covered by exactly 1 test: {uniquely_covered_lines}")
    print(f"Lines covered by 2+ tests: {total_source_lines - uniquely_covered_lines}")

    print(f"\n--- ZERO-UNIQUE TESTS ({len(zero_unique)}) ---")
    print("These tests cover NO lines exclusively. 100% safe to delete.")
    print("(Every line they cover is also covered by at least one other test)")
    print()
    # Group by file
    by_file: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for test, total in zero_unique:
        parts = test.split("::")
        file_part = parts[0] if parts else test
        by_file[file_part].append((test, total))

    for file_name in sorted(by_file.keys()):
        tests_in_file = by_file[file_name]
        print(f"  {file_name} ({len(tests_in_file)} zero-unique tests):")
        for test, total in sorted(tests_in_file, key=lambda x: x[0]):
            short_name = "::".join(test.split("::")[1:]) if "::" in test else test
            print(f"    {short_name}  (covers {total} lines, all redundant)")

    print(f"\n--- LOW-UNIQUE TESTS ({len(low_unique)}) ---")
    print("These tests cover 1-10 lines exclusively. Review before deleting.")
    print()
    for test, unique, total in sorted(low_unique, key=lambda x: x[1]):
        short_name = test.split("::")[-1] if "::" in test else test
        file_part = test.split("::")[0]
        print(f"  {unique:3d} unique / {total:4d} total  {file_part}::{short_name}")

    print(f"\n--- HIGH-VALUE TESTS ({len(high_value)}) ---")
    print("These tests cover >10 lines exclusively. Do NOT delete.")
    print()
    for test, unique, total in sorted(high_value, key=lambda x: -x[1])[:20]:
        short_name = test.split("::")[-1] if "::" in test else test
        file_part = test.split("::")[0]
        print(f"  {unique:3d} unique / {total:4d} total  {file_part}::{short_name}")
    if len(high_value) > 20:
        print(f"  ... and {len(high_value) - 20} more")

    # Coverage loss estimate
    print(f"\n--- SUMMARY ---")
    print(f"Zero-unique (safe to delete):     {len(zero_unique):4d} tests")
    print(f"Low-unique (review before delete): {len(low_unique):4d} tests")
    print(f"High-value (keep):                 {len(high_value):4d} tests")
    print(f"\nIf all zero-unique tests deleted: 0 lines of coverage lost")
    low_unique_lines = sum(u for _, u, _ in low_unique)
    print(f"If all low-unique also deleted:   {low_unique_lines} lines of coverage lost")
    print(f"  ({low_unique_lines}/{total_source_lines} = {low_unique_lines/total_source_lines*100:.1f}% of covered lines)")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: uv run scripts/coverage_seed.py <cov_contexts.json>")
        sys.exit(1)
    data = load_contexts(sys.argv[1])
    analyze(data)


if __name__ == "__main__":
    main()

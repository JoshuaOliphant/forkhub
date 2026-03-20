#!/usr/bin/env bash
# ABOUTME: Autoloop runner — tiered quality gates + structured METRIC output for test consolidation.
# ABOUTME: Immutable measurement pipeline. The agent must never modify this file.
# Exit code 0 = all gates passed, non-zero = broken (agent should revert)
set -euo pipefail

cd "$(dirname "$0")/.."

# ── Gate 1: Fast tests (hard fail) ────────────────────────────
echo "=== Gate 1: Pytest ==="
uv run pytest -x -q --tb=short 2>&1 | tail -5
echo ""

# ── Gate 2: Lint (hard fail) ──────────────────────────────────
echo "=== Gate 2: Ruff ==="
uv run ruff check src/ tests/
echo "Lint: PASSED"
echo ""

# ── Final gate: Coverage seed analysis ────────────────────────
echo "=== Benchmark: Coverage Seed ==="

# Generate per-test coverage with dynamic contexts
cat > /tmp/.coveragerc_dyn << 'COVERAGERC'
[run]
source = src/forkhub
dynamic_context = test_function
data_file = /tmp/.coverage_forkhub
COVERAGERC

uv run coverage run --rcfile=/tmp/.coveragerc_dyn -m pytest tests/ -q -p no:cov 2>&1 | tail -3
uv run coverage json --rcfile=/tmp/.coveragerc_dyn --show-contexts -o /tmp/cov_contexts.json 2>&1

# Extract metrics from coverage seed analysis
SEED_OUTPUT=$(uv run python scripts/coverage_seed.py /tmp/cov_contexts.json 2>&1)

# Parse metrics
TEST_COUNT=$(echo "$SEED_OUTPUT" | grep "Total tests analyzed:" | grep -oE '[0-9]+' | tail -1)
TOTAL_LINES=$(echo "$SEED_OUTPUT" | grep "Total source lines covered:" | grep -oE '[0-9]+' | tail -1)
UNIQUE_LINES=$(echo "$SEED_OUTPUT" | grep "Lines covered by exactly 1 test:" | grep -oE '[0-9]+' | tail -1)
ZERO_UNIQUE=$(echo "$SEED_OUTPUT" | grep "Zero-unique (safe to delete):" | grep -oE '[0-9]+' | tail -1)

# ── Structured METRIC output ─────────────────────────────────
echo ""
echo "METRIC unique_coverage_lines=$UNIQUE_LINES"
echo "METRIC test_count=$TEST_COUNT"
echo "METRIC total_coverage_lines=$TOTAL_LINES"
echo "METRIC zero_unique_tests=$ZERO_UNIQUE"

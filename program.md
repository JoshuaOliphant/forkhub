# ForkHub Test Consolidation

This is an experiment to have an LLM autonomously eliminate redundant tests while maintaining unique line coverage.

## Objective

Reduce the test count by deleting tests that contribute zero unique coverage (every line they cover is also covered by at least one other test). The coverage seed script (`scripts/coverage_seed.py`) identifies these zero-unique tests.

The optimization target is unique_coverage_lines (highest is better — must stay at or above 460).
Secondary goal: minimize test_count while keeping unique_coverage_lines stable.

## Metrics

- **Primary (optimization target)**: `unique_coverage_lines` (count, highest is better)
- **Secondary (tracked, not optimized)**: `test_count` (count, lower is better — this is the number we want to shrink)
- **Secondary (tracked, not optimized)**: `total_coverage_lines` (count, stable is good)
- **Secondary (tracked, not optimized)**: `zero_unique_tests` (count, lower means fewer remaining candidates)

## How to Run

Run `./auto/run.sh` — it runs quality gates in sequence (pytest → ruff lint → coverage seed analysis), outputting `METRIC key=value` lines on success. If any gate fails, the script exits non-zero and the agent should revert.

**Do NOT modify `auto/run.sh`.** It is the immutable measurement pipeline.

## Files in Scope

These are the files the agent edits to eliminate redundant tests:
- `tests/test_models.py` — Pydantic model tests
- `tests/test_database.py` — SQLite CRUD tests
- `tests/test_sync.py` — Sync service tests
- `tests/test_tracker.py` — Tracker service tests
- `tests/test_cli.py` — CLI command tests
- `tests/test_forkhub_api.py` — Public API tests
- `tests/test_config.py` — Configuration tests
- `tests/test_console_backend.py` — Console rendering tests
- `tests/test_interfaces.py` — Protocol interface tests
- `tests/test_clusters.py` — Cluster detection tests
- `tests/test_digest.py` — Digest generation tests
- `tests/test_embeddings.py` — Embedding provider tests
- `tests/test_github_provider.py` — GitHub API provider tests
- `tests/test_agent_tools.py` — Agent tool tests
- `tests/test_agent_runner.py` — Agent runner tests
- `tests/test_agent_hooks.py` — Agent hook tests
- `tests/test_integration.py` — Integration tests
- `tests/test_smoke.py` — Smoke tests
- `tests/test_packaging.py` — Package structure tests

Read context from:
- `scripts/coverage_seed.py` — Understand how zero-unique tests are identified
- `CLAUDE.md` — Project conventions and testing rules

## Off Limits

Do NOT modify these files. They are read-only context:
- `tests/conftest.py` — Shared fixtures
- `tests/stubs.py` — Shared stub implementations
- `scripts/coverage_seed.py` — The coverage analysis script
- `src/` — All source code (no changes)
- `CLAUDE.md` — Project instructions
- `pyproject.toml` — Build config
- `auto/run.sh` — the runner script. Measurement pipeline is immutable.
- `results.tsv` — log file, append-only (never committed to git).

## Setup

To set up a new experiment run, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar19`). The branch `autoloop/{tag}` must not already exist — this is a fresh run.
2. **Create the branch**: `git checkout -b autoloop/{tag}` from current HEAD.
3. **Read the in-scope files**: Skim the test files and read `scripts/coverage_seed.py` for context.
4. **Verify preconditions**: Run `./auto/run.sh > run.log 2>&1 && grep '^METRIC ' run.log` — verify exit 0 and unique_coverage_lines=460.
5. **Initialize results.tsv**: Create `results.tsv` with just the header row. The baseline will be recorded after the first run.
6. **Confirm and go**: Confirm setup looks good.

Once you get confirmation, kick off the experimentation.

## Experimentation

Each iteration, regenerate the coverage seed to find current zero-unique tests:
1. Run `./auto/run.sh > run.log 2>&1` to get fresh coverage data
2. Read the full seed output to identify zero-unique tests by file
3. Pick 1-3 zero-unique tests to delete from the same file (conservative batching)
4. Verify the deletion doesn't break other tests

**What you CAN do:**
- Delete individual test methods that are zero-unique (cover no exclusive lines)
- Delete entire test classes if ALL their methods are zero-unique
- Parameterize near-duplicate tests into fewer parameterized tests
- Remove test fixtures that become unused after test deletion

**What you CANNOT do:**
- Modify any source files in `src/`. They are read-only.
- Modify `auto/run.sh` or anything in `auto/`. The measurement pipeline is sacred.
- Modify `tests/conftest.py` or `tests/stubs.py`. Shared infrastructure is locked.
- Install new packages or add dependencies.
- Delete tests that have unique coverage (>0 exclusive lines).

**The goal is simple: get the highest unique_coverage_lines.** In practice this means maintaining 460 while reducing test_count. If unique_coverage_lines drops below 460, revert immediately.

**Resource constraints**: Each iteration takes ~2.5 minutes (pytest + coverage run). Budget 3 minutes per experiment, timeout at 5 minutes.

**Simplicity criterion**: All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it. Conversely, removing something and getting equal or better results is a great outcome — that's a simplification win. When evaluating whether to keep a change, weigh the complexity cost against the improvement magnitude.

**The first run**: Your very first run should always be to establish the baseline, so run the command as-is without modifications.

## Output format

Run the experiment via the runner script:

```bash
./auto/run.sh > run.log 2>&1
```

The script runs tiered quality gates (pytest → ruff lint → coverage seed). If any gate fails, the script exits non-zero — treat this as a crash.

On success, the last lines of output contain structured metrics:

```bash
grep '^METRIC ' run.log
```

Expected output format:
```
METRIC unique_coverage_lines=460
METRIC test_count=368
METRIC total_coverage_lines=1694
METRIC zero_unique_tests=287
```

Parse the primary metric (unique_coverage_lines) from the `METRIC unique_coverage_lines=` line.
Track test_count, total_coverage_lines, and zero_unique_tests as secondary metrics — do not optimize for them, but log them for tradeoff monitoring.

## Logging results

When an experiment is done, log it to `results.tsv` (tab-separated, NOT comma-separated).

The TSV has a header row and 7 columns:

```
commit	unique_coverage_lines	test_count	total_coverage_lines	zero_unique_tests	status	description
```

1. git commit hash (short, 7 chars)
2. unique_coverage_lines achieved — use 0 for crashes
3. test_count
4. total_coverage_lines
5. zero_unique_tests
6. status: `keep`, `discard`, or `crash`
7. short text description of what this experiment tried

Example:

```
commit	unique_coverage_lines	test_count	total_coverage_lines	zero_unique_tests	status	description
7e5a11c	460	368	1694	287	keep	baseline
a1b2c3d	460	365	1694	284	keep	deleted 3 zero-unique tests from test_config.py
d4e5f6g	458	362	1690	282	discard	deleted test_forkhub_settings_all_defaults - lost 2 unique lines
```

## The experiment loop

The experiment runs on a dedicated branch (e.g. `autoloop/mar19`).

LOOP FOREVER:

1. Look at the git state: the current branch/commit we're on.
2. Read `results.tsv` and the Progress Log below. Explicitly state what you learned from past attempts before proposing a new change.
3. Run the coverage seed to find current zero-unique tests. Pick 1-3 from the same file to delete.
4. git commit the change.
5. Run the experiment: `./auto/run.sh > run.log 2>&1`
6. Extract the results: `grep '^METRIC ' run.log`
7. If the grep is empty or the command failed (non-zero exit), the run crashed. Run `tail -n 50 run.log` to read the error and attempt a fix. If you can't fix it after a few attempts, give up on this idea.
8. Record the results in results.tsv (do NOT commit results.tsv — leave it untracked by git).
9. If unique_coverage_lines stayed at 460 or higher (and test_count decreased), you "advance" the branch, keeping the git commit. Also update the Progress Log section below with a one-line entry.
10. If unique_coverage_lines dropped below 460, git reset back to where you started.

**Timeout**: Each experiment should take approximately 2.5 minutes. If a run exceeds 5 minutes, kill it and treat it as a failure (discard and revert).

**Crashes**: If a run crashes, use your judgment: If it's something simple to fix (typo, missing import), fix and re-run. If the idea is fundamentally broken, log "crash" and move on.

## Strategy guidance

Try these strategies to reduce test count while maintaining unique coverage:

**Phase 1: Delete zero-unique tests (lowest risk)**
- Run the coverage seed, find tests with 0 unique lines
- Delete 1-3 per iteration from the same test file
- Start with files that have the most zero-unique tests
- After deleting, verify no other tests broke (some tests may depend on side effects)

**Phase 2: Parameterize near-duplicates**
- Look for test methods that do nearly the same thing with different inputs
- Combine into a single `@pytest.mark.parametrize` test
- This reduces test_count while potentially maintaining or improving coverage

**Phase 3: Delete entire test classes**
- If all methods in a class are zero-unique, delete the whole class
- Clean up any fixtures that become orphaned

**When you plateau** (per-experiment test_count drop < 1):
- Re-read the coverage seed output for new angles
- Look at low-unique tests (1-5 exclusive lines) — can those lines be covered by expanding a nearby test?
- Consider combining test files that test overlapping functionality

**What NOT to do**:
- Don't delete tests that have unique coverage without first ensuring another test covers those lines
- Don't modify source code to make tests redundant
- Don't add new tests (the goal is reduction, not replacement)

## Baseline

- **Commit**: 7e5a11c (original, before any optimizations)
- **unique_coverage_lines**: 460
- **test_count**: 368
- **total_coverage_lines**: 1694
- **zero_unique_tests**: 287

## Progress Log

Append a one-line entry here for every **kept** experiment. This log is committed with the code so you always see it when reading program.md. Format: `- {commit}: {description} → unique_coverage_lines {value} (test_count {value})`

- cc64757: deleted TestDirectoryHelpers (4 tests) from test_config.py → unique_coverage_lines 463 (test_count 364)
- a17003e: deleted TestGetDbPath (4 tests) from test_config.py → unique_coverage_lines 463 (test_count 360)
- c13fc3c: deleted TestDefaultValues + TestPartialToml (3 tests) from test_config.py → unique_coverage_lines 463 (test_count 357)
- 0333e22: deleted TestCosineDistance+TestShouldCluster+TestGenerateClusterLabel (14 tests) from test_clusters.py → unique_coverage_lines 463 (test_count 343)
- f3aa9e0: deleted TestEmbeddingGeneration+TestGetClusters+3 from TestClusterFormation (8 tests) from test_clusters.py → unique_coverage_lines 586 (test_count 335)
- 5dd9125: deleted TestClusterCRUD+TestDigestCRUD+TestSyncState+TestAnnotationsCRUD (14 tests) from test_database.py → unique_coverage_lines 590 (test_count 321)
- 4e05490: deleted TestTrackedRepoCRUD+TestForkCRUD+5 from TestConnection (24 tests) from test_database.py → unique_coverage_lines 598 (test_count 292)
- df2de54: deleted 3 zero-unique from TestSignalCRUD in test_database.py → unique_coverage_lines 598 (test_count 289)
- fa8fa72: deleted 11 zero-unique tests from test_console_backend.py → unique_coverage_lines 617 (test_count 278)
- d459b72: deleted 17 zero-unique tests from test_digest.py → unique_coverage_lines 626 (test_count 261)
- 201ba87: deleted 21 zero-unique tests from test_embeddings.py and test_agent_hooks.py → unique_coverage_lines 647 (test_count 239)
- 998793f: deleted 19 zero-unique tests from test_agent_runner.py → unique_coverage_lines 658 (test_count 219)
- c307cc4: deleted 24 remaining zero-unique tests from test_config.py → unique_coverage_lines 660 (test_count 195)
- 1e61fbf: deleted 17 zero-unique tests from test_forkhub_api.py and test_agent_tools.py → unique_coverage_lines 672 (test_count 178)
- f902c82: deleted 12 zero-unique tests from test_cli.py → unique_coverage_lines 745 (test_count 166)
- 1c89ec8: deleted 80 zero-unique tests across models+github_provider+sync+tracker+integration → unique_coverage_lines 850 (test_count 83)
- b8e22ef: deleted last zero-unique test (test_track_raises_on_duplicate) → unique_coverage_lines 851 (test_count 82)
- 1abd6e6: combined exclude/include noop tests in test_tracker.py → unique_coverage_lines 851 (test_count 81)
- efbdf1f: combined 4 untracked-repo validation tests into 1 in test_forkhub_api.py → unique_coverage_lines 851 (test_count 78)
- 70981a9: combined 3 fork-not-found tests into 1 in test_agent_tools.py → unique_coverage_lines 851 (test_count 76)
- e0dd333: combined near-duplicate tests in test_config.py and test_digest.py → unique_coverage_lines 851 (test_count 73)

## NEVER STOP

Once the experiment loop has begun (after the initial setup), do NOT pause to ask the human if you should continue. Do NOT ask "should I keep going?" or "is this a good stopping point?". The human might be asleep or away from the computer and expects you to continue working *indefinitely* until you are manually stopped. You are autonomous. If you run out of ideas, think harder — re-read the context files for new angles, try combining previous near-misses, try more radical changes, search for patterns in what worked vs what didn't in results.tsv and the Progress Log. The loop runs until the human interrupts you, period.

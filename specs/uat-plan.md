# ForkHub CLI User Acceptance Test Plan

**Goal**: run the real CLI against real GitHub data, exercising every common
command, and verify observed behavior matches the documented contracts
(spec.md §16, README, --help text). This doubles as the first data feed for
the forkhub-dvi measurement harness.

## Ground rules

- **Isolation**: never touch the real `~/.local/share/forkhub/forkhub.db` or
  `~/.config/forkhub/`. Every command runs with:
  - `FORKHUB_DATABASE_PATH=/tmp/forkhub-uat/forkhub.db`
  - a scratch `forkhub.toml` in `/tmp/forkhub-uat/` (cwd-local config wins)
- **Backfill mutates a git repo**: all backfill commands run inside a scratch
  clone under `/tmp/forkhub-uat/target-repo/` — never this workspace.
- **Honest scoring**: each step has an expected outcome written BEFORE running.
  A mismatch is a finding (bead), not a reason to bend the expectation.
- **Budget**: Tier 3 makes real Anthropic API calls. Capped via
  `analysis_budget_usd` in the scratch TOML; do not exceed without approval.

## Tier 0 — Offline smoke (no network, no credentials)

| # | Command | Expected |
|---|---------|----------|
| 0.1 | `forkhub --help` | 13 commands + backfill subapp listed, exit 0 |
| 0.2 | `forkhub backfill --help` | run + 9 primitives listed, exit 0 |
| 0.3 | `forkhub config show` | scratch TOML values + env overrides displayed; secrets masked |
| 0.4 | `forkhub repos` (empty DB) | graceful empty-state, exit 0 |
| 0.5 | `forkhub backfill list` (empty DB) | graceful empty-state, exit 0 |
| 0.6 | `forkhub backfill status nonexistent-id` | clear not-found error, nonzero exit |

## Tier 1 — GitHub read-only (GITHUB_TOKEN, no Anthropic)

Target repo: DECISION — small repo with a real fork constellation (~10-100
forks, some ahead of upstream).

| # | Command | Expected |
|---|---------|----------|
| 1.1 | `forkhub track <owner/repo>` | repo + forks discovered and stored; count plausible vs GitHub UI |
| 1.2 | `forkhub repos` | tracked repo listed with fork count |
| 1.3 | `forkhub forks <owner/repo>` | fork table; ahead/behind/stars populated; head_sha stored (verify in DB — ntr depends on it) |
| 1.4 | `forkhub inspect <fork>` | detail view renders |
| 1.5 | `forkhub sync` (no Anthropic auth in scratch config) | discovery+compare run; analyzer skipped GRACEFULLY with the documented log message; no crash; exit 0 |
| 1.6 | `forkhub exclude` / `include` / `untrack` round-trip | state changes visible in `repos`; untrack removes data |
| 1.7 | rate-limit sanity | second `sync` uses ETag caching (no rate-limit collapse) |

## Tier 2 — Deterministic backfill on real data (the epic's core)

Setup: scratch clone of the tracked repo at its upstream default branch;
seed one signal row in the UAT DB pointing at a REAL divergent fork + the
real files it changed (manual SQL/Python seed — analysis hasn't run in this
tier). Pick the fork during Tier 1.3 (one a few commits ahead with a small
textual change).

| # | Command | Expected |
|---|---------|----------|
| 2.1 | `forkhub backfill candidates --repo <repo>` | seeded signal listed with significance |
| 2.2 | `forkhub backfill apply <signal> --dry-run --json` | PENDING, exit 0, no branch created |
| 2.3 | `forkhub backfill apply <signal> --json` | real outcome: ACCEPTED (exit 0) / TESTS_FAILED (1) / CONFLICT (2); diff fetched against fork **head_sha** (verify via debug log); branch `backfill/<cat>/<owner>-<sig8>` exists; on conflict: tree clean after reset |
| 2.4 | `forkhub backfill list` / `status <attempt>` | attempt visible, status + score correct, created_at = real creation time |
| 2.5 | re-run 2.3 same signal | CONFLICT exit 2 "branch already exists" (collision contract) |
| 2.6 | `forkhub backfill read-failures` (on candidate branch, if tests failed) | failing test files + contents emitted as JSON |
| 2.7 | `forkhub backfill run-tests` | exit mirrors suite result |
| 2.8 | `forkhub backfill write-test tests/test_uat_probe.py --content ...` | file written; then attempt `write-test src/x.py` → REJECTED (safety gate) |
| 2.9 | `forkhub backfill record <attempt> --status rejected --notes uat` | status updated; `--score 5` → validation error (0.0-1.0) |
| 2.10 | `forkhub backfill cleanup <attempt>` | back on original branch, candidate branch deleted |
| 2.11 | partial-fetch probe: seed signal with one bogus filename | PATCH_FAILED exit 3, error names the file ("Partial fetch") |

## Tier 3 — Live agent analysis (REAL COST — needs approval)

| # | Command | Expected |
|---|---------|----------|
| 3.1 | `forkhub sync --repo <repo>` with CLAUDE_ACCESS_TOKEN + `analysis_budget_usd` cap in scratch TOML | agent session runs; signals stored with categories/significance; cost within budget |
| 3.2 | `forkhub clusters <repo>` | clusters listed if similar signals exist (or graceful empty) |
| 3.3 | `forkhub digest --dry-run` then real | digest composed from signals, delivered to console backend |
| 3.4 | `forkhub backfill run --repo <repo> --dry-run` then real | the full deterministic loop on agent-generated signals → **first dvi hit-rate data points** |

## Recording

- Results table appended to this file as each tier completes
  (command, expected, observed, PASS/FAIL, notes).
- Every FAIL → a bead with `discovered-from:<uat-bead>`.
- Tier 3 outcomes additionally logged against specs/backfill-ai-decision.md.

## Results

### Tier 0 — 2026-06-07
| # | Observed | Verdict |
|---|----------|---------|
| 0.1 | `--help` exit 0, all commands listed | PASS |
| 0.2 | `backfill --help` exit 0, run + primitives listed | PASS |
| 0.3 | Scratch TOML honored (DB path, $1.00 cap), secrets masked | PASS |
| 0.4 | Empty `repos` → friendly hint, exit 0 | PASS |
| 0.5 | Empty `backfill list` → friendly message, exit 0 | PASS |
| 0.6 | `backfill status <missing>` → clear error, exit 1 | PASS (initial FAIL was harness error — see lesson below; forkhub-m1m closed as false finding) |

**Harness lesson**: never read `$?` after piping through `tail`/`head` — it
returns the pipe tail's exit, not the CLI's. Redirect to a file and check the
command's own exit code. One false bead (m1m) filed and retracted from this.

### Tier 1 — 2026-06-07 (target: bchao1/bullet, 115 forks discovered)
| # | Observed | Verdict |
|---|----------|---------|
| 1.1 | track registers repo (fork discovery deferred to sync — `track --help` slightly oversells) | PASS, minor wording note |
| 1.2 | repos table renders | PASS |
| 1.3 | forks table renders BUT ahead/behind=0 for forks known to be 2 and 93 ahead; vitality "dead" for an active fork | **FAIL → forkhub-9ey** |
| 1.4 | inspect renders BUT `HEAD SHA: -` | **FAIL → forkhub-p18** |
| 1.5 | degraded sync: 115 forks, 0 signals, exit 0, no crash. Caveat: analyzer path unreached (0 "changed"); skip-message invisible (corroborates forkhub-uox) | PASS w/ caveat |
| 1.7 | second sync: no rate-limit issues; also proved compare-starvation persists | PASS |
| 1.6 | exclude/include deferred; untrack deferred to end of UAT (destructive) | PENDING |

**Findings**: forkhub-p18 (GitHubProvider lacks get_head_sha — head_sha never
populated in production; ntr pinning never engages), forkhub-9ey (vitality
gate starves compare on dormant-upstream constellations → no signals ever —
the product's canonical use case yields zero end-to-end).

### Tier 2 — 2026-06-07 (scratch clone + seeded signal: chroma-core Windows patch)
| # | Observed | Verdict |
|---|----------|---------|
| 2.1 | seeded signal ranked as candidate | PASS |
| 2.2 | dry-run: PENDING, exit 0, 3 real diffs fetched, no branch | PASS |
| 2.3 | **real apply: ACCEPTED, score 1.0, exit 0** — diffstat matches live GitHub compare exactly (3 files, 274 changes), 11 Windows-API refs on branch, caller back on master, clean tree | **PASS — epic core works on live data** |
| 2.4 | list/status show both attempts correctly | PASS |
| 2.5 | re-apply same signal: CONFLICT, exit 2, remediation hint | PASS |
| 2.6 | read-failures: no-failure case implicit via 2.7 (failing-files parse path is unit-covered) | PASS (narrow) |
| 2.7 | run-tests on candidate branch: exit mirrors suite (0) | PASS |
| 2.8 | write-test: valid path written; production path REJECTED exit 1, file not created | PASS (safety gate holds) |
| 2.9 | record: score 5 rejected ("must be between 0.0 and 1.0", exit 2); valid record exit 0 | PASS |
| 2.10 | cleanup without --repo-path: correct partial-success warning + exit 2; with it: branch deleted, master restored, exit 0 | PASS (incl. misuse handling) |
| 2.11a | all-bogus files → "No applicable diffs", exit 2 (terminal) | PASS |
| 2.11b | 404 fork (deleted-fork scenario) → **unhandled GitHubProviderError traceback, exit 1 (collides with tests_failed)** | **FAIL → forkhub-cml** |

### Fix wave — 2026-06-08 (unblocking Tier 3)
- forkhub-p18 + forkhub-9ey fixed (58beb0f): real get_head_sha + compare-all-
  on-first-discovery. **Live-verified**: catch-up baselined 113 forks, data
  now matches the API (rebullet 93 ahead, chroma-core 2, danner26 32);
  steady-state re-sync ~zero extra calls. One follow-up filed: forkhub-zaa
  (unbounded baseline retry pins a fork to the analyzer on persistent SHA-
  fetch failure).
- forkhub-cml fixed (f116ce3): ProviderError hierarchy; the 404 deleted-fork
  probe now returns PATCH_FAILED/exit 3 instead of an unhandled traceback.

### Tier 3 — 2026-06-08 (live agent analysis, $1.00 cap)
The agent layer **works**; signal *storage* is broken. Diagnosed via an
instrumented session probe rather than guesswork.
| # | Observed | Verdict |
|---|----------|---------|
| 3.1 | sync invokes the agent; it reads fork summary, fetches all 3 diffs, classifies 4 signals correctly | PASS (agent reasoning sound) |
| — | every `store_signal` call fails server-side validation; agent retried 16× across 17 turns / $0.56, then gave up; **0 signals stored** | **FAIL → forkhub-flk** |
| 3.2-3.4 | clusters/digest/backfill-run blocked — no signals to operate on | BLOCKED on flk |

**Root cause (forkhub-flk)**: `store_signal`'s `@tool` schema declares
`files_involved` as python `list`, but the claude-agent-sdk simple-schema
mapper has no list branch and renders it as JSON `string`. The model can
never satisfy the contract. Unit tests missed it (they call the handler with
a real list, bypassing SDK schema rendering) — the recurring "stubs hide the
real path" theme.

**Token detour** (two real bugs found en route): forkhub-sqw (empty
GITHUB_TOKEN sends a malformed `token ` header instead of degrading to
unauthenticated), forkhub-9mv (dotenv only loads from cwd). The whole UAT
ran unauthenticated until Tier 3 because `.env` wasn't in the scratch cwd.

**Process notes**: one false finding (forkhub-m1m) from reading `$?` after a
pipe — retracted. forkhub-uox corroborated three times (agent session
failures all invisible in the CLI summary). forkhub-3pj filed (agent can't
run inside a Claude Code session without `env -u CLAUDECODE`).

### Observability harness — 2026-06-08
Lite harness installed (Vector→JSONL) to make agent-path debugging cheap
(see forkhub-r1d for call-site wiring). Transport verified end-to-end;
ports reassigned to 4418/4417/8688 to coexist with another project's harness.

### Tier 3 completion — 2026-06-08 (after forkhub-flk fix, ec42e5a)
The full pipeline works end-to-end on live data.
| # | Observed | Verdict |
|---|----------|---------|
| 3.1 | sync → agent classified + **stored 8 signals** (Windows support, BulletPrompt rebrand, test suite, nav keys, CI/CD, prompt_color, Ctrl+C fix, ruff reformat) with sensible significance scores | PASS |
| 3.2 | clusters → graceful empty (only 2 forks, dissimilar changes → nothing to cluster) | PASS |
| 3.3 | digest --dry-run → composed a real digest from 7 above-threshold signals via the digest-writer agent | PASS (cosmetic: repo UUID not full_name → forkhub-dom) |
| 3.4 | backfill run --dry-run → evaluated all 7 candidates (PENDING, dry-run) | PASS |

**Net**: GitHub → agent classification → stored signals → digest + backfill
candidate evaluation, all proven on a real fork constellation.

### dvi baseline — next deliberate step
A real (non-dry-run) `backfill run --repo bchao1/bullet --repo-path <clone>
--test-command "python3 -c 'import bullet'"` over these 7 agent signals would
produce the first measured deterministic hit-rate for forkhub-dvi. Deferred
with the dvi decision itself (La Boeuf's call). Tier 2 already gave one data
point: 1 signal → ACCEPTED.

## UAT outcome summary
Deterministic core (the epic) validated live; full agent pipeline validated
live after fixing one P1 blocker. Bugs surfaced — flk, p18, 9ey, cml (fixed);
zaa, sqw, 9mv, 3pj, dom (open); r1d, a8p (follow-up tasks). One false finding
(m1m) retracted. The recurring theme across every bug: **stubs/test doubles
hid the real-provider path** — exactly what a live UAT exists to catch.

## Decisions (resolved 2026-06-07)

1. **Target repo**: scouted by Claude, confirmed by La Boeuf before tracking.
2. **Tier 3**: APPROVED, analysis_budget_usd capped at $1.00 total.
3. **Auto-fix-tests**: deferred to dvi measurement runs (NEEDS_REVIEW path is
   mutation-tested at unit level; staging it live is expensive and flaky).

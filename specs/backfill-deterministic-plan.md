# Backfill Deterministic Path — Execution Plan

**Branch**: `feature/backfill-deterministic` (off main)
**Coordination**: sequential waves on shared branch (5 of 6 tasks touch
`services/backfill.py`, with overlapping regions — parallel worktrees would
conflict).

Historical note: This was formerly tracked as epic forkhub-14u.

## Context

The epic's direction: prove a completely non-AI deterministic backfill
(apply fork changes + run tests) before deciding whether an AI layer is
justified. The critical blocker (headerless patches) and its regression test
already landed in PR #10.

## Waves

### Wave 1 — mechanical, well-specified (build now)

1. **Quarantine dead AI layer** (P1 chore).
   - Delete `BACKFILL_EVALUATOR_PROMPT` (prompts.py:110-143; zero references,
     verified by grep).
   - Reword `BackfillService` class docstring + ABOUTME: the loop is
     mechanical rank→apply→test, not "agentic". The optional AI test-fixer
     stays isolated behind `--auto-fix-tests`.
2. **`git apply --3way` + partial-fetch semantics** (P1).
   - `_apply_and_test`: use `--3way` (with index) so context drift either
     resolves or produces real conflict markers → CONFLICT status.
   - `apply_signal:286-305`: fetch failures currently warn-and-drop, then
     proceed with a partial patch set. Switch to all-or-nothing: any fetch
     failure → PATCH_FAILED with explicit "partial fetch" error naming the
     failed files. Transient-failure burn (has_backfill_for_signal skip) is
     noted in the epic; revisit after dvi.
   - Test requirement: construct REAL context drift in a tmp_path repo
     (mutate the local file so plain apply fails and --3way resolves);
     asserting the flag is passed proves nothing.
3. **Cluster ranking + dedup** (P2).
   - New DB query for cluster membership of signals (cluster_members table
     exists; no read path for "which cluster is signal X in").
   - `gather_candidates`: rank cluster-corroborated signals higher
     (sort key: cluster-membership, then -significance, then created_at);
     dedup so N forks making the same change (= same cluster) yield one
     attempt (keep highest-significance member).
   - Makes the docstring claim at :171-177 true instead of deleting it.

### Wave 2 — blocked on decisions (see below)

4. **Guard auto-fix-tests** (P1): DECISION 1.
5. **Scope diffs to signal's change** (P2): DECISION 2.

### Wave 3 — after behavior settles

6. **Document backfill in spec.md** (P2): data model, deterministic
   flow, exit-code contract at cli/backfill_cmd.py:512, external-agent
   primitives.
7. **Decision framework doc + measurement harness spec**.
   NOTE: a measured hit-rate requires running backfill against real
   repos/signals — cannot be produced in this session. Prep the framework,
   do not fabricate numbers.

## Decision 1: what happens when acceptance required editing tests?

Today: test-fixer succeeds → status ACCEPTED, score 0.8. This edits the
oracle to match the change. Options:

- **a) NEEDS_REVIEW status (new BackfillStatus member)** — patch+test-edits
  stay on the candidate branch, attempt marked for human review, never
  auto-accepted. Honest middle ground.
- **b) Hard reject** — test-edit success is treated as TESTS_FAILED;
  auto-fix becomes purely advisory (edits left on branch).
- **c) Keep ACCEPTED but flag** — score stays 0.8 + explicit
  `tests_were_edited` marker; weakest guard.

All options include: CLI help for `--auto-fix-tests` states the risk
explicitly.

## Decision 2: how to scope diffs?

`Signal` carries no commit data — "the signal's commit range" does not exist
in the data model. Options:

- **a) Pin to fork head_sha** (cheap, in-scope): use `fork_row["head_sha"]`
  as the head ref instead of the floating default-branch name. Stops drift
  between analysis time and backfill time; still whole-divergence per file.
- **b) True per-commit scoping** (mini-epic): capture commit SHAs on the
  signal at analysis time → models.py + signals schema + store_signal tool +
  analyzer prompt + backfill. Cross-layer; overlaps with analyzer decoupling
  ([#32](https://github.com/JoshuaOliphant/forkhub/issues/32)). Should be
  its own designed issue chain. See also [#35](https://github.com/JoshuaOliphant/forkhub/issues/35).
- **c) Defer** behind the deterministic-core proof (dvi baseline first).

## Verification

Per task: TDD (red first), `uv run pytest --cov=src/forkhub -m "not
integration and not slow"` must end at 100%, ruff clean, ty no new
diagnostics. Validator sweep at the end against each task's acceptance
criteria, then PR.

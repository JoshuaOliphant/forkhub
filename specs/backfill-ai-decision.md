# Backfill AI Layer: Go/No-Go Decision Framework (forkhub-dvi)

**Status**: prep for La Boeuf's decision — DO NOT decide here.
**Blocked by**: deterministic path landing (forkhub-1u6, ntr, slh, 2oc).

## The question

After the deterministic cherry-pick path is correct and proven, does an AI
evaluation/repair layer add enough value to justify its cost and risk?

## What "proven" means (the baseline to measure first)

An honest hit-rate for the pure-deterministic path. **This cannot be
fabricated** — it requires running backfill against real tracked repos with
real signals. No number in this document is a measurement.

### Measurement harness (to run before deciding)

1. Track 2-3 real repos with active fork constellations (e.g. repos already
   in the maintainer's orbit). Run `forkhub sync` until signals accumulate.
2. Run `forkhub backfill run --dry-run` then live against the candidates.
3. Capture per-attempt outcomes from `backfill_attempts` (the trace table
   already records everything needed):
   - `applied_cleanly`: ACCEPTED on first apply (tests green, no fixing)
   - `conflict`: CONFLICT after `--3way`
   - `tests_failed`: applied but suite red
   - `partial/infra`: PATCH_FAILED (fetch issues etc.)
4. The headline metric: **deterministic hit-rate** = ACCEPTED / attempted.
   Secondary: conflict rate, tests-failed rate, and a manual-review sample
   of ACCEPTED attempts (are they actually good changes?).

Suggested capture window: ≥20 attempts across ≥2 repos before deciding.

## Candidate AI roles (if GO)

Ranked by expected value, with the risk each carries:

| Role | Value hypothesis | Risk |
|------|------------------|------|
| (a) Pre-apply candidate scoring (the original BACKFILL_EVALUATOR_PROMPT intent: value/quality/security of a candidate before applying) | Saves wasted apply/test cycles on junk candidates; adds a quality screen ranking can't express | Cost per candidate; false negatives screen out good changes; judgment is opaque |
| (b) Repairing the fork's **production** code conflicts (resolve `--3way` conflict markers in the imported change — never touching upstream tests) | Converts CONFLICT outcomes into candidates; conflicts are expected to be a large outcome bucket | Semantic mistakes in conflict resolution land in production code; needs strong test gate after |
| (c) Test-fixer (exists today behind `auto_fix_tests`, gated to NEEDS_REVIEW per forkhub-2oc) | Already built; surfaces "tests need updating for valid new behavior" cases for human review | Known oracle-editing hazard — permanently constrained to never auto-accept |

## Decision criteria (proposed)

- **NO-GO** if deterministic hit-rate is already high (most valuable signals
  apply cleanly): the AI layer optimizes a non-problem. Keep (c) as-is.
- **GO for (b)** if CONFLICT is the dominant failure bucket AND a sampled
  review shows the conflicts are mechanical (drifted context, renames)
  rather than semantic divergence.
- **GO for (a)** only if manual review of ACCEPTED attempts shows a
  meaningful fraction are low-value (passing tests but not worth a PR) —
  i.e. the test suite alone is too weak an acceptance oracle.
- Whatever the decision: budget caps (`max_budget_usd` pattern from the
  analyzer) and the TestFixer-style Protocol isolation are preconditions
  for any AI role.

## Inputs available at decision time

- `backfill_attempts` trace table (status/score/error/test_output per attempt)
- `forkhub backfill status` CLI for aggregate counts
- This branch's outcomes: NEEDS_REVIEW bucket size once 2oc lands

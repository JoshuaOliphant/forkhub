# Workflow state planning — 2026-11-13

La Boeuf requested a plan to make the highest-risk implicit machines explicit,
repair transition defects, and turn the state knowledge into product improvements.
He selected explicit transitions with restart tests, bounded safe retries with
manual reconciliation of uncertain effects, and shared CLI/MCP status.

The earlier audit used main at 47d255c. Remote main had advanced to f6e9872:
immutable signal evidence and release preparation were already merged. The current
roadmap #63 also superseded the old ChatGPT-first sequencing with coordinated
website and ChatGPT slices. Planning against the stale checkout would have
duplicated provenance work and followed the wrong interface priority.

Created an isolated documentation worktree. Current-head targeted baseline:
294 passed, 1 deselected in 3.74 seconds. No application source changed, no
operational database was opened for writing, and no deploy or notification ran.

The highest-risk extra ownership finding: a collision attempt records the name
of a branch it never created, while cleanup accepts existence as ownership.
The spec separates ownership, phase, outcome, test evidence and human decision.
Uncertain Git effects require inspection/reconciliation rather than timer-based
automatic reclaim. A crash probe against a disposable database also demonstrated
that committed embeddings can strand unfinished clustering.

A fresh builder found missing reconciliation authority, cleanup defaults,
post-mutation retry eligibility, the meaning of successful application, and hosted
status scope. The draft now records conservative defaults explicitly: preserve
caller cleanup defaults subject to proof, require deliberate post-mutation retry,
never equate green tests with human acceptance, and stage owner-scoped exports
separately from local backfill status.

Knowledge retrieval found the cross-project lesson that recovery must consume
actual crash artifacts, ForkHub's shared-fixture/test-sprawl constraints, and agent
file-edit containment safeguards. The critical-pattern warning about quiet green
signals became direct persisted-state and interruption checks. Semantic search
could not run because the vault has no recommendation index.

The classification helper initially reported unavailable credentials from the
noninteractive shell. Existing project knowledge correctly pointed to the
interactive-shell environment; classification and criterion checks then ran
without reading or printing credentials. Architectural classification: 0.65.

Automation opportunity: drive transition/restart boundary regression checks from
the accepted criteria through the existing acceptance cache and verifier. Do not
add another workflow engine or a separate test-fixture family.

Planning output is proposed, not an implementation pass. Existing baseline tests
do not satisfy the new acceptance criteria. Production schema/data rollout and
build approval remain separate.

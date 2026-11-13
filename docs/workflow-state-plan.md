# Explicit workflow states and recoverable transitions

Status: proposed planning package, 2026-11-13. No implementation or production change authorized by this document.
Baseline: main at f6e9872. Parent roadmap: [#63](https://github.com/JoshuaOliphant/forkhub/issues/63).
Tracker: [workflow plan #71](https://github.com/JoshuaOliphant/forkhub/issues/71); first full specification: [safe backfill #72](https://github.com/JoshuaOliphant/forkhub/issues/72).

## Clarifications

> Make a plan to turn the highest-risk implicit state machines into explicit ones and fix the transition bugs you found. Think about how to use the knowledge of these state machines into application improvements.

- Planning only; application code, operational databases, deployments, and notifications remain outside this task.
- Current roadmap #63 supersedes the older ChatGPT-first sequencing: website and ChatGPT consume shared core contracts in coordinated vertical slices.
- Signal evidence capture already exists. Extend it; do not reconstruct it from today's mutable branch or build another provenance system.
- Confirmed: explicit transition rules and interruption/restart verification without a workflow engine.
- Confirmed: bounded retries for safe backend work; uncertain Git changes and delivery require operator reconciliation.
- Confirmed: expose shared workflow status and next actions through CLI and MCP; website consumes the same status under roadmap #63.
- Assumed: preserve the existing optional analyzer and configured spend limits; add no model provider, daemon, or scheduler.
- Assumed: historical records with insufficient evidence remain explicitly unknown and are not automatically replayed or cleaned up.
- Assumed after builder review: backfill retains its caller-specific cleanup defaults subject to ownership proof; post-mutation failures require explicit retry, and interrupted ownership has a local inspect/reconcile path.
- Assumed after builder review: local workflow status accompanies each repair; sanitized exported status and full website/MCP parity arrive in the shared-status specification. Until a workflow is exported, hosted readers report unavailable rather than infer zero work.

## Deeper ask

- **A professional would also:** define ownership, allowed transitions, interruption recovery, and completion evidence before assigning status names.
- **Rawest material:** current service write paths, stored records, real Git state, existing fixtures/tests, merged provenance work, and roadmap #63.
- **Methods and tools:** small typed transition policies, SQLite atomic claims and completion updates, existing pytest fixtures, temporary real Git repositories, and failure injection at side-effect boundaries.
- **Independent check:** terminate a workflow at each boundary, reopen its database, retry or reconcile, and inspect actual persisted results, branches, and matching public responses.

## Problem

- Metadata checkpoints can hide unfinished comparisons or analysis.
- Backfill eligibility confuses preview, execution, and any prior attempt; branch names are treated as ownership.
- Embeddings can be saved while clustering remains unfinished; delivery timestamps can claim success without successful delivery.
- Connection existence can falsely establish database readiness.
- A successful cache response does not tell the user whether useful work completed.

## Approaches considered

| Approach | Benefit | Cost and decision |
|---|---|---|
| Separate typed transition policies in existing services, durable state where recovery needs it | Makes invalid combinations and recovery visible; uses the current stack | Recommended. Requires focused schema and contract changes, implemented one workflow at a time |
| Add enums around existing fields only | Small initial diff | Reject: preserves lost work, false completion, and unsafe ownership assumptions |
| Introduce a generic workflow engine or event store | General scheduling and orchestration | Reject: introduces a subsystem beyond the correctness repairs and product scope |

Use separate facts for phase, outcome, reason, and ownership. Do not flatten all combinations into one universal status enum. Each transition has an allowed source state, event, guard, persisted result, and observable failure. Network calls and Git actions stay outside database transactions.

## Ordered specifications

These are independent specifications, not one giant implementation issue. Each must carry its own acceptance criteria and implementation PR. The first full specification is [safe backfill attempts](specs/safe-backfill-attempts.md).

| Order | Specification | Concrete deliverable | Depends on |
|---|---|---|---|
| 1 | Database readiness | Publish a connection only after initialization; close and clear it after any initialization failure; reset vector capability on close | None |
| 2 | Safe backfill attempts | Preview without consuming eligibility; persist attempts before Git effects; prove branch ownership; validate outcome changes; explicit cleanup state | 1 |
| 3 | Durable comparison and analysis | Separate observed revisions, successfully compared revisions, and completed analysis; retain pending work independently of discovery hints | 1; existing evidence contracts |
| 4 | Recoverable clustering | Independent processing checkpoint; transactionally publish cluster membership, counts, and completion | 1 |
| 5 | Honest digest delivery | Per-destination delivery outcomes, truthful aggregate status, safe retry and unknown-outcome handling | 1 |
| 6 | Shared workflow status | Explain coverage, available analysis, pending/blocked work, freshness, and next action in website/CLI/MCP | Incremental with 2–5; current relationship/evidence contracts |

Prioritize the first backfill safety fix and the lost-comparison fix before broader workflow recovery. Orders 4 and 5 may proceed independently after readiness. Local status accompanies each completed workflow. Shared owner-scoped exports and website/MCP parity are delivered in order 6, incrementally as each workflow becomes exportable; unsupported local state is explicitly unavailable in hosted responses.

## Specification briefs and acceptance criteria

### A. Database readiness

As a library caller, I want a failed initialization to leave a reusable disconnected object, so that retry cannot use a half-initialized connection.

**State model:** disconnected → initializing → ready → disconnected. Initialization failure returns to disconnected. Vector capability belongs to the current ready connection only. Concurrent callers await the same initialization result; no partially initialized connection is exposed.

#### DB-AC-1: Ready connection
**Given** a disconnected database, **When** initialization succeeds, **Then** a repository inserted through that database is readable through its normal storage interface.

#### DB-AC-2: Failed initialization (outline)
**Given** initialization fails at `<boundary>`, **When** the caller retries after that fault is removed, **Then** storage operations succeed through a newly initialized connection, with no leaked failed connection.

| boundary |
|---|
| journal or foreign-key configuration |
| schema creation |
| migration |

Optional vector extension failure continues to yield a ready non-vector connection; it is not a database initialization failure.

#### DB-AC-3: Concurrent initialization
**Given** two callers connecting the same object, **When** initialization is in progress, **Then** neither can perform operations until readiness is established and only one connection is published.

#### DB-AC-4: Closed capabilities
**Given** a ready vector-enabled database, **When** it closes, **Then** operations report disconnected and vector capability is false.

#### DB-AC-5: Repeated connect
**Given** a ready database with an uncommitted transaction, **When** the same object is connected again, **Then** the existing connection and its transaction remain intact and no additional connection is opened.

### B. Durable comparison and analysis

As a developer monitoring forks, I want unfinished work retained independently of discovery, so that an API or analyzer failure does not silently lose a change.

**Responsibility units:** observation capture; revision comparison; analysis execution; atomic output publication; read-only progress projection. They use existing provider/analyzer seams and evidence validation. No shared job framework is required.

**State model:** pending → running → succeeded, retryable failure, or blocked. Explicit cancellation/interruption leaves recoverable work. Each claim has an owner and expiry; completion requires the current claim. Exhausted retries become blocked with a reason, not success.

**Identity and boundaries:** comparison work names stable repository identities and exact base/head SHAs. Analysis work additionally names the analysis revision. Signal evidence continues to name cited immutable commits and files. One comparison can produce several signals or a successful zero-signal result. Signal output belongs to its work item, not a wall-clock query window.

#### SYNC-AC-1: Successful empty analysis
**Given** captured immutable comparison work, **When** analysis succeeds without findings, **Then** its completion is recorded with zero findings and is distinguishable from never analyzed.

#### SYNC-AC-2: Retry after unchanged discovery (outline)
**Given** `<failure>` left a pending work item, its retry time has arrived, allowance remains, the fault is removed, and the push timestamp is unchanged, **When** backend processing runs again, **Then** the provider or analyzer receives that work item's recorded revisions and the item reaches succeeded without requiring a new push.

| failure |
|---|
| first comparison failed |
| comparison failed for a previously seen fork |
| analysis failed after comparison succeeded |

#### SYNC-AC-3: Immutable input
**Given** source or target branches move after work is captured, **When** the work executes, **Then** comparison and analysis read the recorded revisions and preserve matching evidence identity.

#### SYNC-AC-4: Atomic output and completion
**Given** analysis has produced outputs, **When** publication fails, **Then** no partial visible output set is treated as a completed analysis and retry does not duplicate published signals.

#### SYNC-AC-5: Claim ownership
**Given** two backend processes contend for one work item, **When** both try to claim it, **Then** only one owns it and a completion from an expired prior owner cannot replace the current result.

#### SYNC-AC-6: Partial batches
**Given** a batch contains successful and failed work items, **When** the batch finishes, **Then** successful work stays complete and failed work remains individually recoverable with its reason.

#### SYNC-AC-7: Retry limits and cost
**Given** a work item has reached its configured attempt or cumulative inference budget, **When** backend processing runs again, **Then** it remains blocked with the applicable limit and no further inference is invoked until an explicit retry decision changes its allowance.

#### SYNC-AC-8: Release discovery
**Given** more releases than one provider page, including equal publication timestamps, **When** discovery completes, **Then** every observed release revision is durably recorded before its discovery checkpoint advances, without duplicate work on repeated discovery.

**Release policy:** use provider release identity plus a content revision fingerprint; a metadata edit creates a distinct observed revision. A tag resolving to different content is a new revision, never an overwrite of earlier evidence. Complete pagination is required before a discovery checkpoint can claim coverage. Release discovery and release analysis have separate completion records.

**Scheduling policy proposed:** process pending work during existing backend invocations; no background process is introduced. Preserve existing per-run limits and configured baseline caps. At most three automatic attempts per work item, additionally constrained by the existing inference spend cap, with retry times one minute then five minutes after failures. Permanent input/authorization failures and exhausted limits become blocked. Unknown model-call completion counts toward consumed allowance; do not promise exactly-once inference billing.

**Upstream-only movement:** resolve upstream once per repository observation. A changed base creates bounded pending comparisons for known fork revisions, without one head request per unchanged fork. Apply the existing run budget; leave excess work pending. Analysis runs only for a comparison with changed analyzable evidence, not merely because the base SHA changed.

**Migration:** legacy sync timestamps and head SHAs do not prove successful analysis or comparison. Preserve legacy intelligence as unknown where needed. No automatic historical model reanalysis; an operator can request a bounded reconciliation using current immutable revisions. Reuse existing evidence; do not fabricate historical refs.

### C. Recoverable clustering

As a developer, I want grouping to finish after an interruption, so that embedded signals do not disappear from derived intelligence.

**State model:** embedding unavailable/available is separate from grouping pending/running/complete/failed. A completed singleton is valid. A newly pending signal compares with eligible existing signals, including completed singletons. Do not add algorithm-version machinery until an actual versioning requirement exists.

#### CLUSTER-AC-1: Preembedded input
**Given** a signal already has an embedding but grouping is pending, **When** clustering runs, **Then** it participates in grouping and receives a completion checkpoint even if it remains a singleton.

#### CLUSTER-AC-2: Interrupted publication (outline)
**Given** processing stops after `<boundary>`, **When** processing restarts against that saved database, **Then** cluster memberships and distinct-fork counts match an uninterrupted run with no duplicates.

| boundary |
|---|
| embedding persistence |
| cluster creation |
| first membership write |
| count update |

#### CLUSTER-AC-3: Concurrent processing
**Given** two processes see the same pending signals, **When** both process grouping, **Then** one canonical membership result is committed and counts do not double.

**Migration:** mark legacy signals as grouping pending, retain embeddings and existing membership evidence, and reconcile idempotently. Bounded runs remain pending until finished; no duplicate historical clusters are introduced. Malformed embeddings yield an explicit failed reason and do not poison unrelated signals.

### D. Honest digest delivery

As a developer receiving digests, I want successful, failed, and uncertain destinations distinguished, so that retry does not silently duplicate notifications or claim delivery that never occurred.

**State model:** per destination pending → sending → succeeded / failed / unknown. Aggregate state is not attempted, delivered, partial, failed, or unknown. No destinations means not attempted. Success requires confirmation from that destination, not loop completion. Destinations use stable configured identities, not display names alone.

#### DIGEST-AC-1: All destinations succeed
**Given** a generated digest with configured destinations, **When** every destination confirms delivery, **Then** the aggregate is delivered and successful timestamps are recorded.

#### DIGEST-AC-2: Outcome aggregation (outline)
**Given** a delivery cycle yields `<outcomes>`, **When** its aggregate is read, **Then** it reports `<aggregate>` without claiming unsuccessful destinations were delivered.

| outcomes | aggregate |
|---|---|
| no configured destinations | not attempted |
| all destinations failed definitively | failed |
| one success and one definite failure | partial |
| one success and one uncertain outcome | unknown, with the success retained |

#### DIGEST-AC-3: Retry only unsent work
**Given** some destinations succeeded and another definitely failed before sending, **When** a retry runs, **Then** successful destinations are not sent the digest again.

#### DIGEST-AC-4: Uncertain side effect
**Given** a recorded sending destination survived a process interruption and its backend cannot confirm receipt or deduplicate resend, **When** recovery runs, **Then** the destination status is unknown with next action manual reconciliation, and its backend send-call count does not increase.

**Delivery policy:** a future backend may automatically retry uncertain outcomes only with a demonstrated idempotency mechanism. Returned failure is automatically retryable only if the backend contract guarantees that nothing was delivered. Never claim exactly-once delivery from SQLite alone. Continue other independent destinations after one fails; preserve each result. Legacy aggregate timestamps remain historical claims with unknown per-destination confirmation.

### E. Shared workflow status

As a developer using ForkHub, I want to know what was checked and what I can do next, so that empty or stale results are useful rather than misleading.

**Contract:** return discovery coverage and latest attempt separately from successful analysis, pending/blocked counts, last successful completion, typed reason, and next action. Preserve evidence verification and interpretation limitations as separate dimensions. Aggregate views are derived from authoritative workflow records; there is no second UI status store.

#### STATUS-AC-1: Empty-result explanation (outline)
**Given** `<recorded situation>`, **When** matching results are requested, **Then** the explanation is `<meaning>`.

| recorded situation | meaning |
|---|---|
| legacy cache with no completion record | analysis history unknown |
| discovery complete, analysis pending | analysis pending |
| analysis blocked | analysis blocked, with reason and local next action |
| analysis succeeded with zero signals | analysis completed without findings for the recorded scope |
| signals exist but none match filters | no matching findings; existing findings excluded by filters |

#### STATUS-AC-2: Cross-interface parity
**Given** the same saved snapshot and workflow records, **When** website, CLI, local reader, and authenticated MCP are queried, **Then** their underlying status, timestamps, counts, evidence limitations, and available actions agree.

#### STATUS-AC-3: Reads stay reads
**Given** pending or blocked work, **When** any read-only status request is made, **Then** no scan, inference, Git mutation, delivery, or workflow transition occurs.

#### STATUS-AC-4: Honest freshness
**Given** discovery succeeded while analysis failed and older findings exist, **When** status is read, **Then** the discovery success and analysis failure are both visible and the older findings retain their original completion time.

**Actions:** retry safe pending/failed backend work locally; explain blocked access or limits; reconcile uncertain Git/delivery outcomes manually. Existing MCP tools remain read-only. Future hosted write controls require their own authorization design.

## Application improvements enabled by the states

- **Explain the empty feed:** distinguish unknown history, pending analysis, successful zero findings, and filters excluding existing findings.
- **Resume useful work:** process unfinished comparisons/analysis without rescanning every unchanged fork or rediscovering completed evidence.
- **Show an honest repository health summary:** last successful discovery, analysis backlog, blocked reasons, and stale-but-preserved intelligence.
- **Offer a review queue for backfill:** show test result, whether tests changed, candidate branch ownership/existence, and human decision independently.
- **Avoid duplicate alerts:** retain destination-level confirmation and make uncertain outcomes explicit.
- **Expose confidence correctly:** distinguish complete coverage, recent analysis, verified content, and unverified interpretation.

These improve the existing product. Recommendation ranking, pricing, model providers, webhook orchestration, new workers, and resurrecting the dormant constellation UI are separate work.

## Verification and release

- Extend existing fixtures and test classes; no parallel fixture families or mock mode.
- Use pure transition table tests for allowed and rejected events, plus integration tests across SQLite/Git/transport boundaries.
- Name each criterion in its issue-to-test mapping; update the existing acceptance cache only when real test nodes exist.
- Independent interruption tests reopen real temporary SQLite databases and inspect temporary Git refs and working trees. Cover completion-write failure, process death without finally, cancellation, and overlapping callers.
- Require 100% source statement coverage and pristine test output. Capture expected failures and assert their content.
- Run the repository verifier, including local Workers/D1, real-source acceptance, production import, and bundle checks when affected; document the first failing gate instead of treating compilation or a passing subset as release proof.
- For schema changes, test fresh and migrated disposable databases. Prepare a fresh dedicated hosted cache and pair reader code/schema during a separately approved rollout, with rollback. Planning never migrates the operational cache.
- No compatibility shims: replace internal callers together. Preserve historical facts through explicit migration, not competing legacy write paths.

## Measurement

During implementation, deterministic acceptance targets are zero lost pending work, zero duplicate published signals/memberships, zero false delivery confirmations, zero unowned branch mutations, and parity across status consumers.

After a separately approved rollout, inspect the first 20 backend runs or seven days, whichever is longer. Track pending age, retry counts, blocked reasons, reconciliation incidents, duplicate outputs, actual inference spend per completed item, and API calls per unchanged fork. Compare with a pre-change baseline on the same disposable observation set; do not claim cost or performance improvement without measurements. This is an observation plan, not a newly scheduled automation.

## Open decisions

None for planning. The user accepted the recovery-first approach, bounded safe retries with manual reconciliation of uncertain effects, and shared user-visible status. Individual implementation specifications receive their own review before build; implementation has not been requested.

## Evidence and source map

- Existing sync loss: `services/sync.py` advances observation fields before comparison and advances the repository timestamp after caught analysis failure; analysis completion is inferred from a returned list.
- Current evidence is implemented in `services/evidence.py`, `models.SignalEvidence`, signal storage, shared cache readers, and backfill. Reuse its immutable-content guarantees.
- Current backfill records branch names before collision checks and persists the normal attempt after Git effects. Cleanup checks existence but not ownership.
- Current clustering commits embeddings before deriving work from newly embedded IDs. A disposable SQLite interruption probe retained two embeddings; retry produced zero clusters where uninterrupted processing groups them.
- Current digest delivery timestamps aggregate completion without checking returned success. Current database connect assigns its connection before schema readiness.
- On f6e9872, targeted existing tests: 294 passed, 1 deselected in 3.74 seconds. This proves baseline behavior, not the unimplemented acceptance criteria above.
- Knowledge checked: shared critical patterns; crash recovery must consume leftover artifacts; ForkHub test-sprawl prevention; agent-file containment safeguards. Semantic search was unavailable because the vault has no recommendation index; keyword retrieval supplied these constraints.
- Planning must respect the updated roadmap #63 and existing evidence/release work #35/#68; an older local ADR is not the current interface sequencing decision.

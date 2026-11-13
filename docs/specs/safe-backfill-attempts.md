# Safe backfill attempts and explicit recovery

**Class:** architectural. Backfill execution, local Git ownership, persisted outcomes, and caller status must share explicit transition rules.

Status: proposed specification; implementation awaits approval. Part of the [workflow state plan](../workflow-state-plan.md).
Tracker: [specification #72](https://github.com/JoshuaOliphant/forkhub/issues/72), part of [plan #71](https://github.com/JoshuaOliphant/forkhub/issues/71).

## Clarifications

> Make a plan to turn the highest-risk implicit state machines into explicit ones and fix the transition bugs you found. Think about how to use the knowledge of these state machines into application improvements.

- Confirmed: explicit transitions and interruption/restart tests, without a workflow engine.
- Confirmed: bounded retries for safe backend work; uncertain Git or delivery effects require manual reconciliation.
- Confirmed: shared status explains pending work, failures, freshness, and next action in CLI/MCP; website shares the core contract under roadmap #63.
- This specification covers existing local backfill only. It adds no hosted write tools, autonomous adoption, merge, deployment, or notification.
- Assumed: automated tests establish a test result, not a human acceptance decision.
- Assumed: legacy records never acquire stronger ownership or completion evidence through migration.
- Assumed: safe automatic retries must fit existing limits; an uncertain local side effect stops for reconciliation.
- Assumed after builder review: retain current direct-call versus autonomous-run branch-retention defaults, but persist that cleanup policy before execution and apply it only to proven owned resources.
- Assumed after builder review: reconciled failures after Git mutation require explicit retry; a tests-passed or review-required retained candidate is not automatically applied again.
- Assumed after builder review: local status ships in this slice; sanitized owner-scoped export and cross-interface parity ship with the shared-status specification.

## Deeper ask

- **A professional would also:** distinguish execution, test evidence, human decisions, and ownership; define interruption behavior before resuming Git operations.
- **Rawest material:** persisted attempts, actual repository refs and working trees, current backfill transitions, and existing real-Git tests.
- **Methods and tools:** typed state transitions, guarded SQLite updates, explicit Git ownership records, and failure injection at persistence/Git boundaries.
- **Independent check:** process termination and restart against real temporary repositories/databases, comparing surviving refs and persisted facts with expected outcomes.

## Problem

- Preview writes currently suppress a later autonomous execution.
- A branch collision can record a branch that the attempt never created; cleanup has no ownership proof.
- Process death can leave Git effects without an attempt record or an exact restoration target.
- Arbitrary status changes and stale scores mix test outcomes with human acceptance.

## Overview

- A preview reports prospective changes without creating an execution attempt or changing eligibility.
- Persist execution identity and original repository state before the first Git mutation.
- Track execution phase, terminal outcome, test evidence, human review, and resource ownership separately.
- Mutations require proof that the attempt owns the affected resource and that its observed state matches expectations.
- Surface interrupted and cleanup-failed work with an explicit next action; never infer safety from a branch name.

## Approaches considered

| Approach | Trade-off |
|---|---|
| Typed transition policies with explicit attempt and branch records (recommended) | Uses existing services and SQLite; allows direct testing and conservative restart recovery; requires a schema and caller-contract migration |
| Retain one status plus branch name | Smaller initial change, but cannot represent ownership, test provenance, or interrupted effects safely |
| Generic workflow engine or event-sourced Git orchestration | Adds scheduling and operational machinery beyond this local workflow; does not make SQLite and Git atomic |

## Decisions

### Responsibilities and interfaces

- **Preview:** read existing signal/evidence and fetch necessary immutable content; return a preview result. It may use read-only provider calls but persists no execution or eligibility state.
- **Eligibility:** automatic runs select candidates with no execution history, or definitely failed pre-mutation fetches still inside their retry allowance. Active/interrupted work, finished tests-passed or review-required candidates, human rejection, and post-mutation failures are not automatically reapplied. An explicit retry can create a new attempt after reconciliation. Passing tests blocks automatic repetition but never claims integration into the original branch.
- **Execution:** own one attempt identity and execute its allowed phase transitions. A short atomic claim prevents concurrent active attempts for the same candidate and exclusive repository ownership prevents different candidates mutating one working tree simultaneously.
- **Git ownership:** record canonical repository identity, original named branch or detached commit, original HEAD, candidate branch, ownership attempt identity, and last confirmed candidate HEAD. Creation intent is not ownership proof.
- **Result publication:** persist the test run's revision, exit status, captured output, whether test files changed, terminal outcome, and cleanup state. Signal evidence is immutable input, not an execution success claim.
- **Review:** record a human accepted/rejected decision independently of execution and test evidence. Review does not itself merge changes or delete a branch.
- **Status:** project these records into the existing local library and CLI surfaces, with structured reasons and allowed next actions. This slice does not add backfill state to hosted exports. The separate shared-status specification adds sanitized owner-scoped summaries and parity; until then, hosted readers report local backfill status as unavailable, not zero pending. Never expose local paths or test output.
- **Reconciliation:** provide local inspect and reconcile operations. Inspection is read-only. A reconcile request supplies the attempt ID, expected attempt revision, operator decision, and reason; it re-reads actual repository state and conditionally records the result. Confirmed owned resources can become retained or removed using matching Git evidence. Uncertain resources cannot become owned from a name or operator assertion alone. The operator may abandon uncertain ownership after manually leaving a clean working tree and switching away from the candidate; record the resource as externally managed, prohibit its cleanup, and release the repository claim. Reconciliation itself never applies, resets, deletes, or adopts an unowned branch.

### State model

| Dimension | States |
|---|---|
| Execution phase | planned, fetching, ready, applying, testing, fixing tests, finished, interrupted |
| Terminal execution outcome | tests passed, review required after test edits, tests failed, patch failed, conflict, cancelled; absent before completion |
| Human decision | not reviewed, accepted, rejected |
| Candidate ownership | not created, creation uncertain, owned, ownership uncertain |
| Cleanup | not required, pending, retained, removed, failed, unknown |

Changing phase requires the current expected phase and attempt claim. Terminal execution facts cannot be overwritten by a review command. Repeating the same review decision is idempotent; changing a recorded decision requires an explicit replacement decision with a reason, retaining the previous decision as review history. A review cannot manufacture a test run or retain a stale numeric success score after test failure.

### Execution and recovery policy

- Persist planned state before external mutation. If persistence fails, do not begin Git operations.
- Fetch/validate before creating a candidate. Refuse a dirty initial working tree without resetting or stashing user changes.
- Candidate naming includes the full unique attempt identity. Record creation intent before creation and ownership only after successful creation and verified identity. A crash in that gap is creation uncertain and requires manual reconciliation.
- Restore the recorded starting named branch only if its ref still matches the recorded original HEAD; restore detached HEAD to its recorded commit. If the caller changed refs or working-tree state, stop with a recovery reason rather than overwrite it.
- Persist every completed phase and the expected Git revision. A crash without a trustworthy completion record is interrupted, not success.
- Retry provider fetching only before Git effects, with at most three attempts, retry delays of one minute then five minutes, and existing per-run limits. No automatic replay of applying, fixing tests, cleanup, or uncertain test subprocess completion.
- A failed prior attempt may be explicitly retried as a separate attempt after its resources are reconciled. Automatic retries are limited to definite pre-mutation fetch failures; reconciled test failures, patch failures, conflicts, and interrupted Git effects require a deliberate retry request. Finished tests-passed and review-required candidates remain excluded from automatic runs even if their branches are later removed.
- Test-fixer rounds remain capped at three. An edit or commit failure does not advance the round as a successful test run. Test-file containment guards remain in force. Tests passing after edits remains review required.
- Cleanup follows an explicit policy persisted at attempt creation and is idempotent. Preserve the existing defaults: direct application retains failed candidates; the autonomous runner requests cleanup after definite failure. Either path stops on uncertain effects. A later explicit cleanup request can remove a proven owned failed candidate. Delete only a proven owned candidate at its last confirmed revision, using a conditional ref update; do not delete a moved/replaced branch or one checked out in another worktree. Readiness checks must be revalidated at mutation time.
- Keep candidates that passed tests or require review. Cleanup failures remain persisted until reconciled. Missing already-removed owned resources count as clean; absence of ownership does not authorize deletion.
- Acquisition/release of local repository ownership covers crashes: a lost owner becomes interrupted and blocks further mutation until the actual Git state is reconciled. Do not substitute an expired timer for proof Git is idle.

The transition tables are candidates for small data-driven rules, not a general workflow language.

## User stories and acceptance criteria

### 1. As a developer, I want preview and execution separated, so that inspecting a candidate cannot consume it.

#### AC-1: Preview leaves execution eligibility intact
**Given** an eligible signal with applicable changes,
**When** a preview is requested,
**Then** it describes those changes without creating an execution attempt or altering Git, and the signal remains eligible for a real attempt.

#### AC-2: Failed execution can be retried deliberately
**Given** a failed attempt whose resources have been reconciled,
**When** the developer explicitly retries it,
**Then** a new attempt is recorded and the prior attempt and its evidence remain unchanged.

#### AC-3: Candidate limits count eligible work
**Given** already-attempted ineligible candidates precede eligible candidates in ranked results,
**When** an execution run selects its configured maximum,
**Then** ineligible candidates do not consume the eligible-attempt limit.

### 2. As a developer, I want Git effects tied to proven ownership, so that backfill cannot alter unrelated work.

#### AC-4: Successful candidate
**Given** a clean repository and an eligible signal,
**When** its attempt finishes with unchanged tests passing,
**Then** the owned candidate is retained with its test revision and result, and the recorded starting ref is restored without recording human acceptance.

#### AC-5: Unowned or changed resources (outline)
**Given** an attempt references an existing candidate in `<situation>` with `<ownership evidence>`,
**When** cleanup is requested,
**Then** the candidate ref and working trees remain unchanged and cleanup returns `<reason>`.

| situation | ownership evidence | reason |
|---|---|---|
| pre-existing branch collision | no creation confirmation | ownership unproven |
| concurrent branch creation by another actor | failed creation, no confirmation | ownership unproven |
| candidate moved since last confirmation | owned, current HEAD differs | revision changed |
| candidate checked out elsewhere | owned, matching HEAD, occupied worktree | resource in use |
| legacy branch name | no creation or revision record | ownership unproven |
| creation interrupted before confirmation | creation intent only | reconciliation required |

#### AC-6: Refuse dirty input
**Given** a repository with uncommitted user changes,
**When** execution is requested,
**Then** no Git mutation begins and the response explains that a clean working tree is required.

#### AC-7: Persistence before mutation
**Given** recording the attempt or ownership intent fails,
**When** execution is requested,
**Then** no subsequent Git mutation starts and the failure is returned to the caller.

#### AC-8: Exact restoration (outline)
**Given** execution began from `<starting state>` and that recorded state remains unchanged,
**When** the attempt returns control,
**Then** the repository is restored to that exact starting ref and commit.

| starting state |
|---|
| named branch |
| detached HEAD |

#### AC-9: Preserve changes made during execution
**Given** an actor changes the original ref or working tree after execution starts,
**When** restoration is requested,
**Then** it stops with a reconciliation-required result and does not reset or overwrite that actor's changes.

### 3. As an operator, I want interruption made explicit, so that a restart cannot repeat uncertain effects.

#### AC-10: Real interruption recovery (outline)
**Given** a subprocess was terminated after `<boundary>` in a temporary real repository,
**When** a new process opens the saved attempt and inspects recovery status,
**Then** it reports the actual surviving refs and persisted phase, marks uncertain effects for reconciliation, and does not automatically apply or delete anything.

| boundary |
|---|
| candidate creation |
| patch application |
| candidate commit |
| test execution |
| cleanup before its completion was recorded |

#### AC-11: Idempotent owned cleanup
**Given** an owned failed candidate whose expected revision is unchanged,
**When** explicit cleanup is repeated after successful removal,
**Then** cleanup reports removed without modifying another ref or changing the execution outcome.

#### AC-12: Visible cleanup failure
**Given** Git refuses cleanup,
**When** cleanup is attempted,
**Then** failed cleanup and its reason are persisted and the caller receives a non-success result.

#### AC-13: Concurrent executions
**Given** two processes target the same local working tree,
**When** both attempt execution,
**Then** only one may mutate it and the other receives an already-running or reconciliation-required result.

### 4. As a reviewer, I want execution evidence separate from acceptance, so that a green test cannot hide modified tests or imply approval.

#### AC-14: Test edits require review
**Given** the automated fixer edits tests and a subsequent recorded run passes,
**When** the attempt result is read,
**Then** it reports review required, retains the candidate and test-edit evidence, and has no human acceptance decision.

#### AC-15: Invalid transition
**Given** an attempt is in a phase that does not allow a requested execution transition,
**When** that transition is requested,
**Then** it returns a typed invalid-transition result without changing the attempt, Git, test evidence, or review history.

#### AC-16: Human decision preserves test evidence
**Given** a finished reviewable attempt,
**When** a human accepts or rejects it,
**Then** the decision and reason are recorded independently and the original execution/test evidence remains unchanged.

#### AC-17: Structured status
**Given** attempts in active, failed, interrupted, review-required, and cleaned states,
**When** the local status interfaces read them,
**Then** each reports phase, outcome, review, ownership, cleanup, typed reason, and allowed next action without parsing descriptive error text.

#### AC-18: Conservative historical migration
**Given** historical attempts with only status, score, and optional branch name,
**When** their schema is migrated in a disposable copy,
**Then** historical facts remain readable, ownership and missing execution evidence remain unknown, and no replay or cleanup is authorized by migration.

#### AC-19: Reconciliation releases ownership conservatively
**Given** an interrupted attempt with uncertain branch creation, a clean working tree, and the operator already switched away from the candidate,
**When** the operator records abandonment with the current attempt revision and a reason,
**Then** the repository claim is released, the uncertain resource remains externally managed and ineligible for cleanup, and execution remains interrupted until an explicit new attempt is requested.

#### AC-20: Reject stale reconciliation
**Given** the attempt or repository changed after an operator inspected it,
**When** a reconciliation request supplies the older expected revision,
**Then** reconciliation returns a conflict without releasing the claim or modifying Git.

#### AC-21: Preserve caller cleanup policy (outline)
**Given** an attempt definitely failed with a proven owned unchanged candidate and saved policy `<policy>`,
**When** execution finalization applies its saved cleanup policy,
**Then** the candidate's recorded cleanup result is `<result>`.

| policy | result |
|---|---|
| direct-call default retention | retained, branch present at confirmed revision |
| autonomous-run default cleanup | removed, owned candidate ref absent |

## Testing decisions

- Seams: existing BackfillService entry points, Database, GitRepoProtocol, shared provider/test-fixer stubs, CLI results, and temporary real Git repositories.
- Prior art: existing apply/three-way drift, reset-failure, outcome-recording, cleanup, provenance-scoped application, and test-fixer suites. Extend them rather than duplicate their fixtures.
- Test convention: existing plain pytest/pytest-asyncio; no BDD runner or feature files.
- Pure transition tables cover allowed/rejected events; boundary tests cover actual persisted state and Git effects. AC-10 requires real subprocess termination, not a finally block pretending to be a crash.
- Keep 100% source statement coverage, pristine captured error output, all affected verification gates, and issue-to-test acceptance mappings.

## Assumptions

- Existing owner-scoped local operation remains the write boundary. No new authorization surface is introduced.
- Numeric score is execution evidence only where its meaning is defined; acceptance is a separate human decision.
- Migration does not recover historical ownership from error text, branch naming conventions, or the current reflog.
- Existing evidence-backed patch boundaries and test-edit path containment remain unchanged.

## Out of scope

- Merge, PR creation, hosted backfill, automatic recovery of uncertain Git effects, new test-fixer capabilities, and reviving the dormant browser visualization.
- A general event store, workflow engine, scheduler, or public write API.
- Other workflow specifications remain separately scoped in the parent plan.

## Open questions

None at the product-policy level. This specification proposes implementation-facing defaults above for builder review; build approval remains separate from agreeing those policies.

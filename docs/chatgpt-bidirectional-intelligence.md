# ForkHub Bidirectional Intelligence: ChatGPT App MVP

Status: implementation proposal (November 2026). This document describes the intended product; only the relationship-discovery slice is implemented in the companion PR.

## Goal and positioning

ForkHub helps a developer find evidence-backed innovation across the projects they own, fork, and follow. The three primary directions are:

- **Upstream:** changes from the source project that might matter to the developer's fork.
- **Downstream:** improvements in forks of a repository the developer owns or watches.
- **Sibling:** alternative implementations in other forks of a shared parent.

The default ChatGPT experience is a unified ranked intelligence feed. Every finding answers what changed, why it might matter to a particular target repository, and what evidence supports that assessment.

## Product journeys

1. **Connect and select.** Enumerate owned and forked public repositories. Show source projects for personal forks. Let the user choose monitored repositories before incurring AI-analysis costs. Never imply private-repo access without consent.
2. **Discover.** Show a time-bounded, paginated feed of relevant upstream, downstream, and sibling findings. Filter by direction, repository, category, score, freshness, and state of applicability.
3. **Investigate.** Open a finding with evidence URLs, source and target refs, changed files, analysis timestamp, and an explicit observed/inferred/unknown distinction. Show a sibling implementation comparison when appropriate.
4. **Monitor.** Background syncs update analysis; conversational queries read cached results. Make freshness, incomplete coverage, and errors visible.

### Screen and component contracts

- **Overview:** number of tracked repos, last successful scan, new findings, and incomplete scans. Empty state explains how to connect and track.
- **Feed:** direction tabs (All, Upstream, Downstream, Sibling), category/significance filters, compact finding cards, cursor pagination. Cards show summary, source/target, significance, time, evidence availability.
- **Detail:** immutable analyzed SHA range, provenance and diff links, observed changes, inferred benefits, unknowns, changed files, cluster members, and suggested follow-up questions.
- **Relationship explorer:** one focus repo, its immediate source, direct/indirect descendants as supported, and sibling forks. Aggregate large networks; never render unbounded graphs.
- **Comparison:** side-by-side implementation evidence and tradeoffs. Do not declare tested performance or compatibility unless tests/benchmarks actually ran.

ChatGPT prose remains useful without widgets. The widget provides selection, overview and inspection, not essential data hidden from the model.

## Current implementation and limitations

ForkHub v0.4.0 exposes `ForkHub.get_repos`, `get_forks`, `get_signals`, and `get_clusters`. `TrackerService.detect_upstream_repos` tracks *parents* of a user's forks as upstream but does not currently persist a durable relationship from each personal fork to its parent. `Fork` is scoped to `tracked_repo_id`; `RepoInfo` provides `is_fork` and `parent_full_name`. The Explore FastAPI interface already maps domain models into a view, so keep UI data shaping in shared services, not endpoint handlers.

The first implementation slice, `RelationshipService.discover`, is a bounded, read-only snapshot using existing GitProvider methods. It does **not** persist edges, compute evidence-based applicability, or discover multi-generation ancestry. Its `complete` flag represents coverage limitations, not confidence in correctness. Do not conflate a direct parent with the ultimate root in nested fork chains.

## Intended intelligence data model

Separate *signals* (observed changes in a source repository) from *findings* (meaning of a signal to a particular target repository/user). The same signal may be relevant to one fork and already incorporated in another.

Proposed `IntelligenceFinding`:
- `id`, `signal_id`, `source_repo_id`, `target_repo_id`, `direction`
- `relevance_score`, `relevance_reason`, `applicability` (`likely_relevant`, `already_present`, `not_applicable`, `unknown`)
- `evidence_id`, `evaluated_at`, `last_seen_at`, `analysis_version`

Proposed evidence record:
- stable source and target GitHub IDs; base/head refs and commit SHAs
- comparison URL and commit URLs; affected files; analysis timestamp
- test/benchmark status (`not_tested` by default)
- confidence and partial-data warnings

Use an additive SQLite migration for relationship edges and evidence; index source/target and SHA pairs. Preserve immutable evidence for historical findings. A missing commit SHA is *not* proof a change is absent: cherry-picks and independent implementations need patch/semantic equivalence evaluation.

## MCP tool contracts (planned, not implemented)

Read tools return structured Pydantic models and concise text summaries. Limit output size and use cursors. Tool hints are informative, never authorization guarantees.

| Tool | Inputs | Response |
|---|---|---|
| `get_my_ecosystem` | cursor, tracking mode | owned, forked, watched repos; freshness |
| `get_repository_relationships` | focus repo, depth/limit/cursor | bounded directed edges, coverage |
| `get_intelligence_feed` | repo?, directions[], since?, category?, min_score?, limit/cursor | contextual findings, stale/partial flags |
| `get_finding` | finding_id | detail, immutable SHA evidence, uncertainty |
| `compare_related_forks` | source and target repo, optional ref | commits/files and applicability caveats |
| `get_clusters` | repo, size, cursor | semantically related signals and source refs |
| `get_scan_status` | repo? | last scan, pending jobs, errors |

Write operations (`track_repository`, sync requests, patch application) should be separately marked and authorization-gated. Backfill and PR creation are **out of scope** for the read-only MVP. Never run arbitrary fork code in the API host.

Use official MCP Python SDK over Streamable HTTP and optional Apps SDK widget resources. Persist work in backend jobs; avoid synchronous full-fork scans during a ChatGPT tool request. The deployed service requires authenticated identity, tenant-scoped queries, rate limiting, and separate GitHub scopes. Public-repo pilot may start with a single configured maintainer account but must not expose that account's data to unrelated callers.

## Next increments

1. **Relationships** (this PR): bounded direct upstream/downstream/sibling discovery, tests and design specification.
2. **Persistence and ancestry**: durable edges, multi-generation relationships, migrations, reconciliation, and transparent incomplete coverage.
3. **Intelligence query layer**: contextual findings, relevance ranking, deduplication, immutable SHA evidence, pagination.
4. **MCP transport**: read-only tools, auth, schema snapshots, error contracts, integration tests.
5. **ChatGPT widgets**: feed, investigation, relationship explorer, conversational fallback.
6. **Pilot deployment**: OAuth, background workers, quotas, tenant isolation, observability, staged onboarding.

## Test and acceptance strategy

- Unit tests use `StubGitProvider` and shared fixtures, no `unittest.mock`.
- Relationship tests cover owned, user-fork, sibling exclusion of focus, duplicates, page budget, missing parent, invalid input, untracked public repo, and shared parent semantics.
- Preserve the repo's 100% statement coverage and run `uv run pytest`, `uv run ruff check src/ tests/`, `uv run ruff format --check src/ tests/`, and `uv run ty check` before merging.
- Each observed assertion must be tied to GitHub evidence and dated SHA refs. Don't promote AI inference to verified outcomes.
- Pilot metrics: fraction of findings marked useful, investigations per finding, duplicate rate, source accuracy, and analysis cost per useful discovery.

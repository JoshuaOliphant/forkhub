# Explicit workflow transitions in existing services

Status: Proposed, 2026-11-13. Implementation approval pending.

## Context

ForkHub has independent SQLite-backed workflows for comparison/analysis, local backfill,
clustering, and digest delivery. Existing fields conflate observations with completion,
resource names with ownership, and attempted effects with confirmed success.
The shared-core roadmap requires website and MCP to report the same underlying facts.

## Proposed decision

Use small typed state and transition policies per workflow. Keep phase, outcome,
reason, evidence, and ownership separate when they describe distinct facts.
Persist transitions only where restart correctness requires them. Perform I/O at
service edges and publish durable outcomes atomically where one datastore permits it.
Reconcile uncertain external effects explicitly; SQLite cannot make Git or delivery atomic.

Do not add a generic workflow engine or event store. Do not keep competing legacy
write paths: migrate authoritative records and update internal callers together.

## Alternatives and trade-offs

- Enums around current fields reduce initial change but retain ambiguous completion and ownership.
- A workflow engine centralizes orchestration but adds scheduling, infrastructure, and operational
  cost beyond these repairs; it still requires domain-specific effect reconciliation.
- Per-workflow policies cost some local repetition and several migrations, but keep each
  transition understandable and testable without a general orchestration subsystem.

## Consequences

Durable work identities, claims, and public status contracts need explicit migration and
cross-interface tests. These contracts are the costly part to change later.
Legacy facts remain unknown where evidence is missing. New terminal states require
completion evidence; display status is derived rather than separately stored by each UI.
The database remains the current SQLite system, with read-only export into the hosted cache.

Each workflow is implemented and reviewed separately. No deployment or operational
database migration follows from accepting this design document.

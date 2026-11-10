# Signal evidence

[Issue #35](https://github.com/JoshuaOliphant/forkhub/issues/35) implements the
provenance slice of [Milestone 2](https://github.com/JoshuaOliphant/forkhub/issues/63).
Signals retain model interpretations separately from immutable source evidence.

## Capture and verification

`store_signal` accepts full, lowercase, 40-character `commit_shas` in application
order and `files_involved`. The source repository comes from the persisted fork
identity. The shared `capture_evidence` service fetches each cited commit by SHA,
checks the returned SHA, and records relevant file changes and textual patches.
External analysis tools can reuse this service without the Claude SDK.

At the agent-tool boundary, JSON-encoded SHA arrays are decoded, full hexadecimal
SHAs are lowercased, and duplicate SHAs/files are removed in input order. Unusable
references retain the interpretation with an explicit warning and unavailable or
partial evidence. A valid subset is never presented as complete evidence.

The evidence record includes `source_repository`, `commit_shas`, `files`,
`changes`, `captured_at`, `verified_at`, `verification_state`, and `warnings`.
Each change identifies its commit, filename, status, and available patch.

| State | Meaning |
| --- | --- |
| `unavailable` | No immutable references were supplied, or no cited commit could be retrieved. Legacy signals have null evidence and are also displayed as unavailable. |
| `partial` | Some source information was retrieved, but a commit, relevant file, complete response, or complete textual patch is missing. |
| `verified` | Every cited commit and relevant file has checked immutable textual evidence. This does not verify the interpretation, significance, safety, or usefulness of a change. |

Missing patches, binary files, pagination, unrelated commits, SHA mismatches,
and API failures never become verified evidence. Patch addition/deletion counts
are checked against GitHub metadata to detect truncated textual patches.
Verification checks the cited content, not file modes, executable bits, symlink
types, signatures, current branch equivalence, or successful adoption. Added and
removed file patch headers use mode `100644` because the API file metadata does
not supply modes.

## Persistence and both interfaces

The local schema adds nullable `signals.evidence` JSON. Existing rows remain
null; no attempt is made to reconstruct their provenance from a mutable head.
The cache exporter includes the same evidence in the dedicated read-only schema.
The website, SQLite reader, and D1 reader share the signal result contract,
including immutable commit links and uncertainty warnings. The website exposes
the recorded patches in its source-evidence inspector. ChatGPT receives the same
evidence and must preserve the warnings when explaining signals.

Cache freshness is separate from immutable evidence. A failed or inaccessible
repository sync marks cached analysis stale. A successful historical sync reports
its timestamp without claiming the cache is current. Missing sync timestamps
leave freshness unknown. An empty or filtered signal list is not proof that
analysis ran or that no meaningful changes exist.

Backfill uses only recorded per-commit patches for signals with evidence and
refuses partial or mismatched evidence. Commit order is supplied by the analyst;
application and tests remain necessary. Legacy signals retain the existing
comparison path and remain unverified; its patches cannot establish which
commits produced an old interpretation.

## Review and release boundary

Run the unit suite with its required 100% statement coverage and the local
Workers/D1 integration test. Tests use in-memory or disposable databases. For
real-data acceptance, create a fresh disposable cache, capture a real public
commit, inspect the actual website HTML, export to a fresh local database, and
compare the entire website/SQLite/D1/MCP signal result dictionaries.

This code does not update hosted schemas by itself. Before release, review the
exported schema and prepare an approved release/import with rollback. Starting
the library against an existing writable database applies additive migrations;
do not point review experiments at an operational database.

The new readers select `signals.evidence`. They cannot read a cache exported
before this schema: `list_cached_signals` fails with a missing-column error.
Release must pair the code with a fresh export imported into a new D1 database;
never deploy this Worker against the current database binding first. Rolling the
Worker back while keeping the fresh database is safe because the old query
ignores the added column.

Local transport verification does not establish acceptance in the live ChatGPT
connection. Production deployment, either hosted database, and the operational
local cache remain outside this review's write scope. Milestone 2 acceptance
requires a separately approved hosted rollout and fresh authenticated ChatGPT
comparison.

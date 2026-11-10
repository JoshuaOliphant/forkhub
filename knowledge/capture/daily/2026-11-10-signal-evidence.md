# Signal evidence review preparation — 2026-11-10

Started Milestone 2 at #35 in an isolated worktree. Source repository identity,
full commit SHAs, relevant files, captured textual changes, and explicit
verification state now travel through signal creation, local persistence,
cache export, website inspection, and read-only MCP responses.

The review caught two ways to overstate verification: mismatched signal/evidence
file sets and repeated commit SHAs. Repeated SHAs also multiplied backfill
patches. Both are rejected at the model and cache boundaries. Regression tests
protect the invariants; model interpretation and significance remain unverified.

## Observed real-data round trip

Used public fork `JoshuaOliphant/learnharness`, upstream
`amosblomqvist/learnharness`, commit
`0795ef197cca04f6a8e7d50d10ed4dc71bd1a0cc`, file
`tests/chatgpt-auth.test.ts`. The commit contains 36 additions and 6 deletions.

The signal's interpretation was supplied manually for acceptance. No model
analysis, discovery, or operational-cache refresh ran. The actual provider
retrieved the immutable commit, checked its SHA and patch counts, and stored
verified content evidence in a fresh disposable database.

Observed exact signal-response equality across website data, source SQLite,
export/import SQLite, D1 reader, and an authenticated local MCP tool call.
The actual website HTML contained the SHA link, source-evidence inspector,
and interpretation disclaimer. Import `quick_check` returned `ok`; hashes of
both disposable database files remained unchanged during read-only checks.
Private operator artifacts are under
`~/.local/share/forkhub/acceptance/2026-11-10-provenance/`.

The local Workers/D1 integration also passed with a non-empty verified signal,
signed identity, denied invalid credentials, and unchanged disposable databases.
A real temporary Git repository accepted two recorded commits in sequence,
preserved the starting branch, and excluded an unrelated file change.

## Limits and follow-up

Production, both hosted databases, and the operational local cache were not
opened for writing or migrated. Live ChatGPT acceptance remains pending a
separately approved release; local MCP parity does not stand in for that check.
The analyzer CLI primitives in #32 remain separate work.

Jev semantic lint could not run because `TYPESAFE_API_KEY` was absent. Ruff and
fresh diff review provide narrower checks, not a semantic-lint pass. This same
credential limitation was already observed during earlier work; the owning
environment needs the credential before that check can be enforced.

The existing CI Workers/D1 test now includes verified provenance, so losing
evidence in Worker packaging or the hosted query boundary fails automatically.

Local final unit run: 966 passed, 4 deselected; 4,019 source statements covered,
100% statement coverage, no warnings. Ruff lint/format and diff whitespace checks
passed. The local Workers/D1 integration passed separately (1 test).

## Review and verification follow-through

Independent Standards, Spec, correctness and approach passes reviewed the change.
The Standards pass found malformed nested cache evidence could crash the website;
`08642c8` validates it before rendering. A real Git rename-chain regression failed
when commit patches were combined; `8856e25` preserves commit boundaries, reports
final paths and rejects changes that cancel out. The PR's model-input comment
was reproduced before `8918533`: recoverable references are normalized at the
tool boundary, while unusable references retain the interpretation with partial
or unavailable evidence. Strict persisted validation remains intact.

Fresh final verification passed: 1,032 unit tests, 4,054/4,054 source statements
(100%), 114 Ruff files, two integration tests and all 14 cached acceptance rows.
Production import without development dependencies and isolated Worker dry-run
bundling passed. The real-source round trip is now a committed integration test.
The styled website and expanded evidence inspector were observed in the browser
using a disposable cache copy. No production or operational database was changed.

The host has no compost Workflow tool or native Codex review command, so the
review ran by hand with independent agents and skeptics; the independent
correctness pass was a substitute, not a claimed native review. Jev remained
unavailable and the local telemetry collector was down. No mutation tool is
configured, so no automated mutation score is claimed. An ambient npm
allow-scripts warning is documented without changing the user's configuration.

Ruling and acceptance table: https://github.com/JoshuaOliphant/forkhub/issues/35#issuecomment-6772758024

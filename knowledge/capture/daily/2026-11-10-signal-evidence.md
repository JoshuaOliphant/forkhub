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

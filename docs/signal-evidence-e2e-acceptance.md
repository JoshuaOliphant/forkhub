# Evidence-backed signal rollout and acceptance (Milestone 2)

This procedure completes [roadmap #63](https://github.com/JoshuaOliphant/forkhub/issues/63)
after merged PR #67. Local tests and a release bundle are preparation; hosted
acceptance remains pending until fresh authenticated ChatGPT calls and actual
website inspection agree with the prepared snapshot.

## Prepare the private release

Use a checkout containing #67 and this procedure. Record its full commit SHA,
the Worker compatibility date, and hashes of `uv.lock`,
`deploy/cloudflare/uv.lock` and `deploy/cloudflare/package-lock.json` in the
private operator record. Run `uv run python scripts/verify.py` on that checkout.
Do not treat earlier verification as proof for a different tree.

Choose one real target repository whose cache contains at least one visible
signal with verified immutable evidence. Legacy signals remain unavailable;
never fill in their evidence from a current branch head. If no such signal
exists, capture new evidence with the existing analysis/store-signal workflow
before preparing the bundle. Record whether the interpretation came from a
model or was manually supplied; content verification does not verify its meaning.
The real-source integration uses an explicitly manual interpretation and is not
proof of a completed model analysis.

Verify the whole source cache belongs to this single user. The exporter filters
relationships by username, but repositories and signals are not tenant-isolated.
Use the actual source path; do not point review experiments at the operational
cache with a writable `Database` instance. An older schema must first be backed
up with SQLite's online backup API and migrated **only in the disposable copy**.
Do not copy a live `.db` file without its SQLite transaction state.

With `release_source`, `release_dir`, and `release_repo` set to actual private
paths and the selected owner/name:

```sh
umask 077
uv run python examples/prepare_signal_release.py prepare \
  --source "$release_source" --output "$release_dir" \
  --username JoshuaOliphant --repository "$release_repo" \
  --confirm-single-user
```

The command creates a new mode-0700 directory and mode-0600 files. Existing
output directories are refused. It opens the source read-only, takes a consistent
SQLite backup, exports only the served schema, imports a fresh `cache.db`, runs
`quick_check`, and compares all three tool response bodies with the snapshot.
It requires at least one verified signal and refuses truncated acceptance
responses (more than 50 visible repositories or target signals). It does not
scan, invoke models, migrate the source, or deploy.

| Artifact | Purpose |
|---|---|
| `snapshot.db` | Exact full application backup for disposable website inspection; checksummed |
| `cache.sql` | Minimal fresh-schema import for a new D1 database |
| `cache.db` | Local reimport for contract comparison; not a full application database |
| `expected.json` | Exact response bodies, including evidence, timestamps and warnings |
| `manifest.json` | Counts, checksums, tool arguments and pending hosted/website status |

A manifest is written last after local checks pass. A failed preparation may
leave private intermediate files, but no valid manifest. Choose a new output
directory for a retry. Keep the entire bundle outside Git and public artifacts.
Checksums detect accidental changes; they are not signatures or proof of origin.

## Website inspection

The bundle retains `snapshot.db`, the exact full application backup used for
`expected.json`. Verify the bundle before inspection, then launch against a
**disposable copy**, since application startup can migrate or write the database.
From the reviewed checkout, with the same absolute `release_dir` and `release_repo`:

```sh
uv run python examples/prepare_signal_release.py compare \
  --bundle "$release_dir" --actual "$release_dir/expected.json"
website_dir=$(mktemp -d)
chmod 700 "$website_dir"
(umask 077; cp -f "$release_dir/snapshot.db" "$website_dir/website.db")
chmod 600 "$website_dir/website.db"
FORKHUB_DATABASE_PATH="$website_dir/website.db" GITHUB_USERNAME=JoshuaOliphant \
  uv run forkhub web --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/<owner>/<repo>` using `$release_repo` as the
`<owner>/<repo>` path. Substitute the manifest's username for `JoshuaOliphant`
if preparing a different user's bundle. The comparison above checks checksums
only against the saved expected bodies; it is not hosted acceptance. Keep
`snapshot.db` unchanged and discard the website copy after inspection.
`snapshot.db` is the bundle's most sensitive artifact: it contains the full
application database, including data such as embeddings and sync errors that
`cache.sql` omits; delete it and any remaining website copies once the acceptance
record is complete.
`cache.db` is the minimal MCP schema and must not be opened as a writable full
application database.

Inspect the actual target page: expand the evidence inspector, follow the
immutable commit links, and compare source repository, SHAs, files, patches,
verification state and warnings against `expected.json`. Save private
screenshots and observations. Freshness and content verification must remain
separate, and interpretation/significance must remain explicitly unverified.
Do not write test edge cases into the operational cache. Empty, stale, partial
and unavailable states are exercised with disposable regression fixtures; record
that distinction from the real non-empty hosted case.

## Pair the Worker and fresh D1 schema

Use the existing approved Cloudflare account and protected hostname, following
[the deployment procedure](cloudflare-worker-deployment.md). This release does
not require a new paid plan, domain, Access policy, or public preview endpoint.

1. Record the current Worker version, private configuration, D1 database name/ID,
   Access application and exact allowed identity. Retain a deployable copy of the
   previous reviewed code/configuration and verify rollback credentials work.
2. Create a **new empty D1 database**. Verify the account and new ID against the
   operator record before transfer. Never import into the currently bound database.
3. Create a mode-0600 candidate private Wrangler configuration beside the Worker
   project, preserving the existing Access issuer/audience/identity/hostname and
   disabled `workers.dev`/preview settings. Change its DB binding to the new ID.
   Keep the previous private configuration intact for rollback.
4. Import `cache.sql` into that new ID with Wrangler's reviewed `--remote` command
   and explicit candidate `--config`. Check all four table counts against the
   manifest, `PRAGMA quick_check`, and `PRAGMA table_info(signals)` for `evidence`.
   Locally import the same SQL with Wrangler/D1 as an additional transport check.
5. Build the candidate Worker with `--dry-run`, using the same candidate config
   directory as deployment. Inspect the bundle. Only then release the reviewed
   Worker **and the new DB binding together** to `mcp.forkhub.dev`.
6. Verify missing/invalid/forged credentials still receive denial and that no
   alternate public preview endpoint exists. Preserve the existing exact-identity
   policy; do not weaken authentication to troubleshoot acceptance.

The new reader selects `signals.evidence`; deploying it against the previous
cache first causes missing-column errors. The old reader can read the fresh
schema, but restoring the old Worker **and its old database binding** is the
preferred exact rollback. Keep both databases until acceptance and cleanup are
separately recorded.

## Fresh authenticated ChatGPT comparison

Use the actual connected ForkHub app after deployment. Call all three tools with
the exact arguments in `manifest.json`, including `limit=50` and
`min_significance=1`. Save the returned JSON bodies, not prose summaries or raw
JSON-RPC envelopes, to a private `actual.json` object keyed by:

- `list_tracked_repositories`
- `get_cached_relationships`
- `list_cached_signals`

Record call time, tool/connection identity and deployed version separately. Do
not create `actual.json` by copying expected responses. The comparison command
cannot establish that responses originated from a live authenticated tool call.

```sh
uv run python examples/prepare_signal_release.py compare \
  --bundle "$release_dir" --actual "$release_dir/actual.json"
```

It verifies artifact checksums and exact response parity, including full signal
evidence and uncertainty warnings. It does not change the manifest's pending
states or declare milestone acceptance. If a tool cannot be called, record
`blocked: tool unavailable`. A successful D1 import is insufficient.

## Rollback and completion record

If deployment or parity fails, restore the previous reviewed Worker version and
DB binding, retaining Access. Recheck authenticated catalog/relationship/signal
responses against the prior snapshot. Keep failed candidate resources for
inspection; do not delete either database during rollback.

| Check | Required evidence | Initial status |
|---|---|---|
| Reviewed release | Full code SHA, lockfile hashes, fresh verifier output | Pending |
| Dedicated real source | Confirmed single-user scope; interpretation origin | Pending |
| Private local package | Manifest counts, checksums, quick_check and exact parity | Pending |
| Actual website | Disposable `snapshot.db` copy; rendered signal IDs, source, SHAs, files, patches, verification and warnings match `expected.json`; screenshots and username recorded | Pending |
| Protected hosted release | New D1 ID/schema/counts, Worker version, denial checks | Pending |
| Authenticated ChatGPT | Three fresh call records and exact comparison pass | Pending |
| Edge states | Disposable empty/stale/partial/unavailable regression results | Pending |
| Rollback | Previous version/binding retained; observed restore/recovery result | Pending |

Record private evidence paths, statuses and limitations in the operator record.
Post only a sanitized summary on #35/#63. Mark Milestone 2 accepted only after
all applicable rows have actual evidence. Then begin Milestone 3 recommendations.

# Relationship-first end-to-end acceptance (Milestone 1)

This is the operator-run acceptance procedure for [roadmap #63](https://github.com/JoshuaOliphant/forkhub/issues/63). It validates **one real discovery snapshot** through local SQLite, the relationship-first website, the exported read-only MCP cache, and the authenticated ChatGPT pilot. A successful unit test or a healthy MCP endpoint does **not** imply a repository has been scanned.

Target: `JoshuaOliphant/An-Oliphant-Never-Forgets`, scope: `JoshuaOliphant`.

## 0. Preconditions and boundaries

- Use a checkout containing merged PRs #64 and #65. Have a narrowly scoped GitHub read credential configured for the CLI. Do not print or commit it.
- Use the **same configured GitHub username** for discovery, website reads, and cache export. For watched repos, this can differ from the repository's owner.
- Confirm the local source cache is exclusively yours before exporting. The exporter does not enforce tenant isolation on tracked repos or signals.
- The authenticated MCP app is **read-only** and cannot start discovery or import D1 data. Do not infer that an empty signal list means a code scan ran.
- Do not replace an existing D1 database in-place. Cloudflare import requires a separate approved hosted-database/binding update; do not bypass Access.
- A GitHub API error, missing credentials, or a partial scan is a failed or qualified acceptance result, **not** a zero-relationships success.

## 1. Run real relationship discovery

From the repository root, with your existing CLI configuration:

```bash
uv run forkhub relationships JoshuaOliphant/An-Oliphant-Never-Forgets \
  --username JoshuaOliphant --max-pages 3
```

Record the **actual** relationship count, pages scanned, and `complete` flag in the acceptance record below. A zero relationship count is valid only when there is a persisted scan; it is not equivalent to `not_scanned`. When pagination is incomplete, explicitly record it and consider a higher page bound after checking rate limits.

Check the configured source database path; the default is `~/.local/share/forkhub/forkhub.db`, but `FORKHUB_DATABASE_PATH` can override it. Keep the database and its WAL sidecars private.

## 2. Inspect the local cache and website

Launch the local website against **that same source database and username**:

```bash
uv run forkhub web --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/JoshuaOliphant/An-Oliphant-Never-Forgets`.

Verify that the page shows:
- A cached relationship view, not `Not scanned yet`, after a successful persisted scan.
- Source repositories with the correct upstream/downstream/sibling direction and clickable GitHub links, or an explicit empty-result state.
- Last attempt timestamp, pages scanned, completeness, last complete timestamp, and warning if coverage is incomplete.
- For a later partial refresh after a complete scan: the previously complete graph remains visible with a stale-preserved warning, not replaced by partial results.
- For an untracked/empty catalog: an appropriate empty state, **not** an executable but invalid discovery command.

Compare with the local read-only MCP contract without calling any external model:

```bash
uv run python - <<'PY'
import json
from forkhub.config import get_db_path, load_settings
from forkhub.mcp_preview_queries import PreviewQueries

path = get_db_path(load_settings())
reader = PreviewQueries(path, "JoshuaOliphant")
result = reader.get_cached_relationships("JoshuaOliphant/An-Oliphant-Never-Forgets")
print(json.dumps(result, indent=2))
PY
```

The website and the local read-only contract must agree on status, relationship directions and sources, scan completeness, and warnings. This comparison uses the **local** cache; it does not prove the hosted D1 copy is updated.

## 3. Export a private cache snapshot (no remote deployment yet)

Export from the same source database to a **new**, private path, after verifying the data is single-user:

```bash
umask 077
uv run python examples/export_mcp_cache.py \
  --source "${FORKHUB_DATABASE_PATH:-$HOME/.local/share/forkhub/forkhub.db}" \
  --destination /PRIVATE/PATH/forkhub-relationships-acceptance.sql \
  --username JoshuaOliphant \
  --confirm-single-user
```

The exporter reports counts for `tracked_repos`, `signals`, `relationship_snapshots` and `repository_relationships`. Do not commit the output or paste real contents into an issue.

**Local dry-run import into a fresh database**, using SQLite from the command line:

```bash
sqlite3 /PRIVATE/PATH/forkhub-acceptance-local.db \
  < /PRIVATE/PATH/forkhub-relationships-acceptance.sql
sqlite3 -readonly /PRIVATE/PATH/forkhub-acceptance-local.db 'PRAGMA quick_check;'
```

The check must return `ok`. Compare the imported read-only contract to the source:

```bash
uv run python - <<'PY'
from forkhub.mcp_preview_queries import PreviewQueries

repo = "JoshuaOliphant/An-Oliphant-Never-Forgets"
username = "JoshuaOliphant"
source = PreviewQueries("/PRIVATE/PATH/forkhub.db", username)
imported = PreviewQueries("/PRIVATE/PATH/forkhub-acceptance-local.db", username)
assert source.get_cached_relationships(repo) == imported.get_cached_relationships(repo)
assert source.list_cached_signals(repo) == imported.list_cached_signals(repo)
print("Local source/import parity: PASS")
PY
```

Replace `/PRIVATE/PATH/forkhub.db` with the **actual source database path** from step 2. This comparison does not verify a real code scan or evidence SHAs.

## 4. Protected D1 import and actual ChatGPT acceptance (separate operator action)

Only with the approved Cloudflare account, private-data transfer, and release/binding change:
1. Prepare a **new empty D1 database** and confirm its intended database ID/account. Do not overwrite the live database or expose a `workers.dev` preview URL.
2. Follow [Cloudflare Worker deployment](cloudflare-worker-deployment.md) to import the reviewed private SQL, validate row counts and `PRAGMA quick_check`, and switch the protected Worker binding with a rollback path. Test access-denied behavior before sending real data.
3. Make *fresh authenticated* ChatGPT calls to `list_tracked_repositories`, `get_cached_relationships`, and `list_cached_signals`. Compare the target repository's status, edge sources/directions, completeness, attempt timestamps, and warnings with step 2.
4. Preserve the signal warning: existing model interpretations are **not independently verified** and SHA-level provenance is not available in this preview. Do not claim changed code, safe cherry-picks, or complete scan coverage without evidence.

If the authenticated pilot cannot be called, record `blocked: tool unavailable` rather than declaring success. A D1 import alone does not establish ChatGPT tool functionality.

## Acceptance record (fill with verified values, not guesses)

| Check | Observed result / link | Status |
|---|---|---|
| Source repo and discovery scope | | Pending |
| Discovery attempt timestamp, pages, complete | | Pending |
| Persisted relationship count and directions | | Pending |
| Website scan state, links, warning | | Pending |
| Local read-only contract agrees with website | | Pending |
| Private export counts and local import quick_check | | Pending |
| Protected D1 transfer, new binding, rollback | | Pending |
| Fresh authenticated ChatGPT result equals local snapshot | | Pending |
| Provenance warning remains visible | | Pending |

**Milestone 1 acceptance:** All relevant rows are verified with actual observations. Until then, code/CI success is **implementation progress**, not an end-to-end successful real scan.

# Cloudflare Worker deployment

This single-user deployment serves ForkHub's three read-only MCP tools from
Cloudflare Workers and D1. Cloudflare Access Managed OAuth owns login,
registration, and consent. The Worker verifies the signed Access application
assertion before querying the cache. A local computer, tunnel, and open terminal
are not part of the hosted request path.

The code and local tests do not constitute a production deployment. Obtain
approval for the paid plan, DNS delegation, Access application, published
Worker route, and private-cache transfer before changing those resources.

## Cost and responsibilities

| Component | Responsibility | Cost basis |
| --- | --- | --- |
| Route 53 registrar | Own and renew `forkhub.dev` | Registration and renewal charge |
| Cloudflare DNS and Access | HTTPS hostname and the exact allowed identity | Selected account plans |
| Workers Paid | Execute MCP and signed assertion checks | US$5/month minimum, plus metered usage |
| D1 | Store the published cache tables | Included allowances, then metered queries and storage |

Check current prices in the account before rollout. The US$5 Workers minimum
is not a spending cap. Monitor requests, CPU, D1 rows read/written, and storage.
The Worker configuration limits request CPU to 1,000 milliseconds; that limit
does not cap total monthly usage. Configure usage alerts and inspect billing
after the synthetic test and again after a week of normal use.

Route 53 remains the registrar when the domain is delegated to Cloudflare.
Registration creates an AWS hosted zone automatically. Inspect it after
delegation; an unused zone can continue to incur DNS hosting charges. Remove
only the unused new zone after Cloudflare DNS is verified and cleanup is
approved. Do not alter existing domains or shared account policies.

## Prepare and test the Worker

`deploy/cloudflare` is a Python Workers project based on Cloudflare's official
Python example. It retains the example's Wrangler/pywrangler tooling. Its
minimal dependency set avoids installing the full application's local
embedding and analysis stack. `deploy/cloudflare/library/pyproject.toml`
builds a pure-Python wheel directly from the canonical `src/forkhub` source.
It does not maintain copied library files. Keep the complete repository
checkout: copying only `deploy/cloudflare` omits the wheel's source inputs.
Install Node.js 22 or later and `uv` before running the project. The checked-in
Node lockfile pins Wrangler 4.158.0; use `npm ci` to install that version.

From the repository root:

```bash
cd deploy/cloudflare
npm ci
uv sync --frozen
uv run pywrangler dev --ip 127.0.0.1 --port 8788
```

To inspect the library distribution separately, run `uv build --wheel
--project library --out-dir /PRIVATE/PATH/worker-wheel` from
`deploy/cloudflare`. Check the built wheel contains the reviewed library
modules and canonical cache schema. Use the checked-in build manifest and
lockfile when building the Worker bundle.

Use the checked-in compatibility date and lockfile. Earlier Python Workers
runtime dates can resolve a different Python/Pyodide version and dependency
set. The entry point creates a fresh stateless MCP application for each
request because Workers starts the ASGI lifespan per request. Reusing one
FastMCP session manager across those lifespans fails on subsequent requests.

Configuration requires these values:

- `FORKHUB_ACCESS_ISSUER`: the exact `https://TEAM.cloudflareaccess.com` issuer.
- `FORKHUB_ACCESS_AUDIENCE`: the dedicated Access application's audience.
- `FORKHUB_ACCESS_EMAIL`: the exact single permitted email address.
- `FORKHUB_GITHUB_USERNAME`: the owner of the dedicated cache.
- `FORKHUB_HOSTNAME`: the one intended hostname, `mcp.forkhub.dev`.
- `DB`: the D1 binding for this installation's cache.

Keep deployment identity values outside the public repository. No GitHub,
Anthropic, or Cloudflare management token belongs in Worker runtime variables.
The D1 binding supplies database access without an API credential in code.
Bindings can write; this application restricts its tool paths to fixed,
parameterized read queries. Do not describe the binding itself as a read-only
database credential.

The checked-in configuration disables `workers.dev` and preview URLs and
publishes no production route. Keep both disabled for real-cache deployments.
An unprotected alternate hostname must not become a repository-data endpoint.
Host validation and signed assertion verification remain required even when
Access also protects the public hostname.

## Export only the served cache

The exporter reads an existing current-schema ForkHub database in a consistent
read-only transaction. It writes only the MCP-visible columns from
`tracked_repos`, `signals`, `relationship_snapshots`, and
`repository_relationships`. It omits credentials, webhook configuration,
embeddings, forks, digests, and unrelated tables. Relationship rows are limited
to the configured username, and their original order is preserved.

Tracked repositories and signals are not tenant-isolated in the source
database. The operator must verify the entire source cache belongs to this
installation's user. `--confirm-single-user` records that assertion; it does
not infer ownership from the rows.

Start with the [synthetic smoke cache](chatgpt-secure-tunnel-smoke.md). From the
repository root, export to a new private path:

```bash
uv run python examples/export_mcp_cache.py \
  --source /PRIVATE/PATH/demo.db \
  --destination /PRIVATE/PATH/forkhub-demo-import.sql \
  --username forkhub-demo \
  --confirm-single-user
```

The destination is created exclusively with mode 0600. Existing files and
symlinks are rejected. The command reports row counts, not SQL or repository
contents. Keep the import outside Git and public build artifacts. A source
with an old schema must first be copied consistently and initialized locally;
the exporter never migrates or writes the original cache.

The SQL creates a fresh schema and inserts one row per statement. It contains
no transaction wrapper, destructive statements, or replacement operations.
Import into a new empty database. An existing table causes failure rather
than replacing data. Preserve the prior production database when preparing
an updated cache.

The exporter rejects a row whose escaped SQL statement exceeds D1's 100,000-byte
limit, before creating the import file. Resolve that row's storage/import
design before proceeding; do not truncate or drop its fields to make it fit.

## Prepare the protected hosted installation

After rollout approval, create a dedicated D1 database and put its actual ID
in the deployment configuration. With the Worker project selected, import
the approved synthetic SQL using the binding name:

```bash
npx wrangler d1 execute DB --local --file=/PRIVATE/PATH/forkhub-demo-import.sql
```

The local command does not upload the cache. When the correct new hosted
database and the upload are approved, use the same command with `--remote`
instead of `--local`. Inspect the target account, database name, and ID before
doing so. Check imported row counts and `PRAGMA quick_check` before binding
the hosted Worker to the database. Never upload the full local database dump.

Create Access protection before publishing the Worker route:

1. Add the new domain to the approved Cloudflare account and inspect the
   assigned nameservers. Update only `forkhub.dev`'s registrar delegation.
   Verify authoritative DNS before configuring the MCP route.
2. Create a dedicated self-hosted Access application covering the entire
   `mcp.forkhub.dev` hostname. Attach the exact single-user Allow policy. Do
   not add Bypass, Everyone, or Service Auth rules.
3. Enable Managed OAuth with only the exact callback displayed by the new
   ChatGPT connection. Keep localhost and loopback client allowances off.
4. Set the Worker's issuer, application audience, email, username, hostname,
   and dedicated D1 binding. Verify an authenticated build/configuration
   preview before releasing the approved version.
5. Publish only the protected custom hostname. Keep `workers.dev` and preview
   URLs disabled and retain assertion verification in the Worker.

Do not copy the temporary pilot's audience into the new application by
assumption. Each Access application has its own audience. The existing
[Managed OAuth guide](cloudflare-managed-oauth-pilot.md) explains issuer,
policy, discovery, callback, and credential-denial checks.

## Acceptance before real data

Verify the actual deployed service, not only an import or local simulation:

1. Missing credentials, invalid bearer credentials, and forged Access
   assertions must return a denial, never tool results or repository data.
2. Complete the real ChatGPT OAuth login and consent. Invoke all three tools
   and compare their synthetic results with local `PreviewQueries` results.
3. Test an identity outside the exact email policy. Inspect the Access
   decision and Worker outcomes without logging assertion or token values.
4. Test malformed inputs, pagination, case-insensitive repository names,
   missing relationships, and model-provenance warnings. Review errors and
   warnings before declaring acceptance.
5. Verify there is no public alternate preview endpoint. Deploy a fresh
   version and repeat a new actual tool call to establish independence from
   local processes. Keep the old protected pilot until this passes.

Only after synthetic acceptance and the private-data transfer are approved,
export the user's dedicated real cache into a new private SQL file. Import it
into a new dedicated hosted database, verify its contents locally, and switch
the reviewed binding/version. Repeat all three actual ChatGPT calls against
known expected values. Compare source-cache checksums before and after export.

## Cache updates, restore, and rollback

This deployment serves a published cache. It does not automatically refresh
GitHub data, run relationship discovery, create embeddings, or invoke models.
Empty cached signals and `not_scanned` relationships remain valid results.
Scheduling and budgeted analysis require separate implementation and
credential decisions; they must not be inferred from the hosted read tools.

For an update, export and validate a consistent source snapshot, import it
into a new database, compare the three tool contracts, and release a reviewed
binding change. Keep the previous database and Worker version for rollback.
Record the commit, compatibility date, lockfile, database ID, expected counts,
and export timestamp without storing credentials or private results in Git.

Use D1's supported export and recovery facilities and test restoration into
a separate database. Keep an approved encrypted copy of the private import.
Do not rely only on a Worker code rollback: it does not restore database data.
If acceptance fails, disconnect the new route while retaining Access
protection, restore the previous reviewed Worker/database binding, or return
to the previous protected pilot. Never weaken authentication to restore
availability. Retire old domains, routes, databases, and policies only in an
approved cleanup after confirming which resources are still in use.

## References

- [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/)
- [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/)
- [D1 SQL import and export](https://developers.cloudflare.com/d1/best-practices/import-export-data/)
- [D1 statement and storage limits](https://developers.cloudflare.com/d1/platform/limits/)
- [D1 recovery](https://developers.cloudflare.com/d1/reference/time-travel/)
- [Python Workers ASGI](https://developers.cloudflare.com/workers/languages/python/packages/fastapi/)
- [Cloudflare Access Managed OAuth](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/)

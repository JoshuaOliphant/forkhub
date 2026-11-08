# Managed ForkHub deployment

Run one single-user ForkHub installation on an Ubuntu 24.04 LTS VM with a
persistent disk. Cloudflare Access Managed OAuth protects `mcp.YOUR_DOMAIN`;
a dedicated, remotely managed Cloudflare Tunnel reaches the loopback MCP
origin. The VM's systemd services restart after failures and boot. The Mac
and its terminal sessions are not part of this traffic path.

This is a deployment procedure, not evidence that a particular VM or hostname
has been provisioned. Approve the provider, region, recurring cost, hostname,
and private-cache transfer before publishing a route or uploading real data.

## Process and storage boundaries

| Service | Identity | Data and credentials |
| --- | --- | --- |
| `forkhub-mcp` | `forkhub-mcp:forkhub-read` | Read-only published snapshot and Access issuer, audience, email, and GitHub username |
| `forkhub-tunnel` | `forkhub-tunnel` | Dedicated tunnel token delivered by systemd credentials |
| `forkhub-sync` | `forkhub-sync:forkhub-read` | Writable source cache and a narrowly scoped GitHub credential |
| `forkhub-publish` | `forkhub-sync:forkhub-read` | SQLite backup from source cache to an atomically published snapshot |

The MCP process has no GitHub or model credential and cannot write the
published directory. Each request opens the snapshot in SQLite read-only mode.
The writer uses `/var/lib/forkhub/cache/forkhub.db`; the reader uses
`/var/lib/forkhub/published/mcp.db`. Do not serve the writer's WAL database
directly from a filesystem the reader cannot write: SQLite may need sidecar
files after a writer disconnects.

Publication uses SQLite's backup API through the `sqlite3` CLI, converts the
temporary copy to DELETE journal mode, sets its group-readable permissions,
and renames it over `mcp.db` on the same filesystem. A failure before the rename
leaves the last published database in place. systemd serializes publication
and orders it after an in-progress sync. Do not run the unit's individual
publication commands concurrently by hand.

This is one user's dedicated database. Repository and signal tables are not
tenant-isolated. Do not combine other users' private caches in this service.

## Prepare the approved VM

Install Python 3.12 or later, `uv`, `sqlite3`, Git, CA certificates, and
`cloudflared` from their official distributions. Pin the release and verify
download signatures or checksums. The tunnel unit expects `/usr/bin/cloudflared`
version 2025.4.0 or later, which supports `--token-file`. Check these paths
against the installed packages before continuing.

Allow administrative SSH only from the operator's network or an approved
private access path. Do not open port 8767 to the Internet. Permit the outbound
connections required by Cloudflare Tunnel, HTTPS to the Access issuer, and
GitHub HTTPS only if scheduled refresh is enabled. Configure host security
updates, disk monitoring, and the provider's backup policy.

Create the service identities and directories as the administrator:

```bash
sudo groupadd --system forkhub-read
sudo useradd --system --gid forkhub-read --home-dir /nonexistent --shell /usr/sbin/nologin forkhub-mcp
sudo useradd --system --gid forkhub-read --home-dir /var/lib/forkhub/cache --shell /usr/sbin/nologin forkhub-sync
sudo useradd --system --user-group --home-dir /nonexistent --shell /usr/sbin/nologin forkhub-tunnel
sudo install -d -o root -g root -m 0755 /etc/forkhub
sudo install -d -o root -g forkhub-read -m 0750 /var/lib/forkhub
sudo install -d -o forkhub-sync -g forkhub-read -m 0700 /var/lib/forkhub/cache
sudo install -d -o forkhub-sync -g forkhub-read -m 0750 /var/lib/forkhub/published
```

Install the reviewed, pinned repository release at `/opt/forkhub`, owned by
root and readable but not writable by service identities. Do not copy a local
`.env`, `.forkhub-demo`, Git credential, database, or model cache into the
release directory. Resolve dependencies using the checked-in lockfile:

```bash
cd /opt/forkhub
sudo uv sync --frozen --no-dev --extra mcp
sudo chown -R root:root /opt/forkhub
```

Ensure the installed Python interpreter and virtual environment are readable
by all three service identities. A root-only interpreter under `/root` will
not work with the units' `ProtectHome=yes`; use a system interpreter or a
shared, root-owned uv installation location.

## Configure without disclosing secrets

Install `deploy/mcp.env.example` as `/etc/forkhub/mcp.env` and
`deploy/sync.env.example` as `/etc/forkhub/sync.env`, both root-owned mode 0600.
Edit them through the VM's approved secret-management or administrator editor.
Use the new Access application's exact issuer, audience, allowed email, and
the cache owner's GitHub username. Keep the database paths from the examples.

Leave the sync service and timer disabled until a GitHub credential has been
authorized. Use a read-only credential limited to the repositories required
for this deployment. Do not install an Anthropic key, Claude token, or the
`claude` extra for this migration. The scheduled command is explicitly
`forkhub sync --no-analyze`.

Store the dedicated Cloudflare tunnel token, by itself, in
`/etc/forkhub/tunnel-token`, owned by root and mode 0600. Do not put it in a
shell command, command history, unit file, chat, GitHub issue, or log. systemd's
`LoadCredential` exposes a private copy to the tunnel process; the token value
does not appear in `ExecStart` or the process arguments.

Install the units and check them on Linux:

```bash
sudo install -o root -g root -m 0644 deploy/systemd/* /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/forkhub-*.service /etc/systemd/system/forkhub-sync.timer
sudo systemctl daemon-reload
```

Do not proceed past warnings or errors from unit verification. Review
`systemd-analyze security forkhub-mcp.service forkhub-tunnel.service` and
confirm any remaining permissions are required for the workload.

## Import and publish a cache

First use the [synthetic smoke database](chatgpt-secure-tunnel-smoke.md).
Transfer it over the authenticated administrative connection into the private
cache directory, install it as `forkhub-sync:forkhub-read` mode 0600, and
verify its synthetic contents before starting the public route.

For the real cache, prepare a consistent backup on the source machine. Never
copy the main file of a live WAL database with `cp` or `scp` alone:

```bash
umask 077
FORKHUB_IMPORT_DIR=$(mktemp -d)
sqlite3 -readonly "$HOME/.local/share/forkhub/forkhub.db" ".backup '$FORKHUB_IMPORT_DIR/forkhub.db'"
sqlite3 -readonly "$FORKHUB_IMPORT_DIR/forkhub.db" 'PRAGMA quick_check;'
```

The check must return exactly `ok`. Transfer the backup only after the
synthetic OAuth and denial tests below pass and the private-data transfer is
approved. Stop the optional sync timer and wait for any running sync and
publish jobs before replacing the source cache. Keep the previous source
backup for rollback. Install the transferred file as
`/var/lib/forkhub/cache/forkhub.db`, owner `forkhub-sync:forkhub-read`, mode 0600.

Initialize the imported cache's current schema without calling GitHub or a
model. Run this locally on the VM; it modifies only the imported source copy:

```bash
sudo -u forkhub-sync /opt/forkhub/.venv/bin/python - <<'PY'
import asyncio
from forkhub.database import Database

async def initialize():
    async with Database("/var/lib/forkhub/cache/forkhub.db"):
        pass

asyncio.run(initialize())
PY
sudo systemctl start forkhub-publish.service
sudo systemctl status forkhub-publish.service --no-pager
sudo -u forkhub-mcp sqlite3 -readonly /var/lib/forkhub/published/mcp.db 'PRAGMA quick_check; PRAGMA journal_mode;'
```

The final command must return `ok` and `delete`. Verify the snapshot's expected
repository count locally before making actual ChatGPT calls. Confirm the MCP
identity cannot write the published database or read the writer's directory.
The `forkhub-publish` oneshot becomes inactive after successful completion;
its recorded exit status must be zero.

## Protect the new hostname before routing

Use a ForkHub-owned DNS zone and a dedicated Access application for the whole
`mcp.YOUR_DOMAIN` hostname. Follow the
[Managed OAuth pilot procedure](cloudflare-managed-oauth-pilot.md): retain
the exact single-user Allow policy, no Bypass/Everyone rules, the exact
ChatGPT OAuth callback, and origin assertion verification. Configure Managed
OAuth before publishing DNS or a tunnel hostname route.

Create a dedicated remotely managed tunnel for this deployment. Its published
application route must target `http://127.0.0.1:8767`, with origin HTTP Host
header `127.0.0.1:8767`. Enable connector-side Access validation with the same
team and audience as the Python origin. Keep the old pilot route and its
Access policy intact until the new connection passes acceptance.

After approval of the actual route and access change, enable the services:

```bash
sudo systemctl enable --now forkhub-mcp.service forkhub-tunnel.service
sudo systemctl is-active forkhub-mcp.service forkhub-tunnel.service
sudo journalctl -u forkhub-mcp.service -u forkhub-tunnel.service --since '10 minutes ago' --no-pager
```

Both services must report `active`. A healthy tunnel alone does not prove that
OAuth, origin reachability, or tool calls work.

## Acceptance and cutover

1. Check that port 8767 listens only on loopback. Direct local MCP requests
   with no assertion, an invalid assertion, or only a bearer token must fail.
2. Check unauthenticated public MCP requests and forged credentials: they must
   return an OAuth challenge or denial, never repository data. Check issuer,
   protected resource, PKCE S256, and exact registered ChatGPT callback.
3. Connect ChatGPT to the new hostname using OAuth. Complete login and consent,
   invoke all three tools, and compare the actual synthetic values locally.
4. Test an identity outside the Allow policy and inspect Access denials. Keep
   signed-token rejection unit tests as the origin's regression check.
5. After synthetic acceptance, import and publish the approved real cache.
   Repeat the three actual ChatGPT calls against locally known results and
   compare snapshot checksums before and after reads.
6. Restart both services, repeat a tool call, then reboot the VM and verify
   that both services return to `active` and a fresh ChatGPT tool call works.
   Close the Mac's old connector terminal and stop its origin; repeat once
   more to prove the new deployment is independent.

Only after all checks pass, switch the user-facing ChatGPT connection to the
new hostname. Retire the temporary route in a separately approved cleanup;
never remove its Access protection while its DNS route remains reachable.

## Optional refresh and operations

After authorizing the GitHub credential, run one manual refresh and inspect
the complete journal, including warnings:

```bash
sudo systemctl start forkhub-sync.service
sudo journalctl -u forkhub-sync.service -u forkhub-publish.service --since '2 hours ago' --no-pager
sudo systemctl enable --now forkhub-sync.timer
sudo systemctl list-timers forkhub-sync.timer --all
```

The timer runs at 00:00, 06:00, 12:00, and 18:00 UTC with up to ten minutes of
jitter, and catches up after downtime. The CLI can report repository errors
while exiting successfully, so a successful service exit alone does not prove
every repository refreshed. Inspect warnings and cached timestamps. A failed
publish leaves the previous snapshot available; monitor publish failures and
snapshot age as well as service liveness.

`sync --no-analyze` refreshes repository, fork, and release data without model
calls. It does not populate relationship snapshots and does not generate new
signals. Existing relationships can remain `not_scanned`; empty cached signals
are valid. Relationship discovery and budgeted AI analysis need separate
product and credential decisions.

Back up the writable source cache with SQLite `.backup`, verify `quick_check`
returns `ok`, and copy the backup to an approved encrypted off-host location.
Keep a retention policy and test restore to a separate path before relying on
the backup. VM snapshots are supplemental: they do not replace a tested
database restore. Do not back up runtime credential files alongside a public
release archive. Record the deployed commit, dependency lock, configuration
names, and backup timestamp without recording credential values.

For application upgrades, keep the previous reviewed release and a database
backup, stop the sync timer and wait for active jobs, then stop the origin,
replace `/opt/forkhub` with the pinned release and resolve the frozen runtime
dependencies. Initialize the source schema, publish, restart, and repeat the
denial and actual-tool checks. Never run dependency updates automatically as
part of service startup.

## Rollback

Stop the new tunnel to disconnect the new deployment while leaving Access
protection in place. Reconnect the previous authenticated pilot if needed;
its private snapshot remains independent. Restore the previous reviewed code
and a compatible source backup with sync and MCP services stopped, republish,
and rerun acceptance before reconnecting. Do not restore a database over an
active writer or weaken shared Cloudflare policies to recover availability.

## References

- [Cloudflare Tunnel token-file parameter](https://developers.cloudflare.com/tunnel/reference/run-parameters/#token-file)
- [Cloudflare Managed OAuth](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/)
- [SQLite online backup API](https://sqlite.org/backup.html)
- [SQLite read-only WAL behavior](https://sqlite.org/wal.html#read_only_databases)
- [systemd service execution and credentials](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html)

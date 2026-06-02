# Recovering beads (bd) in a fresh sandbox / web session

This project tracks issues with **beads (`bd`)** on a **Dolt** backend. The
Dolt database is *runtime state* and is **not** in git (see `.gitignore`:
`dolt/`); only the JSONL export under `.beads/backup/` is committed. So in a
fresh Claude Code on the web container (or any fresh clone) `bd` is missing,
Dolt is missing, and the database has to be rebuilt from the backup.

The steps below are the **verified working sequence** (2026-06). Several
"obvious" commands do **not** work here — those dead ends are noted so you
don't repeat them.

## TL;DR

```bash
# 1. Install bd (lands in /root/go/bin, NOT on PATH)
curl -sSL https://raw.githubusercontent.com/steveyegge/beads/main/scripts/install.sh | bash
export PATH="$PATH:/root/go/bin"

# 2. Install dolt (single binary -> /usr/local/bin/dolt)
curl -sSL https://github.com/dolthub/dolt/releases/latest/download/install.sh | bash

# 3. Use EMBEDDED mode, not the committed server mode (see gotcha #2)
#    Edit .beads/metadata.json: "dolt_mode": "embedded"
#    Clear any half-built runtime state:
rm -rf .beads/dolt .beads/embeddeddolt .beads/dolt-server.*

# 4. Init fresh AND use it immediately (see gotcha #3)
bd init --prefix forkhub

# 5. Load the committed backlog (needs schema coercion, see gotcha #4)
#    then replay dependencies (see gotcha #5). Script below.
```

## Gotchas (why the simple path fails)

1. **No prebuilt binary.** The bd install script's GitHub-releases path
   returns HTTP 403 in this sandbox; it falls back to `go install`
   (`go` is present). The binary lands at `/root/go/bin/bd`, which is **not on
   PATH** — export it. Same shape for any `bd` invocation in a new shell.

2. **Committed `metadata.json` pins `dolt_mode: server`.** In server mode `bd`
   tries to "reconcile shared-server metadata" against a stale port and dies
   with `dial tcp 127.0.0.1:0: connect: connection refused`. **Switch
   `dolt_mode` to `embedded`** for sandbox work. Don't commit that flip — it
   changes the maintainer's backend (it's left modified in the working tree
   but kept out of issue-tracking commits).

3. **`bd init` then *immediately* create/import.** Running `bd backup restore`
   (or other commands) *between* `bd init` and the first real use corrupts the
   DB's `issue_prefix` config — every later command then fails with
   `database not initialized: issue_prefix config is missing`. If you hit that,
   `rm -rf .beads/dolt .beads/embeddeddolt` and re-`init`.

4. **The committed JSONL is an OLDER (schema v6) dense format.** A current `bd`
   (v1.0.5) `bd import` rejects it with type errors. Coerce before importing:
   - `ephemeral`, `is_template`, `pinned`: int → bool
   - `waiters`: string → `[]string` (empty string → `[]`)
   (Iterate: `bd import --dry-run` names the next offending field + target type.)

5. **`bd backup restore` does NOT work here.** It's a *Dolt-native* restore
   that expects a Dolt remote/commit, not the JSONL files in `.beads/backup/`.
   It fails with `Error 1105: not found` (the stored dolt commit hash isn't
   present). Use `bd import` for issues + `bd dep add` for dependencies instead.
   A couple of historical deps may be rejected by newer validation rules
   (e.g. "epics can only block other epics") — that's fine, skip them.

6. **Don't `pkill` the Dolt server.** Killing the child server process makes
   this shell exit with code 144. Use `bd dolt stop` (or just leave it; embedded
   mode doesn't run a server).

## Restore script (steps 5–6)

Run after steps 1–4, with `PATH` including `/root/go/bin`:

```bash
python3 - <<'PY'
import json, subprocess, re, os
env = dict(os.environ); env["PATH"] += ":/root/go/bin"
recs = [json.loads(l) for l in open(".beads/backup/issues.jsonl") if l.strip()]

# Coerce old dense schema -> current bd schema, driven by import errors.
pat = re.compile(r"cannot unmarshal (\w+) into Go struct field \S*\.(\w+) of type (\S+)")
def coerce(field, totype):
    n = 0
    for d in recs:
        if field not in d: continue
        v = d[field]
        if totype == "bool" and isinstance(v, (int, float)):
            d[field] = bool(v); n += 1
        elif "[]" in totype and isinstance(v, str):
            d[field] = json.loads(v) if v.strip().startswith("[") else ([] if v == "" else [v]); n += 1
        elif totype in ("int","int64","float64") and v == "":
            d[field] = 0; n += 1
    return n

for _ in range(40):
    open("/tmp/conv.jsonl","w").write("\n".join(json.dumps(d) for d in recs) + "\n")
    r = subprocess.run(["bd","import","--dry-run","/tmp/conv.jsonl"], capture_output=True, text=True, env=env)
    m = pat.search(r.stdout + r.stderr)
    if not m:
        print("parse OK:", (r.stdout + r.stderr).strip().splitlines()[0]); break
    _, field, totype = m.groups()
    if coerce(field, totype) == 0:
        print("could not coerce", field); break

subprocess.run(["bd","import","/tmp/conv.jsonl"], env=env)

# Replay dependencies (bd dep add <issue_id> <depends_on_id> --type <type>)
for l in open(".beads/backup/dependencies.jsonl"):
    if not l.strip(): continue
    d = json.loads(l)
    subprocess.run(["bd","dep","add", d["issue_id"], d["depends_on_id"],
                    "--type", d.get("type","blocks"), "--no-cycle-check"],
                   capture_output=True, text=True, env=env)
print("done")
PY
```

## Persisting NEW issues back to git

`bd backup`/`bd export` write a *newer* format than the committed dense file.
To avoid reformatting the 49 historical records (which the maintainer's `bd`
reads natively), **append** new records in the *same dense schema*:

1. Create issues normally with `bd create ... --json` and capture the ids.
2. Build dense records from a template (the first line of
   `.beads/backup/issues.jsonl`): copy it, reset every field to its type
   default, then set `id/title/description/issue_type/priority/status/created_at/
   updated_at/created_by/owner` and a `content_hash` (sha256 of
   `id+title+description` is fine — `bd` recomputes on import).
3. Append those lines to `.beads/backup/issues.jsonl`.
4. Append dependency rows to `.beads/backup/dependencies.jsonl`
   (`{created_at, created_by, depends_on_id, issue_id, type}`).
5. Bump the counts + timestamp in `.beads/backup/backup_state.json`.
6. Commit only those three files (not `metadata.json`, `config.yaml`, runtime
   dirs, or `uv.lock`).
```

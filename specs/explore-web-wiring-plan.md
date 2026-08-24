# Plan — Wire Explore web UI to FastAPI + library (forkhub-87l)

Implements [explore-web-wiring-spec.md](explore-web-wiring-spec.md). Library-first:
data access + mapping live in the library/web package; the frontend is hardened to
consume real (nullable, sometimes-missing) data. TDD; the 100% coverage gate (AC-11)
applies to all new Python.

## Architecture

```
ForkHub (library)
  ├─ get_signals(owner, repo) -> list[Signal]            # wraps db.list_signals  (AC-1)
  └─ get_clusters_with_members(owner, repo)              # Cluster + member fork_ids (AC-2)
        uses db.list_clusters + db.get_signal_cluster_map + signals' fork_id

src/forkhub/web/
  ├─ data.py    build_explore_data(forkhub, owner, repo) -> dict   (AC-3,4,5)
  │               maps Fork + latest Signal -> frontend JSON shape; detail->reasoning,
  │               files_involved->files; no cost; carries fork.html_url; signal may be None
  ├─ app.py     FastAPI: StaticFiles + Jinja2Templates; GET /{owner}/{repo}, GET /  (AC-6, D1)
  ├─ templates/explore.html   (moved from web/explore.html; {{ data|tojson }})     (AC-7)
  └─ static/... (unchanged paths)

cli/web_cmd.py   forkhub web [--host --port]   -> uvicorn.run(app)                 (AC-9, D2)

frontend hardening (static/js/explore.js, constellation.js, static/css/forkhub.css):
  null-safe signal, escapeHTML, html_url links, LAYOUT recompute, color unification,
  dead-CSS removal                                                          (AC-4,8,10,12)
```

## Existing surface to build on

- `db.list_signals(...)`, `db.list_clusters(repo_id)`, `db.get_signal_cluster_map(repo_id)`,
  `db.get_tracked_repo_by_name(full_name)` — all present.
- `ForkHub.get_forks/get_clusters` already raise `ValueError` for untracked repos — mirror that.
- `Fork`, `Signal`, `Cluster` models in `models.py`; `Signal.fork_id`, `detail`,
  `files_involved`, `significance`, `category`, `summary`.
- `tests/stubs.py` (`StubGitProvider`, factories) + `tests/conftest.py` (`db`, fixtures).
- `otel.py` for the instrumentation span (AC-13).

## Tasks (Beads) — every AC mapped

| Task | Covers | Depends on |
|------|--------|-----------|
| T1 library accessors: `get_signals` + `get_clusters_with_members` (+ tests) | AC-1, AC-2 | — |
| T2 `web/data.py` `build_explore_data` mapper (+ tests) | AC-3, AC-5 | T1 |
| T3 FastAPI app + route + template conversion + move fixture + deps (+ TestClient tests) | AC-6, AC-7, D1, D3 | T2 |
| T4 `forkhub web` CLI command (+ test) | AC-9 | T3 |
| T5 frontend hardening: null-safe signal, escapeHTML, html_url, LAYOUT recompute, color unify, dead-CSS | AC-4, AC-8, AC-10, AC-12 | T2 (field names) |
| T6 observability span on render path (+ assert it fires) | AC-13 | T3 |
| T7 docs: CLAUDE.md web section + module map + `forkhub web` usage | docs | T3, T4 |

AC-11 (100% coverage) is a VERIFY gate across T1–T4/T6, not a separate task.

## Risks / notes

- **signal=null is the headline risk**: a synced-not-analyzed fork has no signal. `data.py`
  must emit `signal: null`; the frontend must render a "not analyzed yet" state (AC-4).
- **Coverage gate**: `uvicorn.run` entrypoint gets one `# pragma: no cover`; everything
  else is TestClient/unit covered.
- **Frontend (T5) is not measured by pytest coverage** (JS) — verify via DOM assertions
  in a headless render during VERIFY.
- Keep `web/explore.html` working as a static dev page until T3 converts it, so nothing
  regresses mid-build.

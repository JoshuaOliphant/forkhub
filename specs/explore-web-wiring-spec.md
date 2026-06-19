# Spec — Wire Explore web UI to FastAPI + library (forkhub-87l)

Make the fixture-fed Explore zone (`src/forkhub/web/`) consume **real** data from the
ForkHub library, served by FastAPI, hardened against the live-data gaps the code review
surfaced. Library-first: data access lives in the library, the web layer only maps +
serves.

Source: bead `forkhub-87l` (description + review hardening notes). PRODUCT.md / DESIGN.md
define the Observatory identity; the frontend already reads a
`<script id="forkhub-data" type="application/json">` block — the same shape Jinja injects.

## Decisions (autonomous)

- **D1** `GET /` redirects to the first tracked repo; if none are tracked, render the
  Explore page with an empty-state ("No repos tracked yet") rather than a 404.
- **D2** `forkhub web` defaults to host `127.0.0.1`, port `8000`, `--reload` off.
- **D3** The dev fixture JSON moves to `tests/fixtures/explore_sample.json` and doubles
  as a test fixture, so the template no longer ships an inline fixture.
- **D4** Per-fork cost is dropped from the inspector (the `Signal` model has no cost);
  no session-cost surfacing in this feature.
- **D5** Reuse the existing `otel.py` + lite harness; instrument the page-render path
  with one span rather than adding new telemetry infrastructure.

## Acceptance Criteria

**AC-1 — Library: signals accessor.**
Given a tracked repo with stored signals,
When `ForkHub.get_signals(owner, repo)` is called,
Then it returns the repo's `list[Signal]`; and for an untracked repo it raises
`ValueError` (consistent with `get_forks`/`get_clusters`).

**AC-2 — Library: cluster membership.**
Given clusters exist for a repo,
When the library is asked for clusters with membership,
Then each cluster exposes its member **fork ids** (derived from
`db.get_signal_cluster_map` + each signal's `fork_id`).

**AC-3 — Data mapper shape.**
Given a tracked repo,
When `build_explore_data(forkhub, owner, repo)` runs,
Then it returns a dict matching the frontend contract:
`repo{name, full_name, fork_count, last_sync?}`,
`clusters[{id, label, members:[fork_id], summary}]`,
`forks[{id, owner, sha, html_url, live?, signal?}]` where `signal` (when present) is
`{category, significance, summary, reasoning, files}` mapping real `Signal` fields
(`detail`→`reasoning`, `files_involved`→`files`); **no `cost` field**.

**AC-4 — Unanalyzed forks don't crash.**
Given a fork that has been synced but has no signal yet (`signal` null),
When it is rendered in the map, inspector, list, and any cluster it belongs to,
Then nothing dereferences a missing signal; the inspector shows a "not analyzed yet"
state. (Frontend: `populateFork`/`buildList`/`populateCluster` null-safe; cluster member
resolution filters unresolved ids like `computeLayout` does.)

**AC-5 — Real fork URLs.**
Given forks (including renamed ones),
When GitHub links are built,
Then they use each fork's real `html_url`/`full_name` carried through the data, not a
reconstruction of `github.com/{owner}/{upstream-name}`.

**AC-6 — FastAPI route.**
Given the app is running,
When `GET /{owner}/{repo}` is requested for a tracked repo,
Then it returns `200` with the Explore HTML embedding the mapped data as JSON; static
assets are served; `GET /` behaves per D1.

**AC-7 — Template conversion.**
Given the page is server-rendered,
When `templates/explore.html` renders,
Then the inline fixture is replaced by server-injected `{{ data|tojson }}` and static
paths use `url_for('static', ...)`; Jinja autoescaping covers server-rendered values.

**AC-8 — No client-side XSS.**
Given a fork owner or agent-written summary/detail containing HTML
(e.g. `<img src=x onerror=...>`),
When the inspector/list/cluster HTML is built client-side,
Then the value is escaped (`& < > " '`) and does not execute; href values are
encoded/validated.

**AC-9 — CLI launches the server.**
Given the package is installed,
When `forkhub web` runs,
Then it starts the FastAPI app via uvicorn on the D2 defaults (host/port overridable).

**AC-10 — Layout recomputes on new data.**
Given the constellation is rendered and `DATA` changes (new/removed forks, a live fork
resolves),
When the map re-renders,
Then layout is recomputed (not served from a stale module cache) and `SELECTED` is
cleared if its id no longer exists.

**AC-11 — Tests + 100% coverage hold.**
Given the new Python code,
When `uv run pytest --cov=src/forkhub -m "not integration and not slow"` runs,
Then `get_signals`, cluster membership, `build_explore_data`, and the FastAPI route
(TestClient + `StubGitProvider` + seeded db fixture) are covered and total coverage
stays at **100%** (the uvicorn entrypoint may use a single `# pragma: no cover`).

**AC-12 — Cleanup.**
Given the frontend has duplicated/dead code the review flagged,
When this feature lands,
Then category→color resolution has one source of truth (no map/inspector divergence for
an unknown category) and dead CSS (`.overlay`, HTML `.node-label` rules, `.cluster-tag`,
unused `.empty`/`.skeleton`/`.btn-ghost`) is removed or wired to real states.

**AC-13 — Observability.**
Given the existing otel harness,
When a page is served,
Then the render path emits one instrumented span/metric with real labels (repo, fork
count), verifiable via the observability-query path.

## Out of scope

Digest and Control zones; HTMX live-update; auth; the already-fixed items (orphaned
backdrop, repo-name color, `members_meta`).

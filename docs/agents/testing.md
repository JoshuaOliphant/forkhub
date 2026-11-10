# Tests and gates

## Test convention

Plain pytest, adopted from the existing suite. Tests live in `tests/`, use
pytest-asyncio, and extend fixtures from `tests/conftest.py` and real provider
stubs/factories from `tests/stubs.py`. There are no BDD feature files.

Run all local review gates with:

```sh
uv run python scripts/verify.py
```

The command stops on the first failure and retains its fresh coverage JSON,
JUnit reports, isolated production environment and Worker bundle under a printed
temporary artifact directory. `--output /absolute/new/path` chooses that directory;
an existing destination is refused. Tests create disposable databases only.

## Gates

The existing `.github/workflows/ci.yml` defines required checks. The local command
runs equivalent checks and verifies every node in [the acceptance cache](acceptance.md)
exists, ran, and passed; missing, skipped, xfailed or failed criteria are failures.

| Gate | Command | Recorded status |
|---|---|---|
| Unit suite and coverage | `uv run pytest -x -q` | 2026-11-10: 1,032 passed, 5 deselected; 4,054/4,054 source statements covered |
| Lint | `uv run ruff check src/ tests/ examples/ deploy/cloudflare/src/ scripts/verify.py` | 2026-11-10: passed, 114 files selected |
| Format | `uv run ruff format --check src/ tests/ examples/ deploy/cloudflare/src/ scripts/verify.py` | 2026-11-10: 114 files already formatted |
| Workers/D1 transport | `uv run pytest tests/test_cloudflare_runtime.py -o addopts='' -m integration -x -q` | 2026-11-10: passed in the 2-test integration gate |
| Real source acceptance | `uv run pytest tests/test_signal_provenance_acceptance.py -o addopts='' -m integration -x -q` | 2026-11-10: passed in the 2-test integration gate; missing network is a failed check |
| Production import | `uv sync --frozen --no-dev --extra mcp`, then import the MCP origin | 2026-11-10: isolated environment excludes pytest and imports the MCP origin |
| Worker bundle | `uv run --python 3.14 pywrangler deploy --dry-run --outdir <temporary-path>` | 2026-11-10: copied checkout produced 918 bundle files without deployment |

CI also runs the unit suite on Python 3.12 and 3.13. Publishing a release is not
a verification gate and is never run by this command. The type checker is not a
CI gate: `uv run ty check` is currently broken at its first diagnostic,
`deploy/cloudflare/src/worker.py:6:6` cannot resolve the Workers-only `workers`
module from the root Python environment. This is not a type-check pass.

The local `npm ci` build step printed an ambient-config warning: its `.npmrc`
`allow-scripts` setting is ignored because the project's `package.json` declares
`allowScripts`. There is no project `.npmrc`; npm uses the explicit project
allowlist. The build passed with zero vulnerabilities. This is a recorded external
build warning, not a pristine test-output claim, and verification neither changes
nor suppresses the user's npm settings.

## Coverage

Threshold: 100% source statement coverage, as already configured in
`pyproject.toml`. The verification command also rejects an empty coverage report.
The existing exclusions are `src/forkhub/otel.py` (mutually exclusive optional SDK
paths), `TYPE_CHECKING` blocks, `raise NotImplementedError`, import-error paths,
and main guards. This review adds no coverage exclusions.

## Mutation

Tool: none. No mutation tool/configuration exists in this repository; automated
mutation execution is skipped. Boundary and wiring changes require a manual
mutation walk with explicit regression assertions. Adding a mutation dependency
or changing the coverage policy is a separate decision.

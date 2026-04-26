# 100% Code Coverage Required

The unit-test suite must hit **100% statement coverage** of `src/forkhub`.
This is enforced by `coverage.fail_under = 100` in `pyproject.toml`, so the
test command itself fails when coverage drops below 100%.

## How to verify locally

```bash
uv run pytest --cov=src/forkhub --cov-report=term-missing -m "not integration and not slow"
```

A passing run ends with `Required test coverage of 100% reached.` Anything
below 100% fails CI.

## Rules when adding or changing code

- **Every new statement must be exercised by a unit test in the same change.**
  Don't merge code without the test that covers it.
- **Don't lower the threshold to "make it green" — fix the coverage instead.**
  The threshold in `pyproject.toml` is non-negotiable; if a new branch is hard
  to reach, design it out or add a focused test.
- **Prefer deleting unreachable code over excluding it.** The smallest passing
  test wins; the smallest reachable code wins more.
- **Use real stubs, not `unittest.mock`.** See `tests/stubs.py` for the
  canonical `StubGitProvider`, `StubNotificationBackend`, `StubEmbeddingProvider`,
  `StubAnalyzer`, `StubTestFixer`.

## When a line genuinely cannot be covered

These categories are excluded automatically by `[tool.coverage.report].exclude_also`
in `pyproject.toml`:

- `if TYPE_CHECKING:` — import-time only, never runs at runtime.
- `except ImportError:` blocks for the optional `[claude]` extra fallback.
- `if __name__ == "__main__":` entry points.

If a line falls outside those patterns and is genuinely unreachable, use a
single `# pragma: no cover` with a one-line justification (why it's
unreachable, not what it does). Don't sprinkle `pragma` directives — each
one is a quiet exception to the rule that adds technical debt.

## Common testability patterns used in this codebase

- **Dependency injection via Protocols.** Services accept protocol-typed
  collaborators; tests pass real stubs that conform to the protocol.
- **`_impl` + thin wrapper pattern in CLI.** Each command has an `async
  _xxx_impl(...)` that accepts injectable `db`, `provider`, and
  `capture_output: list[str] | None`. Tests call `_impl` directly with stubs.
- **Closure-based factories for agent tools.** See `agent/tools.py:create_tools`
  — tools close over injected `db`, `provider`, `embedding_provider`.
- **Monkeypatching `get_services`.** When testing the auto-build branch
  (`if db is None or provider is None: ... await get_services()`), patch
  `forkhub.cli.helpers.get_services` to return your stubs.
- **Real git repos in `tmp_path`.** Use `_init_git_repo_sync(tmp_path)` from
  `tests/test_backfill.py` — it sets `commit.gpgsign=false` so commits
  succeed in environments with required-signing global config.

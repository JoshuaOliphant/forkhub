# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is ForkHub?

ForkHub monitors the constellation of forks around GitHub repositories, uses a Claude Agent SDK agent to classify what changed and why, and surfaces interesting divergences through configurable digest notifications. It's a **Python library first** — the CLI consumes the library. Future consumers (web UI, GitHub Action) would also consume the library. Nothing interesting should live only in the CLI layer.

## Commands

```bash
# Package management
uv sync                          # Install dependencies
uv add <package>                 # Add dependency
uv run forkhub <command>         # Run CLI

# Testing
uv run pytest                    # Run all tests (450 tests)
uv run pytest tests/test_foo.py  # Single file
uv run pytest -k "test_name"    # Single test by name
uv run pytest -x                # Stop on first failure
uv run pytest -m "not integration"  # Skip integration tests
uv run pytest -m "not slow"     # Skip slow tests (model downloads)

# Linting & formatting
uv run ruff check src/ tests/   # Lint
uv run ruff format src/ tests/  # Format

# Type checking
uv run ty check                 # Type check (Astral's ty - preferred)
uv run mypy src/forkhub/        # Type check (mypy - legacy)
```

## Architecture

### Module map

```
src/forkhub/
├── __init__.py          # ForkHub class (public API entry point)
├── models.py            # 18 Pydantic models + 3 StrEnums
├── interfaces.py        # 3 @runtime_checkable Protocols
├── database.py          # Async SQLite + sqlite-vec
├── config.py            # Pydantic Settings (TOML + env vars)
├── providers/
│   └── github.py        # GitHubProvider (githubkit async)
├── embeddings/
│   └── local.py         # LocalEmbeddingProvider (sentence-transformers)
├── notifications/
│   └── console.py       # ConsoleBackend (Rich-formatted terminal output)
├── services/
│   ├── tracker.py       # Repo discovery, track/untrack/exclude/include
│   ├── sync.py          # Fork sync pipeline + analyzer invocation
│   ├── cluster.py       # Cosine-similarity clustering
│   └── digest.py        # Signal filtering, digest generation/delivery
├── agent/
│   ├── tools.py         # 7 custom MCP tools via create_tools() factory
│   ├── prompts.py       # System prompts for coordinator + subagents
│   ├── agents.py        # diff_analyst, digest_writer AgentDefinitions
│   ├── hooks.py         # Cost tracker + rate limit guard hooks
│   └── runner.py        # ClaudeAnalyzer (Analyzer protocol, batching)
└── cli/
    ├── app.py           # Root Typer app (11 commands)
    ├── helpers.py       # async_command decorator, get_services()
    ├── formatting.py    # Rich tables, panels, significance bars
    └── *_cmd.py         # One module per command group
```

### Library-first with Protocol-based plugins

The core library exposes a `ForkHub` class (`__init__.py`) as the public API — an async context manager with injectable providers. Extension points use Python `Protocol` classes (structural typing) defined in `interfaces.py`:

- **`GitProvider`** — fetches repo/fork data (implemented: `GitHubProvider` via githubkit async)
- **`NotificationBackend`** — delivers digest notifications (implemented: `ConsoleBackend`)
- **`EmbeddingProvider`** — generates text embeddings for cluster detection (implemented: `LocalEmbeddingProvider` via sentence-transformers)

### Agent SDK coordinator + subagent pattern

Analysis uses the Claude Agent SDK (`claude-agent-sdk` package) with custom in-process tools (not a separate MCP server):

1. **Coordinator agent** — gets tools to explore forks (list_forks, get_fork_summary, get_file_diff, etc.)
2. **diff-analyst subagent** (Sonnet) — deep-dives individual forks, calls `store_signal` for findings
3. **digest-writer subagent** (Haiku) — composes notification digests from accumulated signals

The agent decides what to investigate. It starts with file lists + commit messages (cheap), then fetches full diffs only for interesting files. Budget caps (`max_budget_usd`) prevent runaway costs.

### Data flow: sync → analyze → digest

```
forkhub sync  →  discover forks (GitHub API)  →  compare (HEAD SHA changed?)
              →  agent session (classify changes, store signals)  →  update clusters

forkhub digest  →  query signals since last digest  →  digest-writer agent  →  deliver via backends
```

### Database

SQLite + sqlite-vec (vector similarity for clustering). Single file at `~/.local/share/forkhub/forkhub.db`. Key tables: `tracked_repos`, `forks`, `signals`, `clusters`, `cluster_members`, `digest_configs`, `digests`. Schema is in `spec.md` §8.

### Signals and clusters

A **signal** is a classified change (categories: feature, fix, refactor, config, dependency, removal, adaptation, release) with a significance score 1-10. When multiple forks make similar changes independently, they form **clusters** — detected via vector similarity of signal embeddings.

### Configuration

`forkhub.toml` in `~/.config/forkhub/` or project root. Pydantic Settings with env var overrides (`GITHUB_TOKEN`, `ANTHROPIC_API_KEY`).

## Key Patterns

### Closure-based dependency injection for agent tools

Agent SDK `@tool` handlers only accept `args: dict`. Use a factory function that returns tool instances closing over injected dependencies:

```python
def create_tools(db, provider, embedding) -> list[SdkMcpTool]:
    @tool("list_forks", "...", schema)
    async def list_forks(args):
        # db, provider available via closure
        ...
    return [list_forks, ...]
```

### Service layer bridges Pydantic ↔ DB dicts

Services accept/return Pydantic models but convert to `dict[str, Any]` for the database layer using `model.model_dump()` with datetime/JSON serialization.

### Async CLI via decorator

Typer doesn't natively support async. The `async_command` decorator in `cli/helpers.py` wraps async `_impl()` functions with `asyncio.run()`. Each command module has a testable `_impl()` and a thin Typer wrapper.

### Graceful sqlite-vec degradation

sqlite-vec may fail to load on some platforms. Always check `db.vec_enabled` before vector operations. Clustering falls back to non-vector mode when unavailable.

### Env var precedence over TOML

Pydantic Settings `**kwargs` override env vars. The `_merge_env_over_toml()` function in `config.py` explicitly checks `os.environ` and overlays values on TOML data before constructing settings, ensuring: env vars > TOML > defaults.

## Dos

- Use Pydantic models (not ORM) for all data structures — see `models.py`
- Use async throughout — githubkit and the Agent SDK are both async
- Use `uuid4` strings for all primary keys
- Store JSON arrays as TEXT columns in SQLite (e.g., `files_involved`, `signal_ids`)
- Keep CLI layer thin — it should only parse args, call library services, and format output with Rich
- Use ETag caching for GitHub API conditional requests to minimize rate limit usage
- Track HEAD SHA per fork to skip unchanged forks during sync
- Use real stubs (protocol-conforming classes) in tests, never `unittest.mock`
- Use shared stubs from `tests/stubs.py` and fixtures from `tests/conftest.py` — don't duplicate
- Check existing tests before adding new ones — parameterize or extend instead of duplicating
- All files start with 2-line `ABOUTME:` comments

## Don'ts

- Don't use `unittest.mock` — write real stub classes that conform to Protocols
- Don't put business logic in CLI commands — keep them as thin `_impl()` + wrapper pairs
- Don't pass `**toml_data` directly to Pydantic Settings constructors — use `_merge_env_over_toml()`
- Don't assume sqlite-vec is available — always gate on `db.vec_enabled`
- Don't use `claude-ai` or `anthropic` for agent features — the package is `claude-agent-sdk`
- Don't define local StubGitProvider, db fixtures, or factory helpers in test files — import from `tests/stubs.py` and `tests/conftest.py`
- Don't add tests that overlap with existing ones — search test files first, then parameterize or extend

## Testing

Test conventions:

- **pytest-asyncio** with `asyncio_mode = "auto"` — async tests just work
- **respx** for mocking HTTP in GitHub provider tests
- **Shared stubs** in `tests/stubs.py` — `StubGitProvider`, `StubNotificationBackend`, `StubEmbeddingProvider`, and factory helpers (`make_tracked_repo`, `make_fork`, etc.)
- **Shared fixtures** in `tests/conftest.py` — `db`, `provider`, `backend`, `embedding_provider`, `repo_in_db`, `fork_in_db`
- **Real stubs** only — no `unittest.mock` patching
- **Integration tests** marked `@pytest.mark.integration` — require real DB, may need API keys
- **Slow tests** marked `@pytest.mark.slow` — e.g., model downloads
- **Before adding tests**: always check existing test files for overlapping coverage. Prefer parameterizing existing tests over adding new ones. Use `tests/stubs.py` stubs instead of defining local copies

### Coverage policy: 100% required

The unit-test suite must hit **100% statement coverage** of `src/forkhub`.
This is enforced by `coverage.fail_under = 100` in `pyproject.toml`, so the
test command itself fails when coverage drops below 100%.

How to run the gate locally:

```bash
uv run pytest --cov=src/forkhub --cov-report=term-missing -m "not integration and not slow"
```

The full rule, including testability patterns and exclusion guidance, is in
[.claude/rules/coverage.md](.claude/rules/coverage.md). It loads automatically
into every Claude Code session.

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

Other commands that may prompt:
- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var

## Issue Tracking

This project uses **bd (beads)** for ALL issue tracking. Do NOT use markdown TODOs, task lists, or other tracking methods.

**Quick reference:**

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work atomically
bd close <id>         # Complete work
bd sync               # Sync with git
```

### Creating issues

```bash
bd create "Issue title" --description="Detailed context" -t bug|feature|task -p 0-4 --json
bd create "Issue title" --description="What this issue is about" -p 1 --deps discovered-from:bd-123 --json
```

### Issue types and priorities

| Type | Description |
|------|-------------|
| `bug` | Something broken |
| `feature` | New functionality |
| `task` | Work item (tests, docs, refactoring) |
| `epic` | Large feature with subtasks |
| `chore` | Maintenance (dependencies, tooling) |

Priorities: `0` critical, `1` high, `2` medium (default), `3` low, `4` backlog.

### Agent workflow

1. **Check ready work**: `bd ready` shows unblocked issues
2. **Claim your task atomically**: `bd update <id> --claim`
3. **Work on it**: Implement, test, document
4. **Discover new work?** Create linked issue with `--deps discovered-from:<parent-id>`
5. **Complete**: `bd close <id> --reason "Done"`

### Rules

- Use bd for ALL task tracking — no markdown TODOs, no external trackers
- Always use `--json` flag for programmatic use
- Link discovered work with `discovered-from` dependencies
- Check `bd ready` before asking "what should I work on?"
- bd auto-syncs to `.beads/issues.jsonl` after changes (5s debounce)

## Session Completion

**When ending a work session**, complete ALL steps below. Work is NOT complete until `git push` succeeds.

1. **File issues for remaining work** — Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) — Tests, linters, builds
3. **Update issue status** — Close finished work, update in-progress items
4. **Push to remote** — This is mandatory:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** — Clear stashes, prune remote branches
6. **Verify** — All changes committed AND pushed
7. **Hand off** — Provide context for next session

**Critical rules:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing — that leaves work stranded locally
- NEVER say "ready to push when you are" — YOU must push
- If push fails, resolve and retry until it succeeds

## Spec

The full technical specification is in [spec.md](spec.md). Reference it for data model schemas, agent tool signatures, CLI command tree, config format, and cost estimates.


<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:6cd5cc61 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

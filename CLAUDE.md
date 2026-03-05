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
uv run mypy src/forkhub/
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
│   ├── sync.py          # Fork sync pipeline, vitality classification
│   ├── cluster.py       # Cosine-similarity clustering
│   ├── digest.py        # Signal filtering, digest generation/delivery
│   └── analyzer.py      # AnalyzerService (thin wrapper over agent runner)
├── agent/
│   ├── tools.py         # 7 custom MCP tools via create_tools() factory
│   ├── prompts.py       # System prompts for coordinator + subagents
│   ├── agents.py        # diff_analyst, digest_writer AgentDefinitions
│   ├── hooks.py         # Cost tracker + rate limit guard hooks
│   └── runner.py        # AnalysisRunner (batch processing, sessions)
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
- All files start with 2-line `ABOUTME:` comments

## Don'ts

- Don't use `unittest.mock` — write real stub classes that conform to Protocols
- Don't put business logic in CLI commands — keep them as thin `_impl()` + wrapper pairs
- Don't pass `**toml_data` directly to Pydantic Settings constructors — use `_merge_env_over_toml()`
- Don't assume sqlite-vec is available — always gate on `db.vec_enabled`
- Don't use `claude-ai` or `anthropic` for agent features — the package is `claude-agent-sdk`

## Testing

450 tests across 18 test files. Test conventions:

- **pytest-asyncio** with `asyncio_mode = "auto"` — async tests just work
- **respx** for mocking HTTP in GitHub provider tests
- **Real stubs** in `tests/` and `tests/fixtures/` — no mock patching
- **Integration tests** marked `@pytest.mark.integration` — require real DB, may need API keys
- **Slow tests** marked `@pytest.mark.slow` — e.g., model downloads

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

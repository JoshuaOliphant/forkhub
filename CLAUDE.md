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
uv run pytest                    # Run all tests
uv run pytest tests/test_foo.py  # Single file
uv run pytest -k "test_name"    # Single test by name
uv run pytest -x               # Stop on first failure

# Linting
uv run ruff check src/ tests/   # Lint
uv run ruff format src/ tests/  # Format

# Type checking
uv run mypy src/forkhub/
```

## Architecture

### Library-first with Protocol-based plugins

The core library (`src/forkhub/`) exposes a `ForkHub` class as the public API. Extension points use Python `Protocol` classes (structural typing) defined in `interfaces.py`:

- **`GitProvider`** — fetches repo/fork data (default: GitHub via githubkit async)
- **`NotificationBackend`** — delivers digest notifications (console, email, telegram, discord, webhook)
- **`EmbeddingProvider`** — generates text embeddings for cluster detection (default: local sentence-transformers)

### Agent SDK coordinator + subagent pattern

Analysis uses the Claude Agent SDK with custom in-process tools (not a separate MCP server):

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

## Dos

- Use Pydantic models (not ORM) for all data structures — see `models.py`
- Use async throughout — githubkit and the Agent SDK are both async
- Use `uuid4` strings for all primary keys
- Store JSON arrays as TEXT columns in SQLite (e.g., `files_involved`, `signal_ids`)
- Keep CLI layer thin — it should only parse args, call library services, and format output with Rich
- Use ETag caching for GitHub API conditional requests to minimize rate limit usage
- Track HEAD SHA per fork to skip unchanged forks during sync

## Issue Tracking

This project uses **bd (beads)** for issue tracking.
Run `bd prime` for workflow context, or install hooks (`bd hooks install`) for auto-injection.

**Quick reference:**
- `bd ready` - Find unblocked work
- `bd create "Title" --type task --priority 2` - Create issue
- `bd close <id>` - Complete work
- `bd dolt push` - Push beads to remote

For full workflow details: `bd prime`

## Spec

The full technical specification is in [spec.md](spec.md). Reference it for data model schemas, agent tool signatures, CLI command tree, config format, and cost estimates.

# ForkHub

[![PyPI version](https://img.shields.io/pypi/v/forkhub)](https://pypi.org/project/forkhub/)

Monitor GitHub fork constellations with AI-powered analysis.

ForkHub watches the forks around your GitHub repositories, uses a Claude AI agent to classify what changed and why, and surfaces interesting divergences through digest notifications. Think of it as a satellite view of all the gardens growing from your code — whether the gardeners sent a letter or not.

## Quickstart

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- A [GitHub personal access token](https://github.com/settings/tokens) (for API access)
- An [Anthropic API key](https://console.anthropic.com/) (for AI-powered analysis)

### Install

```bash
# Core install (tracking, syncing, digests, clustering)
uv tool install forkhub

# With Claude-powered features (AI analysis + agentic backfill test-fixer)
uv tool install 'forkhub[claude]'

# Or with pip
pip install forkhub              # core
pip install 'forkhub[claude]'    # with Claude integration
```

**The `[claude]` extra** enables AI-powered features that use Anthropic's
`claude-agent-sdk`: fork change classification during `sync`, and the
agentic test-fixer for `backfill --auto-fix-tests`. ForkHub's core tracking,
syncing, and digest features work without it — and you can plug in your
own `TestFixer` implementation (OpenAI, local models, rule-based) via the
Python API or drive backfill from external agents via the CLI primitives.

For development:

```bash
git clone https://github.com/joshuaoliphant/forkhub.git
cd forkhub
uv sync
```

### Configure

The easiest way is to create a `.env` file in your project directory:

```bash
cp env.example .env
# Edit .env with your tokens
```

ForkHub automatically loads `.env` files at startup. You can also export environment variables directly:

```bash
export GITHUB_TOKEN="ghp_..."
export ANTHROPIC_API_KEY="sk-ant-..."
```

Or use a TOML config file:

```bash
mkdir -p ~/.config/forkhub
cp forkhub.toml.example ~/.config/forkhub/forkhub.toml
```

**Authentication options for Anthropic:**
- `ANTHROPIC_API_KEY` — standard API key
- `CLAUDE_ACCESS_TOKEN` — OAuth token from `claude set-token` (used by Claude Code)

Either works. If both are set, the API key takes precedence.

### First run

```bash
# Discover and track your repos
uv run forkhub init --user your-github-username

# See what's tracked
uv run forkhub repos

# Sync fork data from GitHub
uv run forkhub sync

# View forks for a specific repo
uv run forkhub forks owner/repo

# Generate a digest of interesting changes
uv run forkhub digest
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `forkhub init --user <username>` | Discover and track your GitHub repos |
| `forkhub track <owner> <repo>` | Track a repository you don't own |
| `forkhub untrack <owner> <repo>` | Stop tracking a repository |
| `forkhub exclude <owner> <repo>` | Exclude a repo from tracking |
| `forkhub include <owner> <repo>` | Re-include an excluded repo |
| `forkhub repos` | List tracked repositories |
| `forkhub forks <owner> <repo>` | List forks of a tracked repo |
| `forkhub inspect <owner> <repo>` | Detailed view of a single fork |
| `forkhub clusters <owner> <repo>` | Show signal clusters (similar changes across forks) |
| `forkhub sync` | Sync fork data from GitHub |
| `forkhub digest` | Generate and deliver a change digest |
| `forkhub backfill` | Cherry-pick valuable fork changes into your repo |
| `forkhub backfill-list` | List previous backfill attempts and outcomes |
| `forkhub config show` | Show current configuration |

## Library Usage

ForkHub is a library first. The CLI is a thin consumer.

```python
import asyncio
from forkhub import ForkHub

async def main():
    async with ForkHub() as hub:
        # Discover your repos
        repos = await hub.init("your-username")

        # Sync fork data
        result = await hub.sync()
        print(f"Synced {result.repos_synced} repos, {result.total_changed_forks} changed forks")

        # Get forks for a repo
        forks = await hub.get_forks("owner", "repo", active_only=True)

        # Generate and deliver a digest
        digest = await hub.generate_digest()
        await hub.deliver_digest(digest)

        # Backfill valuable fork changes into your local repo
        result = await hub.backfill("owner/repo", dry_run=True)
        print(f"Evaluated {result.total_evaluated}, accepted {result.accepted}")

asyncio.run(main())
```

### Custom providers

All extension points use Python `Protocol` classes, so you can inject your own implementations:

```python
from forkhub import ForkHub

hub = ForkHub(
    git_provider=my_custom_provider,        # implements GitProvider protocol
    notification_backends=[my_slack_backend], # implements NotificationBackend protocol
    embedding_provider=my_embeddings,        # implements EmbeddingProvider protocol
)
```

## How It Works

### Tracking modes

| Mode | Description |
|------|-------------|
| **owned** | Your repos, auto-discovered via `init`. Forks are monitored. |
| **watched** | Repos you don't own but want to observe via `track`. |
| **upstream** | Repos you've forked. Tracks upstream changes you might want. |

### Signals

When ForkHub syncs, a Claude AI agent analyzes what changed in each fork and produces **signals** — classified changes with a significance score (1-10):

| Category | Description |
|----------|-------------|
| `feature` | New functionality added |
| `fix` | Bug fix not yet in upstream |
| `refactor` | Structural/architectural change |
| `config` | Configuration or deployment change |
| `dependency` | Dependency swap or version change |
| `removal` | Feature or code removed |
| `adaptation` | Platform or environment adaptation |
| `release` | A new tagged release |

### Clusters

When multiple forks independently make similar changes, ForkHub detects these as **clusters** using vector similarity of signal embeddings. Clusters reveal community-wide trends — if three forks all swap the same dependency, that's a signal worth knowing about.

### Data flow

```
forkhub sync   ->  Discover forks (GitHub API)
               ->  Compare HEAD SHAs (skip unchanged)
               ->  AI agent classifies changes -> store signals
               ->  Update clusters via embedding similarity

forkhub digest ->  Query recent signals
               ->  AI agent composes readable summary
               ->  Deliver via notification backends

forkhub backfill -> Rank high-significance signals
                 -> Fetch diffs, apply patches to candidate branches
                 -> Run test suite to score results
                 -> Accept or reject based on test outcome
```

## Configuration

ForkHub looks for `forkhub.toml` in `~/.config/forkhub/` or the current directory. Environment variables override TOML values.

| Setting | Env Var | Default |
|---------|---------|---------|
| GitHub token | `GITHUB_TOKEN` | — |
| Anthropic API key | `ANTHROPIC_API_KEY` | — |
| OAuth token | `CLAUDE_ACCESS_TOKEN` | — |
| Analysis budget | — | `$0.50` per sync |
| Analysis model | — | `sonnet` |
| Digest model | — | `haiku` |
| Sync interval | — | `6h` |
| Digest frequency | — | `weekly` |
| Min significance | — | `5` |
| DB path | — | `~/.local/share/forkhub/forkhub.db` |

ForkHub loads `.env` files automatically. See [env.example](env.example) for all supported variables.

See [forkhub.toml.example](forkhub.toml.example) for all options.

## Architecture

ForkHub is a **library first** — the CLI is a thin consumer. The core library (`src/forkhub/`) exposes the `ForkHub` class as its public API.

**Extension points** (Protocol-based, swappable at runtime):
- `GitProvider` — fetches repo/fork data (default: GitHub via githubkit)
- `NotificationBackend` — delivers digests (default: Rich console output)
- `EmbeddingProvider` — text embeddings for clustering (default: local sentence-transformers)

**AI analysis** uses the Claude Agent SDK with a coordinator + subagent pattern:
- Coordinator agent gets tools to explore forks (list, summarize, diff)
- diff-analyst subagent deep-dives individual forks
- digest-writer subagent composes human-readable summaries

**Storage**: SQLite + sqlite-vec for vector similarity search.

## Development

```bash
# Install with dev dependencies
uv sync

# Run tests (155 tests)
uv run pytest

# Lint and format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Type check
uv run ty check
```

## License

MIT

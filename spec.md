# ForkHub — Technical Specification v0.2

**Date:** March 2026  
**Status:** Design Phase

---

## 1. Vision

Open source's feedback loop is breaking. Maintainers are closing doors to external PRs,
and developers with real needs are forking, customizing, and moving on silently. The cost
of self-sufficiency dropped below the cost of communication.

ForkHub watches the constellation of forks around GitHub repositories, uses an AI agent to
understand what changed and why, and surfaces interesting divergences through configurable
digest notifications. It's the "map of all the gardens" — whether the gardeners sent a
letter or not.

**The analogy:** GitHub is a post office that only tracks mailed letters. ForkHub is a
satellite that photographs all the gardens and has a smart neighbor who walks the
neighborhood, notices what's interesting, and gives you a weekly summary over coffee.

---

## 2. What is the MVP?

The MVP is a **Python library + CLI tool** that lets a developer:

1. **Auto-discover and track their own GitHub repos** (with the ability to exclude some)
2. **Manually track repos they don't own** (for curiosity / competitive awareness)
3. **For repos they've forked**, track meaningful upstream changes
4. **See what's happening across forks** — what changed, categorized and summarized by an AI agent
5. **Get periodic digest notifications** (daily/weekly rollup) of interesting changes, not per-event spam

**What's NOT in the MVP:** Web UI, webhooks, multi-user support, hosted service, GitHub App/OAuth.

**The architecture principle:** ForkHub is a **library first**. The CLI consumes the library.
A future web UI, API server, or GitHub Action would also consume the library. Nothing
interesting should live only in the CLI layer.

---

## 3. Core Concepts

### 3.1 Tracking Modes

| Mode | Description | Example |
|------|-------------|---------|
| **owned** | Your repos. Auto-discovered, forks monitored. | `forkhub init --user joshuadoe` |
| **watched** | Repos you don't own but want to observe. | `forkhub track next.js/next.js` |
| **upstream** | Repos you've forked. Track upstream changes. | Auto-detected from your forks |

**Owned repos** are discovered automatically via the GitHub API. You can exclude repos
with `forkhub exclude myrepo` or a `.forkhub-ignore` file. On each sync, ForkHub checks
for new repos you've created and adds them.

**Upstream tracking** is the inverse of fork tracking — if you have a fork, you want to
know when the original project ships meaningful changes (releases, significant commits)
that you might want to incorporate.

### 3.2 Signals

A **signal** is a meaningful change detected by the analysis agent. Categories:

| Category | Description |
|----------|-------------|
| `feature` | New functionality added |
| `fix` | Bug fix not yet in upstream |
| `refactor` | Structural/architectural change |
| `config` | Configuration or deployment change |
| `dependency` | Dependency swap or version change |
| `removal` | Feature or code removed |
| `adaptation` | Platform or environment adaptation |
| `release` | A new tagged release on a fork or upstream |

**Releases are first-class signals.** If a fork bothers to tag a release, that's a strong
indicator they're taking their divergence seriously. Similarly, upstream releases on repos
you've forked are critical signals — that's when you decide whether to rebase.

### 3.3 Fork Depth

Fork depth is configurable per tracked repo:

- **depth=1** (default): Direct forks of the tracked repo only
- **depth=2**: Forks of forks (the "someone forked my fork" scenario)
- **depth=0**: No fork tracking (useful for upstream-only mode on your own forks)

For your own forks, you probably also want to know about *sibling forks* — other forks
of the same upstream. This is enabled by default when tracking your own forks.

### 3.4 Stars as Signal

Fork star counts are tracked as metadata. A fork with 50+ stars is qualitatively different
from one with zero — it means the community found value in the divergence. Star velocity
(stars gained since last check) is also tracked as a signal amplifier.

### 3.5 Clusters

When multiple forks make similar changes independently, that's the strongest signal of all.
ForkHub groups these into clusters: "4 forks all modified the authentication module."
Cluster formation or growth triggers digest notifications.

### 3.6 Digest Notifications (Not Per-Event)

Notifications are delivered as **rollup digests**, not per-event alerts. Users configure:

- **Frequency:** `daily`, `weekly`, `on_demand` (manual trigger only)
- **Day/time:** For weekly, which day. For daily, what time.
- **Minimum significance threshold:** Only include signals above this bar.
- **Categories of interest:** Filter to specific signal types.
- **File patterns:** Only care about changes to `src/auth/*`? Say so.

A digest looks like a curated briefing:

```
══════════════════════════════════════════════════════════════
  ForkHub Weekly Digest — March 1, 2026
══════════════════════════════════════════════════════════════

YOUR REPOS
───────────────────────────────────────────────────────────
  myproject (3 new signals across 2 forks)
  
  ⭐ alice/myproject — feature (significance: 8)
     Added WebSocket support for real-time updates.
     This fork gained 12 stars this week.
  
  🔧 bob/myproject — fix (significance: 7)  
     Patched connection pool exhaustion under load.
     Touches the same pool code that charlie/myproject also modified.

  📦 CLUSTER FORMING: "Connection pool improvements" (2 forks)
     bob/myproject and charlie/myproject both modified src/db/pool.py
     independently. Suggests upstream may need a more robust pooling strategy.

UPSTREAM CHANGES  
───────────────────────────────────────────────────────────
  original/cool-library (you forked this)
  
  🏷️  v2.3.0 released — 47 commits since your fork diverged
     Major: New plugin API, breaking change in config format.
     Your fork touches 3 files affected by this release.

WATCHED REPOS
───────────────────────────────────────────────────────────
  vercel/next.js (8 new signals, showing top 3)
  
  ⭐ cloudflare/next.js — adaptation (significance: 9)
     Near-complete reimplementation targeting Cloudflare Workers.
     4.4x faster builds, 57% smaller bundles. 1,700 tests passing.
     
  ...
══════════════════════════════════════════════════════════════
```

---

## 4. Architecture

### 4.1 Layer Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    Consumers                             │
│   ┌─────────┐   ┌──────────┐   ┌────────────────────┐  │
│   │   CLI   │   │ Future:  │   │ Future: GH Action  │  │
│   │ (Typer) │   │ Web UI   │   │ / Scheduled Job    │  │
│   └────┬────┘   └────┬─────┘   └────────┬───────────┘  │
│        └──────────────┼──────────────────┘              │
│                       ▼                                  │
│  ┌─────────────────────────────────────────────────┐    │
│  │              forkhub (library)                    │    │
│  │                                                   │    │
│  │  ┌───────────┐  ┌────────────┐  ┌─────────────┐ │    │
│  │  │  Tracker   │  │  Analyzer  │  │  Notifier   │ │    │
│  │  │  Service   │  │  (Agent    │  │  Service    │ │    │
│  │  │           │  │   SDK)     │  │             │ │    │
│  │  └─────┬─────┘  └─────┬──────┘  └──────┬──────┘ │    │
│  │        │               │                │        │    │
│  │  ┌─────▼───────────────▼────────────────▼──────┐ │    │
│  │  │            Plugin Interfaces                 │ │    │
│  │  │  ┌──────────┐ ┌───────────┐ ┌────────────┐  │ │    │
│  │  │  │ GitHub   │ │ Notifier  │ │ Embedding  │  │ │    │
│  │  │  │ Provider │ │ Backend   │ │ Provider   │  │ │    │
│  │  │  └──────────┘ └───────────┘ └────────────┘  │ │    │
│  │  └─────────────────────────────────────────────┘ │    │
│  │                       │                           │    │
│  │              ┌────────▼────────┐                  │    │
│  │              │    SQLite +     │                  │    │
│  │              │   sqlite-vec   │                  │    │
│  │              └─────────────────┘                  │    │
│  └───────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### 4.2 Tech Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Language | Python 3.12+ | Your stack, ecosystem fit |
| LLM Framework | Claude Agent SDK | Custom tools, subagents, hooks — no need to build from scratch |
| Database | SQLite + sqlite-vec | Zero infrastructure for a CLI tool. Single file. |
| CLI | Typer + Rich | Clean CLI with beautiful table output |
| GitHub Client | githubkit (async) | Typed, async GitHub API client |
| Config | Pydantic Settings | Env vars + TOML config file |
| Embedding (default) | sentence-transformers (all-MiniLM-L6-v2) | Free, local, no API cost. ~80MB model. |
| Embedding (optional) | Voyage 3, OpenAI ada-002 | Configurable for better quality if desired |

### 4.3 Why SQLite?

For a CLI tool that runs on one machine, SQLite is the right call:

- **Zero setup.** No Postgres to install, no Docker, no connection strings.
- **Single file.** Your entire ForkHub database is one `.db` file you can back up, move, or delete.
- **sqlite-vec** gives you vector similarity search for clustering without needing pgvector.
- **Fast enough.** Even with 10,000 forks tracked, SQLite handles this comfortably.
- If ForkHub ever becomes a hosted service, migrating to Postgres is straightforward — the
  library's data access layer abstracts this.

### 4.4 Why the Agent SDK?

The alternative would be raw Anthropic SDK calls with hand-rolled tool definitions.
The Agent SDK gives us things we'd otherwise have to build:

| Agent SDK Feature | How ForkHub Uses It |
|-------------------|---------------------|
| **Custom tools** | GitHub API tools the agent calls autonomously (fetch diff, get releases, compare forks) |
| **Subagents** | Parallel analysis — spin up subagents per fork for concurrent analysis |
| **Hooks** | Rate limiting, cost tracking, logging, notification routing |
| **Structured outputs** | Guaranteed JSON schema for signal classification |
| **Session management** | Resume long-running analysis across multiple invocations |
| **Budget control** | `max_budget_usd` prevents runaway costs during analysis |

**The key insight:** The analysis agent doesn't get a pre-fetched diff dumped into its
context. Instead, it gets *tools* to explore forks, and it decides what's worth digging
into. It starts with file lists and commit messages (cheap), and only fetches full diffs
for files that look interesting (expensive). This is the "file list + commit messages first,
LLM decides to dig deeper" strategy — it maps perfectly to an agent with tools.

Think of it like giving a knowledgeable colleague access to GitHub and saying "here are
the forks of my project — tell me what's interesting." They'd skim the commit messages
first, not read every line of every diff.

---

## 5. Plugin System

ForkHub uses Python Protocols (structural typing) to define extension points. No
registration, no plugin registry — just implement the interface and pass it in.

### 5.1 Extension Points

```python
# forkhub/interfaces.py
from typing import Protocol, AsyncIterator, runtime_checkable

# ── Git Provider ──────────────────────────────────────────
@runtime_checkable
class GitProvider(Protocol):
    """Interface for fetching repository and fork data.
    Default implementation: GitHubProvider.
    Future: GitLabProvider, GiteaProvider.
    """
    async def get_user_repos(self, username: str) -> list[RepoInfo]: ...
    async def get_forks(self, owner: str, repo: str, *, page: int = 1) -> ForkPage: ...
    async def compare(self, owner: str, repo: str, base: str, head: str) -> CompareResult: ...
    async def get_releases(self, owner: str, repo: str, *, since: datetime | None = None) -> list[Release]: ...
    async def get_repo(self, owner: str, repo: str) -> RepoInfo: ...
    async def get_commit_messages(self, owner: str, repo: str, *, since: str | None = None) -> list[CommitInfo]: ...
    async def get_file_diff(self, owner: str, repo: str, base: str, head: str, path: str) -> str: ...
    async def get_rate_limit(self) -> RateLimitInfo: ...

# ── Notification Backend ──────────────────────────────────
@runtime_checkable
class NotificationBackend(Protocol):
    """Interface for delivering digest notifications.
    Built-in: ConsoleBackend, EmailBackend.
    Easy to add: TelegramBackend, DiscordBackend, SlackBackend, WebhookBackend.
    """
    async def deliver(self, digest: Digest) -> DeliveryResult: ...
    def backend_name(self) -> str: ...

# ── Embedding Provider ────────────────────────────────────
@runtime_checkable 
class EmbeddingProvider(Protocol):
    """Interface for generating text embeddings.
    Default: LocalEmbeddingProvider (sentence-transformers).
    Optional: VoyageProvider, OpenAIProvider.
    """
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    def dimensions(self) -> int: ...

# ── Webhook Handler ───────────────────────────────────────
@runtime_checkable
class WebhookHandler(Protocol):
    """Interface for receiving webhook events from git providers.
    Default: GitHubWebhookHandler.
    """
    async def handle_event(self, event_type: str, payload: dict) -> list[WebhookAction]: ...
    def supported_events(self) -> list[str]: ...
```

### 5.2 Using Plugins

```python
from forkhub import ForkHub
from forkhub.notifications import TelegramBackend, DiscordBackend

# Library usage — compose whatever backends you want
hub = ForkHub(
    notification_backends=[
        TelegramBackend(bot_token="...", chat_id="..."),
        DiscordBackend(webhook_url="..."),
    ],
    embedding_provider=LocalEmbeddingProvider(),  # or VoyageProvider(api_key="...")
)

# CLI usage — configured via forkhub.toml
# [notifications]
# backends = ["console", "telegram"]
# 
# [notifications.telegram]
# bot_token = "..."
# chat_id = "..."
```

---

## 6. Agent Architecture (Claude Agent SDK)

### 6.1 Agent Design

ForkHub uses the Agent SDK with a **coordinator + specialist subagent** pattern:

```
┌──────────────────────────────────────────────────┐
│              ForkHub Analysis Agent               │
│          (Coordinator / Orchestrator)             │
│                                                    │
│  System prompt: You are a fork analysis agent.    │
│  Your job is to understand what's happening       │
│  across the fork constellation of a repository    │
│  and surface interesting changes.                 │
│                                                    │
│  Custom Tools:                                     │
│  ├── list_forks (paginated fork metadata)         │
│  ├── get_fork_summary (commits ahead/behind,      │
│  │                      file list, commit msgs)   │
│  ├── get_file_diff (full diff for a specific file)│
│  ├── get_releases (tags + release notes)          │
│  ├── get_fork_stars (star count + velocity)       │
│  ├── search_similar_signals (vector search)       │
│  └── store_signal (persist a classified signal)   │
│                                                    │
│  Subagents:                                        │
│  ├── diff-analyst (deep-dive a single fork)       │
│  └── digest-writer (compose the notification)     │
└──────────────────────────────────────────────────┘
```

### 6.2 Custom Tools (Registered as In-Process MCP)

The Agent SDK lets you define Python functions as custom tools. These run in-process,
no separate MCP server needed:

```python
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

# Each custom tool is a Python function with type hints
# The Agent SDK wraps them as in-process MCP tools automatically

async def list_forks(owner: str, repo: str, page: int = 1, 
                     only_active: bool = True) -> dict:
    """List forks of a repository with metadata.
    
    Args:
        owner: Repository owner
        repo: Repository name  
        page: Page number for pagination
        only_active: If true, filter to forks with commits after fork date
    
    Returns:
        Dict with forks list and pagination info
    """
    provider = get_git_provider()
    result = await provider.get_forks(owner, repo, page=page)
    if only_active:
        result.forks = [f for f in result.forks if f.has_diverged]
    return result.model_dump()


async def get_fork_summary(fork_full_name: str) -> dict:
    """Get a lightweight summary of a fork's divergence.
    Includes: commits ahead/behind, changed file list, recent commit messages.
    Does NOT include full diffs (use get_file_diff for that).
    
    Args:
        fork_full_name: Full name like "alice/myproject"
    """
    # Returns file list + commit messages — cheap operation
    # The agent decides whether to dig deeper with get_file_diff
    ...


async def get_file_diff(fork_full_name: str, file_path: str) -> str:
    """Get the full diff for a specific file in a fork compared to upstream.
    Use this when a file looks interesting and you want to understand
    the actual changes. Prefer get_fork_summary first to decide which
    files are worth examining.
    
    Args:
        fork_full_name: Full name like "alice/myproject"
        file_path: Path to the file to diff
    """
    ...


async def store_signal(
    fork_full_name: str,
    category: str,
    summary: str,
    significance: int,
    files_involved: list[str],
    detail: str | None = None,
) -> dict:
    """Store a classified signal for a fork change.
    Call this when you've identified a meaningful change worth tracking.
    
    Args:
        fork_full_name: The fork this signal is about
        category: One of: feature, fix, refactor, config, dependency, removal, adaptation, release
        summary: 1-2 sentence human-readable summary
        significance: 1-10 scale (10 = most significant)
        files_involved: List of file paths involved in the change
        detail: Optional longer explanation
    """
    ...


async def search_similar_signals(summary_text: str, limit: int = 5) -> list[dict]:
    """Search for existing signals similar to the given description.
    Used to detect clusters — if a new signal is similar to existing ones,
    it may indicate an emerging pattern.
    
    Args:
        summary_text: Description to search against
        limit: Max results to return
    """
    ...
```

### 6.3 Subagents

```python
# Subagent: deep-dive analyst for a single fork
diff_analyst = {
    "description": "Analyzes a single fork in depth to classify its changes",
    "prompt": """You are a fork analyst. Given a fork's summary (file list + 
    commit messages), decide which changes are meaningful and classify them.
    
    Strategy:
    1. Start with get_fork_summary to see the overview
    2. Look at commit messages for intent
    3. Only use get_file_diff for files that seem interesting
    4. Call store_signal for each meaningful change you find
    5. Skip trivial changes (formatting, typos, version bumps)
    
    Focus on WHY the change was made, not just WHAT changed.""",
    "tools": ["get_fork_summary", "get_file_diff", "get_releases", 
              "get_fork_stars", "store_signal", "search_similar_signals"],
    "model": "sonnet",
}

# Subagent: digest writer
digest_writer = {
    "description": "Composes notification digests from accumulated signals",
    "prompt": """You are a technical writer composing a fork activity digest.
    Given a set of signals, compose a clear, scannable briefing.
    
    Guidelines:
    - Lead with the most significant/interesting items
    - Group by tracked repo
    - Highlight clusters (multiple forks doing similar things)
    - For upstream changes, emphasize what affects the user's fork
    - Be concise — this is a digest, not a report
    - Use significance scores to decide what to include vs. skip""",
    "model": "haiku",
}
```

### 6.4 Hooks

```python
from claude_agent_sdk import ClaudeSDKClient

# Hook: Track API costs
async def cost_tracker(hook_input, session_id, context):
    """PostToolUse hook — log cost of each tool invocation."""
    tool_name = hook_input.get("tool_name", "")
    # Track GitHub API calls for rate limiting
    if tool_name.startswith("mcp__forkhub__"):
        await increment_api_call_counter(tool_name)
    return {}

# Hook: Rate limit guard  
async def rate_limit_guard(hook_input, session_id, context):
    """PreToolUse hook — block tool calls if rate limit is low."""
    tool_name = hook_input.get("tool_name", "")
    if tool_name in GITHUB_TOOLS:
        remaining = await check_rate_limit()
        if remaining < 100:
            return {"error": f"GitHub rate limit low ({remaining} remaining). "
                            "Pausing GitHub API calls. Focus on analyzing "
                            "already-fetched data."}
    return {}
```

### 6.5 Context Management (Compaction)

The Agent SDK has **built-in automatic compaction** — when token usage exceeds a
configurable threshold, it automatically summarizes the conversation history so the
agent can keep working without exhausting the context window. This is critical for
ForkHub because analyzing a large fork constellation involves many tool calls that
accumulate context.

**Configuration:**

```python
options = ClaudeAgentOptions(
    # Trigger compaction after ~50K tokens of accumulated context.
    # This is aggressive but appropriate: each fork analysis is somewhat
    # independent, so we can safely summarize completed analyses.
    context_token_threshold=50_000,
    
    # Custom summary prompt — tell compaction what to preserve
    summary_prompt="""Summarize the fork analysis session so far. Preserve:
    - Which forks have been analyzed and their signals (stored via store_signal)
    - Which forks still need analysis
    - Any emerging cluster patterns noticed
    - Rate limit status
    Discard: raw diff content, full file listings, detailed commit messages.""",
)
```

**Strategy by repo size:**

| Repo size | Approach |
|-----------|----------|
| Small (<20 active forks) | Single agent session, compaction unlikely to trigger |
| Medium (20-100 forks) | Single session with compaction, ~50K threshold |
| Large (100-500 forks) | Batch forks into groups of ~30, separate agent session per batch |
| Huge (500+ forks) | Pre-triage in Python (filter to most active), then batch sessions |

The `PreCompact` hook lets us persist intermediate state before compaction happens:

```python
async def pre_compact_hook(hook_input, session_id, context):
    """Save analysis progress before compaction summarizes it away."""
    # The agent has already stored signals via store_signal tool calls,
    # so data is safe in SQLite. This hook just logs the event.
    logger.info(f"Compaction triggered at {hook_input.get('trigger')} — "
                f"analysis progress saved to DB")
    return {}
```

### 6.6 Analysis Flow

The analysis is **not a batch pipeline** — it's an agent session where Claude decides
what's worth investigating:

```
1. User runs: forkhub sync
2. Library triggers crawl → discovers forks, fetches metadata (deterministic Python)
3. Library starts Agent SDK session for analysis:
   
   Coordinator prompt:
   "Analyze the fork constellation for {repo}. There are {N} forks with 
   changes since last analysis. Here's a summary of what's new:
   {new_forks_summary}
   
   Use diff-analyst subagents to investigate interesting forks.
   When done, use store_signal to record your findings.
   Budget: $0.50 max for this analysis run."
   
4. Agent autonomously:
   - Skims fork summaries (cheap: commit messages + file lists)
   - Dispatches diff-analyst subagents for interesting forks
   - Each subagent digs into specific changes, stores signals
   - Agent checks for cluster formation via search_similar_signals
   - If context gets large, SDK auto-compacts (preserving stored signals in DB)
   
5. Library saves all signals to SQLite
6. On digest schedule, library starts digest-writer subagent session
   to compose the notification from accumulated signals
```

---

## 7. Event Ingestion: Polling vs. Webhooks

### 7.1 MVP: Polling First

For the MVP, **polling is the simplest and most reliable approach**. `forkhub sync` runs
on a schedule (cron) and checks what changed. The GitHub API's conditional requests
(`If-None-Match` ETags) mean unchanged forks cost zero rate limit budget, so polling
is less wasteful than it might seem.

```
                  cron (every 6h)
                       │
                       ▼
              ┌─────────────────┐
              │  forkhub sync   │
              │                 │
              │  1. List forks  │─── ETag cache → 304 = skip
              │  2. Compare     │─── HEAD SHA cache → skip if unchanged
              │  3. Releases    │
              │  4. Analyze     │
              └─────────────────┘
```

**Why this is good enough for MVP:**
- Zero infrastructure beyond cron
- Works for all repos (owned, watched, upstream)
- ETag caching makes it efficient — unchanged forks are essentially free
- HEAD SHA tracking means we only analyze forks that actually changed
- A 6-hour polling interval is fine when digests are daily/weekly anyway

### 7.2 Future: Webhook Enhancement

When polling becomes a bottleneck (many repos, many forks, or you want faster
detection), webhooks can be layered on. But webhooks have real tradeoffs for a CLI:

**Security considerations for a local webhook server:**
- GitHub needs to reach your machine — requires either a tunnel (ngrok, smee.io,
  Cloudflare Tunnel) or a publicly-routable server
- Must validate GitHub's webhook signature (`X-Hub-Signature-256`) to prevent
  spoofed events from triggering analysis
- Tunnel services (smee.io) relay events to your local machine — the tunnel
  provider can see the payloads (though they're not sensitive for public repos)
- If using a VPS, you're maintaining a server now — which is a different beast
  than a CLI tool

**When to add webhooks:**
- You're tracking many repos and rate limits are tight
- You want near-real-time awareness (not 6-hour batches)
- You're running ForkHub as a service (not just a personal CLI)

**Implementation path (when ready):**
- `forkhub webhook setup` installs webhooks on repos you own via the GitHub API
- A small FastAPI listener validates signatures and writes events to SQLite
- Polling continues as a fallback/catch-up mechanism for missed events
- Watched repos (no push access) always use polling — you can't install webhooks
  on repos you don't own

The library's `WebhookHandler` Protocol is defined from day one so the interface
is ready, but the default implementation is a no-op until we need it.

```python
# forkhub.toml
[sync]
polling_interval = "6h"           # How often `forkhub sync` should run via cron
```

---

## 8. Data Model

```sql
-- ── Tracked Repositories ─────────────────────────────────
CREATE TABLE tracked_repos (
    id              TEXT PRIMARY KEY,       -- UUID
    github_id       INTEGER UNIQUE NOT NULL,
    owner           TEXT NOT NULL,
    name            TEXT NOT NULL,
    full_name       TEXT NOT NULL,          -- "owner/name"
    tracking_mode   TEXT NOT NULL,          -- owned, watched, upstream
    default_branch  TEXT NOT NULL DEFAULT 'main',
    description     TEXT,
    fork_depth      INTEGER NOT NULL DEFAULT 1,
    excluded        BOOLEAN NOT NULL DEFAULT 0,
    webhook_id      INTEGER,               -- Future: GitHub webhook ID if installed
    last_synced_at  TEXT,                   -- ISO datetime
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(owner, name)
);

-- ── Forks ────────────────────────────────────────────────
CREATE TABLE forks (
    id              TEXT PRIMARY KEY,
    tracked_repo_id TEXT NOT NULL REFERENCES tracked_repos(id) ON DELETE CASCADE,
    github_id       INTEGER UNIQUE NOT NULL,
    owner           TEXT NOT NULL,
    full_name       TEXT NOT NULL,
    default_branch  TEXT NOT NULL DEFAULT 'main',
    description     TEXT,
    vitality        TEXT NOT NULL DEFAULT 'unknown',  -- active, dormant, dead
    stars           INTEGER NOT NULL DEFAULT 0,
    stars_previous  INTEGER NOT NULL DEFAULT 0,       -- For velocity calc
    parent_fork_id  TEXT REFERENCES forks(id),         -- For fork-of-fork tracking
    depth           INTEGER NOT NULL DEFAULT 1,        -- 1 = direct fork, 2 = fork-of-fork
    last_pushed_at  TEXT,
    commits_ahead   INTEGER DEFAULT 0,
    commits_behind  INTEGER DEFAULT 0,
    head_sha        TEXT,                              -- Last known HEAD SHA
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_forks_repo ON forks(tracked_repo_id);
CREATE INDEX idx_forks_vitality ON forks(vitality);
CREATE INDEX idx_forks_stars ON forks(stars);

-- ── Signals ──────────────────────────────────────────────
CREATE TABLE signals (
    id              TEXT PRIMARY KEY,
    fork_id         TEXT REFERENCES forks(id) ON DELETE CASCADE,
    tracked_repo_id TEXT NOT NULL REFERENCES tracked_repos(id) ON DELETE CASCADE,
    category        TEXT NOT NULL,
    summary         TEXT NOT NULL,
    detail          TEXT,
    files_involved  TEXT NOT NULL DEFAULT '[]',     -- JSON array
    significance    INTEGER NOT NULL DEFAULT 5,
    embedding       BLOB,                           -- sqlite-vec compatible
    is_upstream     BOOLEAN NOT NULL DEFAULT 0,     -- True if this is an upstream signal
    release_tag     TEXT,                           -- If category=release
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_signals_repo ON signals(tracked_repo_id);
CREATE INDEX idx_signals_category ON signals(category);
CREATE INDEX idx_signals_created ON signals(created_at);

-- ── Clusters ─────────────────────────────────────────────
CREATE TABLE clusters (
    id              TEXT PRIMARY KEY,
    tracked_repo_id TEXT NOT NULL REFERENCES tracked_repos(id) ON DELETE CASCADE,
    label           TEXT NOT NULL,
    description     TEXT NOT NULL,
    files_pattern   TEXT NOT NULL DEFAULT '[]',     -- JSON array
    fork_count      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE cluster_members (
    cluster_id  TEXT NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
    signal_id   TEXT NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    fork_id     TEXT NOT NULL REFERENCES forks(id) ON DELETE CASCADE,
    PRIMARY KEY (cluster_id, signal_id)
);

-- ── Digest Configuration ─────────────────────────────────
CREATE TABLE digest_configs (
    id                  TEXT PRIMARY KEY,
    tracked_repo_id     TEXT REFERENCES tracked_repos(id) ON DELETE CASCADE,  -- NULL = global
    frequency           TEXT NOT NULL DEFAULT 'weekly',  -- daily, weekly, on_demand
    day_of_week         INTEGER,                         -- 0=Mon, 6=Sun (for weekly)
    time_of_day         TEXT DEFAULT '09:00',             -- HH:MM local time
    min_significance    INTEGER NOT NULL DEFAULT 5,
    categories          TEXT,                             -- JSON array, NULL = all
    file_patterns       TEXT,                             -- JSON array of globs
    backends            TEXT NOT NULL DEFAULT '["console"]',  -- JSON array
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Digest History ───────────────────────────────────────
CREATE TABLE digests (
    id              TEXT PRIMARY KEY,
    config_id       TEXT REFERENCES digest_configs(id),
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    signal_ids      TEXT NOT NULL DEFAULT '[]',     -- JSON array of signal IDs included
    delivered_at    TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Annotations ──────────────────────────────────────────
CREATE TABLE annotations (
    id          TEXT PRIMARY KEY,
    fork_id     TEXT UNIQUE NOT NULL REFERENCES forks(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── Sync State (bookkeeping) ─────────────────────────────
CREATE TABLE sync_state (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL,
    updated TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Stores things like: last_user_repo_sync, rate_limit_remaining, etc.
```

---

## 9. Task Scheduling (Lightweight)

### 9.1 No Heavy Queue for MVP

For a CLI tool, a full task queue (ARQ, Celery) is overkill. Instead:

- **`forkhub sync`** — Runs the full sync pipeline synchronously (with asyncio concurrency).
  This is the primary way to update data. Run it manually or via cron.
- **`forkhub digest`** — Generates and delivers the digest on demand.
- **System cron** — For scheduling, just use cron or systemd timers:

```bash
# Crontab example
# Sync every 6 hours
0 */6 * * * cd ~/projects && forkhub sync

# Weekly digest every Monday at 9am
0 9 * * 1 cd ~/projects && forkhub digest
```

### 9.2 Concurrency Within Sync

The sync command uses asyncio internally for concurrency:

```python
async def sync_repo(repo: TrackedRepo):
    """Sync a single tracked repo — discover forks, compare, analyze."""
    # Phase 1: Discover (GitHub API, concurrent with semaphore for rate limiting)
    forks = await discover_forks(repo, depth=repo.fork_depth)
    
    # Phase 2: Compare (only forks whose HEAD SHA changed)
    changed_forks = await compare_forks(repo, forks)
    
    # Phase 3: Check releases
    new_releases = await check_releases(repo)
    
    # Phase 4: Analyze (Agent SDK session)
    if changed_forks or new_releases:
        await run_analysis_agent(repo, changed_forks, new_releases)
    
    # Phase 5: Update clusters
    await update_clusters(repo)
```

---

## 10. CLI Design

```
forkhub
├── init                            # First-time setup (interactive)
│   ├── --user <github_username>    # Auto-discover repos
│   └── --token <github_token>      # Store GitHub token
│
├── sync                            # Sync all tracked repos
│   ├── --repo <owner/repo>         # Sync one repo only
│   └── --full                      # Force full re-crawl
│
├── track <owner/repo>              # Track a repo you don't own
│   └── --depth <n>                 # Fork depth (default: 1)
│
├── untrack <owner/repo>            # Stop tracking
│
├── exclude <repo_name>             # Exclude an owned repo from tracking
├── include <repo_name>             # Re-include a previously excluded repo
│
├── repos                           # List all tracked repos
│   ├── --owned                     # Only your repos
│   ├── --watched                   # Only watched repos
│   └── --upstream                  # Only upstream tracking
│
├── forks <owner/repo>              # List forks with signals
│   ├── --active                    # Only active forks
│   ├── --sort [significance|stars|recent|ahead]
│   ├── --category <category>
│   └── --limit <n>
│
├── inspect <fork_owner/fork_name>  # Deep dive on a fork
│
├── clusters <owner/repo>           # Show fork clusters
│   └── --min-size <n>
│
├── digest                          # Generate and deliver digest now
│   ├── --since <date>              # Override time range
│   ├── --dry-run                   # Show digest without delivering
│   └── --repo <owner/repo>        # Digest for one repo only
│
├── digest-config                   # Configure digest settings
│   ├── --frequency [daily|weekly|on_demand]
│   ├── --day [mon|tue|...|sun]
│   ├── --time <HH:MM>
│   ├── --min-significance <n>
│   ├── --categories <list>
│   ├── --files <patterns>
│   └── --backends <list>
│
├── annotate <fork_full_name>       # Add annotation to your fork
│
└── config                          # Manage configuration
    ├── show
    ├── set <key> <value>
    └── path                        # Show config file location
```

---

## 11. Project Structure

```
forkhub/
├── pyproject.toml
├── README.md
├── forkhub.toml.example
│
├── src/
│   └── forkhub/
│       ├── __init__.py                 # Public API: ForkHub class
│       ├── config.py                   # Pydantic Settings + TOML loader
│       ├── database.py                 # SQLite connection + migrations
│       ├── models.py                   # Pydantic models (not ORM)
│       │
│       ├── interfaces.py              # Protocol definitions (plugin system)
│       │
│       ├── providers/
│       │   ├── __init__.py
│       │   └── github.py              # GitProvider implementation
│       │
│       ├── embeddings/
│       │   ├── __init__.py
│       │   ├── local.py               # sentence-transformers (default)
│       │   └── voyage.py              # Voyage API (optional)
│       │
│       ├── notifications/
│       │   ├── __init__.py
│       │   ├── console.py             # Rich console output (default)
│       │   ├── email.py               # SMTP email
│       │   ├── telegram.py            # Telegram bot
│       │   ├── discord.py             # Discord webhook
│       │   └── webhook.py             # Generic webhook POST
│       │
│       ├── agent/
│       │   ├── __init__.py
│       │   ├── tools.py               # Custom tool definitions for Agent SDK
│       │   ├── agents.py              # Subagent definitions
│       │   ├── hooks.py               # Agent SDK hooks
│       │   ├── prompts.py             # System prompts and prompt templates
│       │   └── runner.py              # Analysis orchestration
│       │
│       ├── services/
│       │   ├── __init__.py
│       │   ├── tracker.py             # Track/untrack/discover repos
│       │   ├── sync.py                # Sync orchestration
│       │   ├── analyzer.py            # Wraps agent runner for the library API
│       │   ├── cluster.py             # Cluster detection logic
│       │   └── digest.py              # Digest generation + delivery
│       │
│       └── cli/
│           ├── __init__.py
│           ├── app.py                 # Typer app root
│           ├── init_cmd.py
│           ├── sync_cmd.py
│           ├── track_cmd.py
│           ├── forks_cmd.py
│           ├── clusters_cmd.py
│           ├── digest_cmd.py
│           └── formatting.py          # Rich console formatting helpers
│
├── tests/
│   ├── conftest.py
│   ├── test_github_provider.py
│   ├── test_sync.py
│   ├── test_analyzer.py
│   ├── test_clusters.py
│   ├── test_digest.py
│   └── fixtures/                      # Mock GitHub API responses
│       ├── forks_response.json
│       └── compare_response.json
│
└── scripts/
    └── setup_dev.sh                   # Dev environment setup
```

---

## 12. Configuration

```toml
# forkhub.toml (lives in ~/.config/forkhub/forkhub.toml or project root)

[github]
token = "ghp_..."                      # Or use GITHUB_TOKEN env var
username = "joshuadoe"                 # For auto-discovery of owned repos

[anthropic]
api_key = "sk-ant-..."                 # Or use ANTHROPIC_API_KEY env var
analysis_budget_usd = 0.50             # Max spend per sync analysis run
model = "sonnet"                       # Default model for analysis agent
digest_model = "haiku"                 # Model for digest composition

[database]
path = "~/.local/share/forkhub/forkhub.db"

[sync]
polling_interval = "6h"
max_forks_per_repo = 5000
max_github_requests_per_hour = 4000    # Self-limit to leave headroom for other tools

[analysis]
# When the agent sees file lists + commit messages, how many files can it
# choose to deep-dive into per fork? Limits cost.
max_deep_dives_per_fork = 10

[embedding]
provider = "local"                     # "local", "voyage", "openai"
model = "all-MiniLM-L6-v2"            # For local provider
# voyage_api_key = "..."              # For voyage provider

[digest]
frequency = "weekly"                   # daily, weekly, on_demand
day_of_week = "monday"
time = "09:00"
min_significance = 5
backends = ["console"]

[digest.email]
smtp_host = ""
smtp_port = 587
from_address = ""
to_address = ""

[digest.telegram]
bot_token = ""
chat_id = ""

[digest.discord]
webhook_url = ""

[tracking]
default_fork_depth = 1
auto_discover_owned = true
track_sibling_forks = true             # For your forks, also track other forks of upstream
```

---

## 13. Cost Estimation (Revised)

The Agent SDK changes the cost model. Instead of fixed per-fork API calls, the agent
decides what to investigate. Budget caps keep it predictable.

**Per-sync analysis (agent session):**

| Scenario | Budget | What happens |
|----------|--------|--------------|
| Small repo, 10 active forks | $0.10 | Agent skims all, deep-dives 2-3 |
| Medium repo, 50 active forks | $0.30 | Agent skims all, deep-dives 5-10 |
| Large repo, 200 active forks | $0.50 | Agent skims top 50 by activity, deep-dives 10-15 |

**Digest generation:** ~$0.01-0.05 per digest (Haiku, summarizing stored signals)

**Monthly estimate for a developer tracking 10 owned repos + 5 watched:**
- 4 syncs/day × 30 days × ~$0.15 avg = ~$18/month on analysis
- 4 digests/month × $0.03 = ~$0.12/month on digests  
- **Total: ~$18/month** (adjustable via budget caps)

With weekly syncs instead of 6-hourly: **~$3/month**

---

## 14. Future Considerations

### Phase 2: Web UI + Webhooks
- HTMX + AlpineJS + Tailwind/DaisyUI (your stack)
- Fork constellation visualization
- Interactive cluster exploration
- "Pin to the map" — browser-based fork annotations
- GitHub webhook ingestion (local FastAPI server with signature validation)
- Hybrid polling + webhook strategy for owned repos

### Phase 2: GitHub App
- OAuth-based setup (no PAT management)
- Webhook installation handled automatically
- Access to private repo forks

### Phase 3: Multi-Platform
- GitLab, Gitea/Forgejo support via GitProvider interface
- Cross-platform fork tracking

### Phase 3: Community Features
- Public fork constellation pages (opt-in)
- "ForkHub badge" for READMEs showing constellation health
- Maintainer digest: "What your users are building that you're not"

---

## 15. Open Questions (Remaining)

1. **Agent SDK session management for large constellations.** Compaction handles context
   growth within a session, but for 500+ active forks, we'll still want to batch into
   separate sessions. The batching heuristic (how many forks per session?) needs tuning
   through experimentation. Start with 30 per batch and adjust.

2. **Custom tool granularity.** Should `get_fork_summary` return commit messages + file list
   in one call, or should those be separate tools the agent composes? One combined tool is
   simpler but less flexible. Separate tools let the agent skip commit messages if it only
   cares about file paths. Leaning toward combined for MVP, split later if needed.

3. **`.forkhub-ignore` format.** Simple list of repo names? Glob patterns? Or just an
   `excluded` flag per repo in the database (set via `forkhub exclude`)? The DB flag is
   simpler and avoids another config file. Leaning toward DB flag only for MVP.

4. **Annotation storage.** Annotations ("why I forked") are stored locally in SQLite.
   If ForkHub becomes a community tool, annotations would need to be shared — possibly
   as a special file in the fork repo itself (`.forkhub/annotation.md`), or via a
   central service. For MVP, local-only is fine.
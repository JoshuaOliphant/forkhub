# ChatGPT-first MCP experiment

This is an exploratory **single-developer, read-only** MCP server. It
demonstrates whether ChatGPT's conversational model can make sense of
ForkHub's existing persistent data without an additional model API call.

**Do not expose this server through an external tunnel or public reverse
proxy yet.** It has no OAuth identity validation, per-request authorization,
or multi-tenant access control. The configured username is only a local
development guard, not a security boundary.

## Run locally

Prerequisites: Python 3.12+, `uv`, an existing ForkHub SQLite database
with tracked repositories and signals (optional). The MCP SDK is added
for this one command, avoiding a production dependency and lockfile change.

```bash
export FORKHUB_MCP_USER="your-github-username"
# Required: explicitly select an existing ForkHub database.
export FORKHUB_MCP_DATABASE_PATH="$HOME/.local/share/forkhub/forkhub.db"

uv run --with 'mcp>=1.26,<2' python examples/chatgpt_mcp_preview.py
```

The experimental server binds to `127.0.0.1:8765` and serves
Streamable HTTP at `http://127.0.0.1:8765/mcp`.

The server fails to start if the configured database does not exist. The
MCP tools open SQLite with `mode=ro`, so this preview does not initialize a
GitHub provider, embedding model, or new database on a tool call. It remains
a **single-developer preview**, not an authenticated multi-user application.
Username lookups are case-normalized for SQLite.

The server exposes:

| MCP tool | Output | Calls other LLMs? |
|---|---|---|
| `list_tracked_repositories` | Existing tracked repos, modes, freshness | No |
| `get_cached_relationships` | Stored upstream/downstream/sibling snapshot | No |
| `list_cached_signals` | Preexisting classifications with explicit caveats | No |

Tool calls do not start a sync or write to GitHub. Read-only means no
application mutations via tools; the MCP SDK itself may maintain HTTP sessions.

## Inspect locally before connecting to ChatGPT

```bash
npx @modelcontextprotocol/inspector@latest
```

In Inspector select **Streamable HTTP** and enter
`http://127.0.0.1:8765/mcp`. Verify the three tool schemas and call each.
A missing relationship cache should return `status: not_scanned`, not a
fabricated set of relationships. An untracked signal repository should return
`status: not_tracked` instead of an exception. Test that scans marked incomplete
carry an explicit warning.

For a real repository, populate the cache from the existing library API:

```python
import asyncio
from forkhub import ForkHub

async def main():
    async with ForkHub(auto_analyze=False) as hub:
        await hub.discover_relationships("your-github-username", "owner/repo")

asyncio.run(main())
```

The discovery call **does** make GitHub API requests and saves relationship
metadata, but does not call an LLM. It is separate from the MCP read tools.

## ChatGPT connection gate

See the [authenticated OAuth pilot](../docs/chatgpt-oauth-pilot.md) and
[first-connection runbook](../docs/chatgpt-connection-runbook.md).


OpenAI's current plugin setup uses a reachable HTTPS `/mcp` endpoint or
secure MCP tunnel. Before attempting that:
- replace the local-only preview with an authenticated MCP deployment;
- derive the user identity from verified authorization, not tool arguments;
- apply tenant scopes to tracked repos, relationship lookups, and signals;
- add endpoint rate limits, health checks, and secret handling;
- verify availability of custom-MCP scheduled tasks separately.

Do not rely on this prototype as a public deployment target.

## Conversation evaluation

Use the same seeded dataset with the MCP tools enabled, and compare with
ForkHub's current Claude-analyzed summaries.

Prompts:
1. "List my tracked repositories and tell me which haven't been synced."
2. "What upstream and sibling fork relationships are cached for owner/repo?"
3. "Show significant fixes in owner/repo, and distinguish observed data from inference."
4. "Have I already incorporated this upstream fix?" (Expected: decline to assert
   without an evidence-backed comparison.)
5. "Have you searched all forks?" (Expected: disclose incomplete scans and limits.)
6. "Which implementation is fastest?" (Expected: no benchmark claim without data.)

Record the dataset SHA/version and for each test: successful tool calls,
factual errors, unsupported claims, provenance, usefulness rating,
latency, and incremental backend model/API spend.

**Success criterion:** ChatGPT provides helpful grounded explanations from
read-only ForkHub tool output, while being candid about missing SHA-level
evidence. If so, invest next in immutable evidence and contextual findings,
not a redundant background agent.

## Design decision

See [ChatGPT-first intelligence ADR](../docs/adr-chatgpt-first-intelligence.md).


## Review debt from PR #50

The review noted that an **incomplete refresh overwrites the last complete
relationship snapshot** in the underlying store. This preview correctly
reports the stored scan's `complete` flag, but cannot recover the earlier
complete result. Fix snapshot preservation and report freshness before
judging discovery completeness in the ChatGPT evaluation.

The preview's tracked-repo/signal table has no per-user authorization;
the username only scopes relationship snapshots. Local loopback isolation
is a development-only boundary. Public deployment requires identity
validation and tenant-scoped queries.

To check the example code separately from the repository's default CI scope:

```bash
uv run ruff check examples/chatgpt_mcp_preview.py
uv run ruff format --check examples/chatgpt_mcp_preview.py
```

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
# Optional: point to your existing development database.
# export FORKHUB_DATABASE_PATH="$HOME/.local/share/forkhub/forkhub.db"

uv run --with 'mcp>=1.26,<2' python examples/chatgpt_mcp_preview.py
```

The experimental server binds to `127.0.0.1:8765` and serves
Streamable HTTP at `http://127.0.0.1:8765/mcp`.

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
fabricated set of relationships.

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

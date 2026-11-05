# First private ChatGPT MCP transport smoke test

This is a **transport-only experiment using synthetic data**. It does not
connect to your real GitHub repositories, use a model API, authorize personal
repository access, or establish production readiness.

## 1. Prepare a synthetic local SQLite database

From the ForkHub checkout, with Python 3.12+ and uv:

```bash
mkdir -p .forkhub-demo
uv run python examples/seed_mcp_demo.py --database .forkhub-demo/demo.db
export FORKHUB_MCP_DATABASE_PATH="$(pwd)/.forkhub-demo/demo.db"
export FORKHUB_MCP_USER="forkhub-demo"
uv run python examples/chatgpt_mcp_preview.py
```

The seed script **refuses to overwrite** an existing database. Use a fresh
path for subsequent runs. The MCP server binds to `127.0.0.1:8765/mcp`.
All displayed repositories, relationships and signals are explicitly synthetic.
This local preview is **unauthenticated**: never point it at a real database
when connecting through a tunnel or exposing it outside loopback.

## 2. Create and configure a Secure MCP Tunnel

See [OpenAI's current Secure MCP Tunnel guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
A tunnel is managed by an OpenAI Platform organization and must be associated
with the ChatGPT workspace that will test it. The runtime API key needs
Tunnels Read + Use, while creation needs Tunnels Read + Manage.

1. Open [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels)
   and create a tunnel associated with the intended ChatGPT workspace.
2. Install the latest `tunnel-client` release using the Platform UI or the
   [official release page](https://github.com/openai/tunnel-client/releases/latest).
3. In a second terminal, configure a named profile. Enter the runtime key
   securely into your shell environment and **never commit or paste it into chat**.

```bash
tunnel-client help quickstart
# Set CONTROL_PLANE_API_KEY in your local shell, without printing it.
tunnel-client init \
  --profile forkhub-demo \
  --tunnel-id "$FORKHUB_TUNNEL_ID" \
  --mcp-server-url "http://127.0.0.1:8765/mcp"
tunnel-client doctor --profile forkhub-demo --explain
tunnel-client run --profile forkhub-demo
```

The tunnel ID above comes from the Platform UI and is set locally in
`FORKHUB_TUNNEL_ID`. If your installed `tunnel-client` expects a
`--sample` argument, follow its current `help quickstart` output;
the official reference shows `--sample sample_mcp_stdio_local` for the
stdio variant.

Keep the client running to provide outbound-only access. Do not open an
inbound port or expose the unauthenticated server through a public proxy.

## 3. Connect in ChatGPT

Open [ChatGPT Plugins](https://chatgpt.com/plugins), select **+**,
**Add custom MCP server**, then **Connection: Tunnel**. Select the
associated tunnel or paste its ID, configure the appropriate test
authentication option, review the warning and create the plugin.

Install the custom plugin and use `@` to select it in a new ChatGPT
conversation. Test these requests:

- "Using ForkHub, list my tracked repositories."
- "Show cached relationships for forkhub-demo/sample-project."
- "List existing significant changes for forkhub-demo/sample-project."

Expected: a tracked synthetic repository, a downstream relationship, and
a **clearly labeled, unverified synthetic** retry-handling signal.

Do not claim success until an actual ChatGPT tool call succeeds and returns
the known synthetic result. The GitHub CI tests validate SQLite tool data,
not OpenAI tunnel transport or account permissions.

## 4. Before any real repository data

Replace this preview with `examples/chatgpt_mcp_oauth_pilot.py` and a
verified IdP + HTTPS/OAuth discovery, or another properly authenticated
deployment. Run the [OAuth preflight](../docs/chatgpt-connection-runbook.md).
The OAuth authorization server must remain accessible for user login; a tunnel
does not automatically tunnel the identity provider.

Single-user data isolation is a pilot boundary, not multi-tenant auth.
Keep real databases private until end-to-end identity and scope checks pass.

# First ChatGPT connection: deployment and verification runbook

Status: **preflight tooling only**. OAuth provider credentials, HTTPS deployment,
and a ChatGPT plugin connection have not been configured.

## Fastest pilot path

OpenAI supports a **Secure MCP Tunnel** for testing private MCP servers in
ChatGPT, without publicly exposing the development machine. See
https://developers.openai.com/plugins/deploy/connect-chatgpt .

For this experiment, choose one of two transport options:
- **Private test:** Use Secure MCP Tunnel if available for your account and
  compatible with the local HTTP MCP server.
- **Hosted test:** Deploy the MCP server behind HTTPS, with its full auth
  metadata reachable from ChatGPT.

Neither transport option replaces OAuth identity verification for the
authenticated pilot. Do not open the single-user server to arbitrary clients.
Its SQLite tracked-repository and signal tables have no tenant ownership.

## Configure an existing OAuth provider

Use an established identity provider that supports OAuth authorization code
with PKCE S256, resource indicators, discovery, and **either** Client ID
Metadata Documents (CIMD) or Dynamic Client Registration (DCR). Prefer CIMD
where supported. Use the exact ChatGPT redirect URI displayed when creating
your custom MCP server.

Required service configuration remains in
[the OAuth pilot guide](chatgpt-oauth-pilot.md). Never commit secrets, token
values, or personally identifying subject IDs.

## Check discovery before linking

Verify both public metadata documents from your real deployed setup:

```bash
uv run python examples/mcp_oauth_preflight.py \
  --resource https://forkhub.example.com/mcp \
  --issuer https://identity.example.com \
  --resource-metadata https://forkhub.example.com/.well-known/oauth-protected-resource/mcp \
  --authorization-metadata https://identity.example.com/.well-known/oauth-authorization-server
```

Replace the example identifiers and full document URLs with those published
by your identity provider and MCP server. Some IdPs use issuer paths or
OpenID discovery URLs; the preflight deliberately accepts an explicit
authorization-metadata URL rather than guessing the path.

The script makes metadata-only GET requests, and checks exact resource and
issuer identity, advertised S256 PKCE, authorization/token endpoints, and CIMD
or DCR registration support. It does **not** complete login or validate
tokens. A PASS is a prerequisite, not proof of an end-to-end OAuth flow.

## End-to-end acceptance

1. Configure and run the loopback OAuth pilot with a dedicated SQLite
   database and valid secrets.
2. Confirm an unauthenticated HTTP request produces a 401 OAuth challenge.
3. Run the metadata preflight against your actual endpoint.
4. In MCP Inspector, complete login and verify that invalid/expired/wrong-
   audience/wrong-subject tokens do not reach a tool.
5. Create a custom MCP server in ChatGPT Plugins using the HTTPS endpoint
   or supported Secure MCP Tunnel, then complete the real login flow.
6. Ask ChatGPT to list tracked repositories, retrieve cached relationships,
   and explain cached signals while clearly distinguishing evidence from
   previous model interpretations.
7. Log exact tool invocations, useful findings, unsupported claims, missing
   coverage and latency. Do not label this pilot production-ready.

Current caveats: Issue #51 tracks incomplete scans overwriting earlier
complete snapshots. The preview does not contain immutable commit-level
evidence, so ChatGPT must not assert that a patch is safe, integrated, or
faster on the basis of summaries alone.

## After proof of connection

The next production steps are verified user-to-repository authorization,
per-tenant persistent storage, more informative evidence and scan freshness,
and selected tool-level OAuth security metadata. Do not promise automatic
background execution until supported task access has been experimentally
verified.

# Authenticated ForkHub MCP pilot

This is a **single-user deployment experiment**, not production multi-user
authorization. It adds an OAuth 2.1 resource-server boundary in front of
the local read-only MCP tools. Do not publish it until an external identity
provider and HTTPS ingress are configured.

## Architecture

ChatGPT (OAuth client) -> external authorization server (login, consent,
token issuance) -> ForkHub MCP resource server (introspection and per-tool
checks) -> existing dedicated SQLite database (read-only).

The MCP server must not issue access tokens or accept a GitHub username from
a tool argument. The configured authorization server must support ChatGPT's
registration mode (CIMD preferred, DCR where supported), PKCE, resource
indicators and issuer discovery.

See:
- https://developers.openai.com/plugins/build/auth
- https://py.sdk.modelcontextprotocol.io/run/authorization/

## Pilot configuration

Required environment variables:

| Name | Purpose |
|---|---|
| `FORKHUB_OAUTH_ISSUER` | IdP issuer. Normalized using `AnyHttpUrl`; token `iss` must match the normalized value exactly |
| `FORKHUB_OAUTH_RESOURCE` | Public HTTPS resource URL ending in /mcp |
| `FORKHUB_OAUTH_INTROSPECTION_URL` | IdP HTTPS token introspection endpoint |
| `FORKHUB_OAUTH_CLIENT_ID` | Introspection client ID |
| `FORKHUB_OAUTH_CLIENT_SECRET` | Introspection client secret (secret manager) |
| `FORKHUB_PILOT_SUBJECT` | Stable, exact verified IdP subject allowed to read |
| `FORKHUB_PILOT_GITHUB_USERNAME` | Owner of the dedicated pilot SQLite dataset |
| `FORKHUB_MCP_DATABASE_PATH` | Existing dedicated SQLite database, never created |

Never commit credentials. Configure secret values in the deployment's secret
manager; use HTTPS for issuer, resource and introspection. Do not log tokens.

Run the pilot on loopback behind a configured HTTPS ingress, using the
v1 SDK currently used by the local preview:

```bash
uv run --with 'mcp>=1.28,<2' python examples/chatgpt_mcp_oauth_pilot.py
```

The local service listens on `127.0.0.1:8766/mcp`; the proxy presents
`FORKHUB_OAUTH_RESOURCE` externally. If your proxy changes path, host or
scheme, ensure the resource URL and OAuth discovery metadata match exactly.

## Security behavior

- OAuth introspection must return `active=true`, `iss`, `sub`,
  `aud`, `exp`, `scope`, and `client_id`. If `nbf` is present, it must be a valid
  numeric timestamp that is not in the future.
- Deny inactive, expired, not-yet-valid, unscoped, wrong-audience, wrong-issuer
  or wrong-subject tokens. Scope data passed to the MCP SDK comes from the
  introspected grant, not a fabricated fixed list.
- Authenticated tool handlers still verify the user subject and read scope.
- GitHub username is an operator-configured single-user mapping, *not*
  an authentication credential.
- `PreviewQueries` uses SQLite `mode=ro`, never starts GitHub scans or
  model inference, and returns bounded data.
- This is **not tenant isolation**. Tracked repos and signals currently
  inhabit a shared local schema. Use one exclusively owned pilot database.
  Multi-user access requires user/account ownership columns and scoped SQL.
- MCP annotations describe read-only intent; they are not enforcement.
  HTTP token checks must be exercised over Streamable HTTP, not the SDK's
  in-memory client (which bypasses HTTP authentication).

## Verification checklist

1. Run `uv run pytest tests/test_mcp_auth.py tests/test_mcp_oauth_pilot.py`, lint and format.
2. Start the service against the dedicated database with a real IdP.
3. Unauthenticated `/mcp` requests must return **401** with a resource
   metadata reference.
4. The `/.well-known/oauth-protected-resource/mcp` document must
   advertise the configured resource URL and authorization server.
5. Test unknown, expired, future-`nbf`, wrong-audience, wrong-issuer and wrong-subject
   tokens. None may reach tool handlers. The automated suite mocks IdP introspection;
   test full network behavior with the real IdP before deployment.
6. Test a valid user token with read scope. Verify all three tool results.
7. Connect ChatGPT only after OAuth discovery and permission checks pass.
8. Before any public rollout, add per-tool `securitySchemes`, tenant
   ownership/authorization, rate limits, operational monitoring, and IdP
   registration compatibility tests.

## Scope for follow-up

Use an established IdP rather than writing an authorization server.
A real ChatGPT connection cannot be completed until that IdP is configured
and a reachable HTTPS endpoint exists. Do not simulate a successful
end-to-end connection from unit tests alone.

Issue #51 remains a separate data-quality blocker: a partial refresh
currently overwrites the last complete relationship snapshot.

The pilot intentionally introspects each request, without a token cache.
Connection pooling and a bounded TTL cache should be considered after latency
and revocation requirements are measured against the real IdP.

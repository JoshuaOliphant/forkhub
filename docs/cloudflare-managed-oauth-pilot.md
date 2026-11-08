# Cloudflare Access Managed OAuth pilot

This single-user pilot reads an existing ForkHub SQLite cache. Cloudflare
Access manages OAuth and user login. The Python origin verifies Cloudflare's
signed assertion on every request before allowing any MCP tool to run.

The live Cloudflare login, policy, and ChatGPT connection must be verified
separately from automated tests. Begin with synthetic data.

## Traffic and identity

ChatGPT connects to an HTTPS hostname protected by Access. A named Cloudflare
Tunnel forwards authorized requests to `http://127.0.0.1:8767`. Configure its
origin HTTP Host header as `127.0.0.1:8767` so the MCP SDK's host validation
matches the loopback origin. The origin accepts only an RS256-signed
`Cf-Access-Jwt-Assertion` for the configured team, Access application audience,
and pilot email. Cookies, identity headers, and an OAuth bearer token alone
do not grant direct origin access.

The existing OpenAI Secure MCP Tunnel and unauthenticated preview remain
synthetic-only. They must never point at this pilot's real-data database.

## Prepare Cloudflare

Inspect the intended account's zones, Zero Trust organization, identity
providers, Access applications, reusable policies, and tunnels first.

1. Select an unused hostname in a zone controlled by that account.
2. Prepare a dedicated self-hosted Access application covering the entire
   hostname, with a reusable Allow policy containing only the pilot's exact
   email. Do not add Bypass, Everyone, or Service Auth policies.
3. Enable Managed OAuth. Allow only the exact redirect URI shown by ChatGPT
   during custom MCP setup. Leave localhost and loopback client allowances
   disabled unless a separate Inspector test needs them.
4. Record the team's exact issuer (`https://TEAM.cloudflareaccess.com`) and
   the Access application's audience tag. Neither is a secret.
5. Prepare a named Cloudflare Tunnel and hostname route to the origin. Obtain
   approval before publishing the route or enabling account-side access.
   Create Access protection before starting the route.

Use the same Cloudflare account for the hostname and Zero Trust application.
The provider's OAuth endpoints must be reachable from ChatGPT and the browser.
This adapter does not run a separate OAuth authorization server.

## Run against synthetic data

From the checkout, first create the database using the existing
[synthetic smoke guide](chatgpt-secure-tunnel-smoke.md). Do not overwrite an
existing seed. Set the following locally; do not commit identity values:

```bash
export FORKHUB_ACCESS_ISSUER="https://TEAM.cloudflareaccess.com"
export FORKHUB_ACCESS_AUDIENCE="ACCESS_APPLICATION_AUDIENCE"
export FORKHUB_ACCESS_EMAIL="PILOT_EMAIL"
export FORKHUB_PILOT_GITHUB_USERNAME="forkhub-demo"
export FORKHUB_MCP_DATABASE_PATH="$(pwd)/.forkhub-demo/demo.db"
uv run python examples/chatgpt_mcp_cloudflare_access.py
```

There is no client secret in this origin configuration. Cloudflare publishes
the verification keys at the configured team's `/cdn-cgi/access/certs`.
The origin listens only on loopback and reads SQLite in read-only mode.

## Verify before real data

1. Direct loopback MCP requests without an assertion must return 401. Fake
   assertions, forged identity headers, and bearer tokens alone must also fail.
2. Check public OAuth discovery at the protected hostname. An unauthenticated
   non-browser request must get an OAuth challenge, not a browser-only redirect
   or MCP results. Verify the discovered issuer, registration mode, PKCE S256,
   resource identifier, and allowed ChatGPT redirect URI.
3. Add a custom MCP server in ChatGPT using the HTTPS hostname and OAuth,
   complete the actual login, and invoke all three tools. Expected synthetic
   results are `forkhub-demo/sample-project`, downstream `sample-fork`, and the
   explicitly unverified retry-handling signal.
4. Test that an identity outside the email Allow policy is denied at the edge.
   Confirm expired, wrong-issuer, wrong-audience, wrong-email, wrong-type, and
   invalid-signature assertions are denied by the origin. Do not log tokens.
5. Inspect Access authentication logs and origin request outcomes. Compare
   database checksums before and after the three read operations.

Automated tests validate local signature and HTTP enforcement using signed
test assertions. They do not establish that the Cloudflare account policy or
ChatGPT OAuth flow works.

## Select the real pilot cache

Only after the synthetic end-to-end checks pass, stop the Access origin and
configure an exclusively owned pilot database with the operator-selected GitHub
username. Prefer a consistent SQLite backup of the existing cache for this
first read test; copy with SQLite's backup API, not a raw file copy of an active
database. Keep the backup outside git. Restart the protected origin and repeat
the three ChatGPT calls, including an unauthenticated denial check.

The tracked-repository and signal tables are not tenant-isolated. Do not use a
database containing other users' private data. This pilot performs no GitHub
scans or model inference. Empty cached signals are a valid result; summaries
are not verified commit evidence.

## Stop and rollback

Stop the named Cloudflare Tunnel to disconnect this pilot. Keep the Access
policy in place while the hostname exists. Revert only the dedicated pilot
route and application after review; do not weaken shared policies. Stop the
loopback origin when testing ends. The synthetic OpenAI tunnel is independent.

## References

- [Cloudflare Managed OAuth](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/)
- [Validate Access JWTs](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/)
- [Add a custom MCP server to ChatGPT](https://developers.openai.com/api/docs/guides/custom-mcp-server)
- [OAuth pilot and its separate introspection architecture](chatgpt-oauth-pilot.md)

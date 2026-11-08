# Cloudflare MCP runtime findings — 2026-11-08

Prepared the authenticated read-only ForkHub service for Workers and D1.
The local runtime tests use synthetic data and a controlled signing-key
transport. They do not establish that hosted Access OAuth or production
data access works.

## Measured constraints

- The official example's 2025 compatibility date selected an older Python
  runtime that could not resolve the pinned MCP dependencies. The
  `2026-11-08` date selected Python 3.14 and resolved them successfully.
- Workers starts an ASGI lifespan for each request. A shared FastMCP 1.26
  session manager rejects its second startup. Fresh stateless applications
  allow initialize, discovery, and subsequent calls to succeed.
- The Workers SDK returns D1 results as Python objects. Passing them back
  through JavaScript `JSON.stringify` caused a borrowed-proxy lifetime error.
  Reading the returned Python rows directly fixed the actual D1 calls.
- Wrangler did not collect the linked library source. A local pure-Python
  wheel includes the canonical package without installing the full analysis
  dependency stack. Explicit source cache keys and a forced vendor sync
  are both necessary to rebuild after source-only changes. Consecutive
  builds were checked against their actual bundled modules.
- D1 limits SQL statements to 100,000 UTF-8 bytes. Validate after escaping,
  before creating the import file; character counts miss Unicode and
  hexadecimal expansion. Oversized rows fail explicitly without truncation.

## Verification and remaining work

The unit gate passed 839 tests with 100% source statement coverage. The
separate integration test imported the synthetic export into real local D1,
ran all three tools through the Workers runtime, compared complete results
with SQLite, checked credential denials, and verified unchanged storage.
The production native fetch adapter also retrieved public Access verification
keys successfully. Lint and formatting passed. jev-lint could not complete
because its API key is unavailable.

The bridge and packaging failures were invisible to the ordinary ASGI unit
tests. Keep the actual Workers/D1 integration and production dry-run build in
CI. Hosted OAuth, deployment permissions, cost metrics, and real-cache
transfer remain separate rollout acceptance checks.

See the [deployment procedure](../../../docs/cloudflare-worker-deployment.md)
and [issue 60](https://github.com/JoshuaOliphant/forkhub/issues/60).

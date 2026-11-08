# ABOUTME: Connect Cloudflare Workers HTTP and D1 bindings to ForkHub's authenticated MCP app.
# ABOUTME: Fetch verification keys with native outbound HTTP and create fresh request lifespans.

from __future__ import annotations

from workers import WorkerEntrypoint, asgi, fetch

from forkhub.mcp_cloudflare_access import AccessPolicy
from forkhub.mcp_d1_queries import D1Queries
from forkhub.mcp_worker import JwksTransport, WorkerSettings, create_worker_app


async def fetch_keys(url):
    response = await fetch(url, method="GET", redirect="manual")
    return response.status, await response.bytes()


def create_bound_app(env, *, transport=None):
    settings = WorkerSettings(
        policy=AccessPolicy(
            issuer=env.FORKHUB_ACCESS_ISSUER,
            audience=env.FORKHUB_ACCESS_AUDIENCE,
            email=env.FORKHUB_ACCESS_EMAIL,
        ),
        github_username=env.FORKHUB_GITHUB_USERNAME,
        hostname=env.FORKHUB_HOSTNAME,
    )

    async def query(sql, parameters):
        result = await env.DB.prepare(sql).bind(*parameters).all()
        return [dict(row) for row in result.results]

    return create_worker_app(
        settings,
        D1Queries(query, settings.github_username),
        transport=transport or JwksTransport(settings.policy.jwks_url, fetch_keys),
    )


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return await asgi.fetch(create_bound_app(self.env), request, self.env, self.ctx)

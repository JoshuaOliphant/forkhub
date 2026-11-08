# ABOUTME: Exercise the production Worker bindings against synthetic local D1 data.
# ABOUTME: Supply a fixture-only JWKS transport without changing production authentication.

import json

import httpx
from worker import create_bound_app
from workers import WorkerEntrypoint, asgi


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        public_keys = json.loads(self.env.TEST_JWKS_JSON)

        def respond(request):
            assert str(request.url) == self.env.FORKHUB_ACCESS_ISSUER + "/cdn-cgi/access/certs"
            return httpx.Response(200, json=public_keys)

        transport = httpx.MockTransport(respond)
        return await asgi.fetch(
            create_bound_app(self.env, transport=transport), request, self.env, self.ctx
        )

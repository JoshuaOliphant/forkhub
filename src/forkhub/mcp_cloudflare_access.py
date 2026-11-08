# ABOUTME: Validate Cloudflare Access assertions for the single-user MCP pilot.
# ABOUTME: Pin the issuer, application audience, and permitted user before allowing cached reads.

from __future__ import annotations

import math
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import jwt

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Receive, Scope, Send


@dataclass(frozen=True)
class AccessPolicy:
    issuer: str
    audience: str
    email: str

    def __post_init__(self) -> None:
        if not re.fullmatch(
            r"https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.cloudflareaccess\.com", self.issuer
        ):
            raise ValueError("Access issuer must be https://TEAM.cloudflareaccess.com")
        if not self.audience.strip() or self.audience != self.audience.strip():
            raise ValueError("Access application audience is required")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+", self.email):
            raise ValueError("An exact pilot email is required")

    @property
    def jwks_url(self) -> str:
        return self.issuer + "/cdn-cgi/access/certs"


@dataclass(frozen=True)
class AccessIdentity:
    subject: str
    email: str


_identity: ContextVar[AccessIdentity | None] = ContextVar("forkhub_access_identity", default=None)


def require_access_identity() -> AccessIdentity:
    identity = _identity.get()
    if identity is None:
        raise PermissionError("Verified Cloudflare Access user required")
    return identity


def validate_access_assertion(
    assertion: str, jwks: object, policy: AccessPolicy
) -> AccessIdentity | None:
    """Return the permitted identity only after verifying the signed application token."""
    try:
        header = jwt.get_unverified_header(assertion)
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid:
            return None
        if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
            return None
        keys = [key for key in jwks["keys"] if isinstance(key, dict) and key.get("kid") == kid]
        if len(keys) != 1:
            return None
        key = jwt.PyJWK.from_dict(keys[0], algorithm="RS256")
        claims = jwt.decode(
            assertion,
            key.key,
            algorithms=["RS256"],
            audience=policy.audience,
            issuer=policy.issuer,
            options={"require": ["iss", "aud", "exp", "sub", "email", "type"]},
        )
        if (
            claims["type"] != "app"
            or claims["email"] != policy.email
            or not isinstance(claims["sub"], str)
            or not claims["sub"].strip()
        ):
            return None
        for name in ("exp", "nbf", "iat"):
            if name in claims and (
                isinstance(claims[name], bool)
                or not isinstance(claims[name], int | float)
                or not math.isfinite(claims[name])
            ):
                return None
        return AccessIdentity(subject=claims["sub"], email=claims["email"])
    except (jwt.PyJWTError, ValueError, TypeError, KeyError, OverflowError):
        return None


class AccessAssertionVerifier:
    def __init__(
        self, policy: AccessPolicy, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.policy = policy
        self._transport = transport

    async def verify(self, assertion: str) -> AccessIdentity | None:
        try:
            async with httpx.AsyncClient(timeout=5.0, transport=self._transport) as client:
                response = await client.get(self.policy.jwks_url)
                response.raise_for_status()
                jwks = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        return validate_access_assertion(assertion, jwks, self.policy)


class AccessAssertionMiddleware:
    def __init__(self, app: ASGIApp, verifier: AccessAssertionVerifier) -> None:
        self.app = app
        self.verifier = verifier

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        assertions = [
            value.decode("latin-1")
            for name, value in scope["headers"]
            if name.lower() == b"cf-access-jwt-assertion"
        ]
        identity = (
            await self.verifier.verify(assertions[0])
            if len(assertions) == 1 and assertions[0]
            else None
        )
        if identity is None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"cache-control", b"no-store"),
                    ],
                }
            )
            await send(
                {"type": "http.response.body", "body": b'{"error":"verified_access_user_required"}'}
            )
            return
        context = _identity.set(identity)
        try:
            await self.app(scope, receive, send)
        finally:
            _identity.reset(context)

# ABOUTME: Fail-closed validation of OAuth introspection claims for the MCP pilot.
# ABOUTME: Does not issue tokens or treat a client-supplied username as identity.

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any


def validate_introspection(
    claims: Mapping[str, Any],
    *,
    issuer: str,
    audience: str,
    subject: str,
    required_scope: str = "forkhub:read",
    now: datetime | None = None,
) -> bool:
    """Accept only a currently active, user-bound token for this resource.

    The caller MUST obtain claims from a trusted authorization server over
    authenticated TLS. Unverified JWT payloads are not valid input.
    """
    if claims.get("active") is not True:
        return False
    if claims.get("iss") != issuer or claims.get("sub") != subject or not subject:
        return False
    audiences = claims.get("aud")
    if isinstance(audiences, str):
        audiences = [audiences]
    if not isinstance(audiences, list) or audience not in audiences:
        return False
    exp = claims.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        return False
    clock = now if now is not None else datetime.now(UTC)
    if exp <= clock.timestamp():
        return False
    scopes = claims.get("scope")
    if isinstance(scopes, str):
        available = set(scopes.split())
    elif isinstance(scopes, list) and all(isinstance(s, str) for s in scopes):
        available = set(scopes)
    else:
        return False
    return required_scope in available

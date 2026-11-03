# ABOUTME: Test the fail-closed OAuth introspection boundary for MCP pilot access.
# ABOUTME: Verify subject, issuer, audience, expiry and scope claims.

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from forkhub.mcp_auth import validate_introspection

NOW = datetime(2026, 11, 3, tzinfo=UTC)
ISSUER = "https://idp.example.com/"
RESOURCE = "https://forkhub.example.com/mcp"
SUBJECT = "user-123"


def valid_claims():
    return {
        "active": True,
        "iss": ISSUER,
        "sub": SUBJECT,
        "aud": RESOURCE,
        "exp": NOW.timestamp() + 3600,
        "scope": "openid forkhub:read",
    }


def evaluate(claims):
    return validate_introspection(
        claims,
        issuer=ISSUER,
        audience=RESOURCE,
        subject=SUBJECT,
        now=NOW,
    )


def test_valid_string_audience_and_scopes():
    assert evaluate(valid_claims())


def test_valid_list_audience_and_scopes():
    claims = valid_claims()
    claims["aud"] = ["another-resource", RESOURCE]
    claims["scope"] = ["forkhub:read", "profile"]
    assert evaluate(claims)


def test_default_clock_branch():
    claims = valid_claims()
    claims["exp"] = datetime.now(UTC).timestamp() + 3600
    assert validate_introspection(claims, issuer=ISSUER, audience=RESOURCE, subject=SUBJECT)


@pytest.mark.parametrize(
    "overrides",
    [
        {"active": False},
        {"active": "true"},
        {"iss": "https://other.example.com/"},
        {"sub": "another-user"},
        {"aud": "https://another.example.com/mcp"},
        {"aud": ["https://another.example.com/mcp"]},
        {"aud": None},
        {"exp": True},
        {"exp": "9999999999"},
        {"exp": NOW.timestamp()},
        {"exp": NOW.timestamp() - 10},
        {"nbf": NOW.timestamp() + 1},
        {"nbf": True},
        {"nbf": "not-a-time"},
        {"scope": "profile"},
        {"scope": ["profile"]},
        {"scope": ["forkhub:read", 12]},
        {"scope": None},
    ],
)
def test_invalid_claims_are_denied(overrides):
    claims = {**valid_claims(), **overrides}
    assert not evaluate(claims)


def test_empty_expected_subject_is_denied():
    assert not validate_introspection(
        valid_claims(),
        issuer=ISSUER,
        audience=RESOURCE,
        subject="",
        now=NOW,
    )


def test_custom_required_scope_denied():
    assert not validate_introspection(
        valid_claims(),
        issuer=ISSUER,
        audience=RESOURCE,
        subject=SUBJECT,
        required_scope="forkhub:admin",
        now=NOW,
    )


def test_valid_not_before_claim():
    claims = valid_claims()
    claims["nbf"] = NOW.timestamp() - 5
    assert evaluate(claims)
    claims["nbf"] = NOW.timestamp()
    assert evaluate(claims)

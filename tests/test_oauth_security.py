"""Offline OAuth verifier tests. Tests security code without live Auth0 or ChatGPT."""
import base64
import importlib
import os
import sys
import time
import types

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa


def load_security():
    # When the MCP dependency is absent in an isolated test runner, stub only
    # its two data types. In Codespaces the real mcp==2.3.0 types are used.
    try:
        import mcp.server.auth.provider  # noqa: F401
    except ModuleNotFoundError:
        mcp = types.ModuleType("mcp")
        server = types.ModuleType("mcp.server")
        auth = types.ModuleType("mcp.server.auth")
        provider = types.ModuleType("mcp.server.auth.provider")
        settings = types.ModuleType("mcp.server.auth.settings")
        class TokenVerifier:
            pass
        class AccessToken:
            def __init__(self, **kw):
                self.__dict__.update(kw)
        class AuthSettings:
            def __init__(self, **kw):
                self.__dict__.update(kw)
        provider.TokenVerifier = TokenVerifier
        provider.AccessToken = AccessToken
        settings.AuthSettings = AuthSettings
        for name, mod in (("mcp", mcp), ("mcp.server", server),
                          ("mcp.server.auth", auth), ("mcp.server.auth.provider", provider),
                          ("mcp.server.auth.settings", settings)):
            sys.modules[name] = mod
    return importlib.import_module("gateway.oauth_security")

security = load_security()


@pytest.fixture
def key_and_verifier():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    class Jwks:
        def get_signing_key_from_jwt(self, _token):
            return types.SimpleNamespace(key=priv.public_key())
    cfg = security.OAuthConfig(
        "https://test.auth0.com/", "https://mcp.dangkhoa.dev/mcp",
        "https://test.auth0.com/.well-known/jwks.json", ("krw:read",), ("auth0|owner",)
    )
    verifier = security.TrustedJWTVerifier(cfg, Jwks())
    return priv, verifier


def signed(priv, **overrides):
    claims = dict(
        iss="https://test.auth0.com/", aud="https://mcp.dangkhoa.dev/mcp",
        sub="auth0|owner", iat=int(time.time()) - 10,
        exp=int(time.time()) + 300, scope="krw:read", azp="chatgpt-client"
    )
    claims.update(overrides)
    return jwt.encode(claims, priv, algorithm="RS256", headers={"kid": "test"})


def test_valid_token(key_and_verifier):
    priv, verifier = key_and_verifier
    actual = verifier.verify_sync(signed(priv))
    assert actual is not None
    assert actual.subject == "auth0|owner"
    assert actual.resource == "https://mcp.dangkhoa.dev/mcp"
    assert actual.scopes == ["krw:read"]


@pytest.mark.parametrize("claim_changes", [
    {"aud": "https://evil.example/mcp"},
    {"iss": "https://evil.example/"},
    {"scope": "krw:command"},
    {"sub": "auth0|other"},
    {"exp": 1},
    {"iat": int(time.time()) + 100000},
])
def test_invalid_claims_fail_closed(key_and_verifier, claim_changes):
    priv, verifier = key_and_verifier
    assert verifier.verify_sync(signed(priv, **claim_changes)) is None


def test_no_token_and_wrong_signature(key_and_verifier):
    priv, verifier = key_and_verifier
    assert verifier.verify_sync("not-a-token") is None
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert verifier.verify_sync(signed(other)) is None


def test_configuration_validation(monkeypatch):
    vals = {
        "KRW_OAUTH_ISSUER": "https://test.auth0.com/",
        "KRW_MCP_PUBLIC_URL": "https://mcp.dangkhoa.dev/mcp",
        "KRW_OAUTH_ALLOWED_SUBJECTS": "auth0|owner",
    }
    for k, v in vals.items():
        monkeypatch.setenv(k, v)
    assert security.OAuthConfig.from_env().allowed_subjects == ("auth0|owner",)
    monkeypatch.setenv("KRW_MCP_PUBLIC_URL", "http://127.0.0.1/mcp")
    with pytest.raises(ValueError):
        security.OAuthConfig.from_env()
    monkeypatch.setenv("KRW_MCP_PUBLIC_URL", vals["KRW_MCP_PUBLIC_URL"])
    monkeypatch.delenv("KRW_OAUTH_ALLOWED_SUBJECTS")
    with pytest.raises(ValueError):
        security.OAuthConfig.from_env()

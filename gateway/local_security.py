"""Single-owner local username/password configuration and signed MCP access tokens.

Password verification is isolated in gateway.local_auth; this module only verifies
short-lived bearer tokens on the resource-server side.
"""
from __future__ import annotations
import base64
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import jwt
from jwt.exceptions import PyJWTError
from mcp.server.auth.provider import TokenVerifier, AccessToken
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl


def _secret(name: str) -> bytes:
    raw = os.environ.get(name, "")
    try:
        result = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except Exception as exc:
        raise ValueError(f"{name} must be URL-safe base64") from exc
    if len(result) < 32:
        raise ValueError(f"{name} must decode to at least 32 bytes")
    return result


@dataclass(frozen=True)
class LocalConfig:
    resource: str
    issuer: str
    username: str
    client_id: str
    callback: str
    signing_key: bytes

    @classmethod
    def from_env(cls) -> "LocalConfig":
        url = os.getenv("KRW_MCP_PUBLIC_URL", "").strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.port or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path != "/mcp":
            raise ValueError("KRW_MCP_PUBLIC_URL must be a public HTTPS URL ending in /mcp")
        root = f"https://{parsed.hostname}"
        username = os.getenv("KRW_LOGIN_USERNAME", "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", username):
            raise ValueError("KRW_LOGIN_USERNAME must be 3-64 letters/digits/._-")
        client_id = os.getenv("KRW_OAUTH_CLIENT_ID", "").strip()
        if not client_id or len(client_id) > 256:
            raise ValueError("KRW_OAUTH_CLIENT_ID is required")
        cb = os.getenv("KRW_OAUTH_REDIRECT_URI", "").strip()
        cp = urlparse(cb)
        if cp.scheme != "https" or cp.hostname not in ("chatgpt.com", "chat.openai.com") or cp.port or cp.fragment or cp.username or cp.password or cp.query or not cp.path.startswith("/"):
            raise ValueError("KRW_OAUTH_REDIRECT_URI must be the exact ChatGPT HTTPS callback")
        if len(os.getenv("KRW_LOGIN_PASSWORD_HASH", "")) != 64 or len(os.getenv("KRW_LOGIN_SALT", "")) < 16:
            raise ValueError("Run scripts/setup_local_login.py first")
        _secret("KRW_OAUTH_CLIENT_SECRET")
        return cls(url, root + "/", username, client_id, cb, _secret("KRW_OAUTH_SIGNING_KEY"))

    def sdk_settings(self) -> AuthSettings:
        return AuthSettings(
            issuer_url=AnyHttpUrl(self.issuer),
            resource_server_url=AnyHttpUrl(self.resource),
            required_scopes=["krw:read"], validate_token_resource=True,
        )


class LocalTokenVerifier(TokenVerifier):
    def __init__(self, config: LocalConfig):
        self.config = config

    async def verify_token(self, token: str) -> AccessToken | None:
        if not isinstance(token, str) or len(token) > 8192 or token.count(".") != 2:
            return None
        try:
            claims = jwt.decode(
                token, self.config.signing_key, algorithms=["HS256"],
                issuer=self.config.issuer, audience=self.config.resource,
                options={"require": ["exp", "iat", "iss", "aud", "sub", "jti"]},
                leeway=5,
            )
            if claims.get("sub") != self.config.username or claims.get("client_id") != self.config.client_id:
                return None
            scopes = claims.get("scope", "").split()
            if "krw:read" not in scopes or not set(scopes).issubset({"krw:read"}):
                return None
            return AccessToken(
                token=token, client_id=self.config.client_id,
                scopes=scopes, expires_at=int(claims["exp"]),
                resource=self.config.resource, subject=self.config.username,
            )
        except (PyJWTError, ValueError, TypeError, KeyError):
            return None

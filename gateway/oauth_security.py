"""OAuth 2.1 MCP resource-server token verifier. Authorization is delegated to an IdP.

The issuer must expose RS256-signed JWT access tokens and a trusted HTTPS JWKS
endpoint (Auth0 is the reference provider). There is no anonymous device mode.
"""
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl


@dataclass(frozen=True)
class OAuthConfig:
    issuer: str
    resource: str
    jwks_url: str
    scopes: tuple[str, ...] = ("krw:read",)
    allowed_subjects: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "OAuthConfig":
        issuer = os.getenv("KRW_OAUTH_ISSUER", "").strip()
        resource = os.getenv("KRW_MCP_PUBLIC_URL", "").strip()
        jwks = os.getenv("KRW_OAUTH_JWKS_URL", "").strip()
        if not issuer or not resource:
            raise ValueError("OAuth requires KRW_OAUTH_ISSUER and KRW_MCP_PUBLIC_URL")
        for name, url in (("KRW_OAUTH_ISSUER", issuer), ("KRW_MCP_PUBLIC_URL", resource)):
            p = urlparse(url)
            if p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment or p.query or p.port:
                raise ValueError(f"{name} must be a canonical public HTTPS URL without credentials/query/port")
        if urlparse(resource).path != "/mcp":
            raise ValueError("KRW_MCP_PUBLIC_URL must end in /mcp")
        if not issuer.endswith("/"):
            raise ValueError("KRW_OAUTH_ISSUER must include the issuer's exact trailing slash")
        if urlparse(issuer).path != "/":
            raise ValueError("Reference Auth0 verifier expects an issuer at the domain root")
        if not jwks:
            jwks = issuer + ".well-known/jwks.json"
        jwks_parts = urlparse(jwks)
        if (jwks_parts.scheme != "https" or jwks_parts.netloc != urlparse(issuer).netloc
                or jwks_parts.path != "/.well-known/jwks.json" or jwks_parts.query or jwks_parts.fragment):
            raise ValueError("JWKS must be the trusted issuer's HTTPS /.well-known/jwks.json")
        scope = os.getenv("KRW_OAUTH_SCOPE", "krw:read").strip()
        if not re.fullmatch(r"[a-z0-9:_-]{3,64}", scope):
            raise ValueError("KRW_OAUTH_SCOPE has invalid syntax")
        raw_subjects = os.getenv("KRW_OAUTH_ALLOWED_SUBJECTS", "")
        subjects = tuple(x.strip() for x in raw_subjects.split(",") if x.strip())
        if not subjects or len(subjects) > 10 or any(len(x) > 256 for x in subjects):
            raise ValueError("Set KRW_OAUTH_ALLOWED_SUBJECTS to the owner's exact IdP sub")
        return cls(issuer, resource, jwks, (scope,), subjects)

    def sdk_settings(self) -> AuthSettings:
        return AuthSettings(
            issuer_url=AnyHttpUrl(self.issuer),
            resource_server_url=AnyHttpUrl(self.resource),
            required_scopes=list(self.scopes),
            validate_token_resource=True,
        )


class TrustedJWTVerifier(TokenVerifier):
    """Verify signature, issuer, audience, lifetime, scopes; never trust token claims unchecked."""

    def __init__(self, config: OAuthConfig, jwks_client: PyJWKClient | None = None):
        self.config = config
        self.jwks_client = jwks_client or PyJWKClient(
            config.jwks_url, cache_jwk_set=True, lifespan=300, timeout=5
        )

    def verify_sync(self, raw: str) -> AccessToken | None:
        if not isinstance(raw, str) or len(raw) > 16384 or raw.count(".") != 2:
            return None
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(raw)
            claims = jwt.decode(
                raw, signing_key.key, algorithms=["RS256"],
                issuer=self.config.issuer, audience=self.config.resource,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
                leeway=10,
            )
            if not isinstance(claims.get("sub"), str) or not claims["sub"]:
                return None
            if not self.config.allowed_subjects or claims["sub"] not in self.config.allowed_subjects:
                return None
            scope = claims.get("scope", "")
            if not isinstance(scope, str):
                return None
            scopes = scope.split()
            if not all(required in scopes for required in self.config.scopes):
                return None
            # Accept only a token explicitly minted for this public MCP URL.
            audiences = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
            if self.config.resource not in audiences:
                return None
            client_id = claims.get("azp") or claims.get("client_id") or "oauth-client"
            if not isinstance(client_id, str) or len(client_id) > 512:
                return None
            return AccessToken(
                token=raw, client_id=client_id, scopes=scopes,
                expires_at=int(claims["exp"]), resource=self.config.resource,
                subject=claims["sub"],
            )
        except (PyJWTError, ValueError, TypeError, KeyError, OSError):
            return None

    async def verify_token(self, token: str) -> AccessToken | None:
        # JWKS fetch may perform network I/O; never block the async MCP event loop.
        return await asyncio.to_thread(self.verify_sync, token)

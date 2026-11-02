#!/usr/bin/env python3
"""Smoke-test protected MCP discovery over localhost, without exposing secrets.

Run after loading .env.dev into your shell and starting run_mcp.sh.
This script creates a 60-second scoped LOCAL TEST token using the configured
signing key; it sends the token only to 127.0.0.1:8765 and never prints it.
"""
from __future__ import annotations

import os
import secrets
import sys
import time
from pathlib import Path

# Running `python scripts/check_mcp_discovery.py` must resolve the local gateway.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import jwt

from gateway.local_security import LocalConfig


def check(client: httpx.Client, label: str, request: dict, headers: dict[str, str]) -> bool:
    try:
        res = client.post("http://127.0.0.1:8765/mcp", json=request, headers=headers)
    except httpx.RequestError as exc:
        print(f"{label}: connection error ({type(exc).__name__})")
        return False
    try:
        body = res.json()
    except ValueError:
        print(f"{label}: HTTP {res.status_code}, non-JSON response")
        return False
    if not isinstance(body, dict):
        print(f"{label}: HTTP {res.status_code}, unexpected response shape")
        return False
    if "result" in body:
        result = body["result"]
        if isinstance(result, dict) and "tools" in result:
            names = [v.get("name", "?") for v in result["tools"] if isinstance(v, dict)]
            print(f"{label}: HTTP {res.status_code}, tool count={len(names)}, names={names}")
        else:
            print(f"{label}: HTTP {res.status_code}, result returned")
        return res.status_code == 200
    error = body.get("error", {})
    code = error.get("code", "n/a") if isinstance(error, dict) else "n/a"
    message = error.get("message", "") if isinstance(error, dict) else ""
    if not isinstance(message, str):
        message = ""
    category = "other"
    if "header" in message.lower() or "mismatch" in message.lower():
        category = "header-validation"
    elif "version" in message.lower() or "protocol" in message.lower():
        category = "protocol-version"
    elif "session" in message.lower():
        category = "session"
    elif "request" in message.lower():
        category = "invalid-request"
    print(f"{label}: HTTP {res.status_code}, error_code={code}, category={category}")
    return False


def main() -> int:
    required = ["KRW_MCP_PUBLIC_URL", "KRW_OAUTH_SIGNING_KEY", "KRW_LOGIN_USERNAME", "KRW_OAUTH_CLIENT_ID"]
    if any(not os.getenv(k) for k in required):
        print("Load .env.dev first: set -a; source .env.dev; set +a", file=sys.stderr)
        return 2
    cfg = LocalConfig.from_env()
    now = int(time.time())
    token = jwt.encode({
        "iss": cfg.issuer, "aud": cfg.resource, "sub": cfg.username,
        "client_id": cfg.client_id, "scope": "krw:read", "iat": now,
        "nbf": now, "exp": now + 60, "jti": secrets.token_urlsafe(16),
    }, cfg.signing_key, algorithm="HS256")
    headers = {
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {token}",
        "MCP-Protocol-Version": "2025-06-18",
    }
    with httpx.Client(timeout=12, trust_env=False) as client:
        initialized = check(client, "initialize", {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "krw-diagnostic", "version": "1"}},
        }, headers)
        listed = check(client, "tools/list", {
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        }, headers)
    return 0 if initialized and listed else 1


if __name__ == "__main__":
    sys.exit(main())

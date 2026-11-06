"""Ensure the OAuth frontend preserves MCP protocol metadata to the backend."""
import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from test_local_auth import load_auth


def test_forward_modern_mcp_headers(monkeypatch, tmp_path):
    auth, _, _ = load_auth(monkeypatch, tmp_path)
    sent = []

    class StubBackend:
        def __init__(self, *args, **kwargs):
            self.args = kwargs
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def request(self, method, url, content, headers):
            sent.append((method, url, content, headers))
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"tools": []}})

    monkeypatch.setattr(auth.httpx, "AsyncClient", StubBackend)
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    with TestClient(auth.app, base_url="https://tunnel.test") as client:
        res = client.post("/mcp", json=body, headers={
            "Authorization": "Bearer test-secret-never-log",
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/list",
            "Mcp-Name": "example",
            "Mcp-Param-Uri": "b64:aGVsbG8=",
            "Mcp-Session-Id": "opaque-test-session",
            "Accept": "application/json, text/event-stream",
            "X-Internal-Admin": "should-not-forward",
            "Cookie": "not-for-backend",
        })
    assert res.status_code == 200
    method, url, content, headers = sent[0]
    assert method == "POST" and url == "http://127.0.0.1:8767/mcp"
    assert json.loads(content) == body
    assert headers["authorization"] == "Bearer test-secret-never-log"
    assert headers["mcp-method"] == "tools/list"
    assert headers["mcp-name"] == "example"
    assert headers["mcp-param-uri"] == "b64:aGVsbG8="
    assert headers["mcp-protocol-version"] == "2026-07-28"
    assert headers["mcp-session-id"] == "opaque-test-session"
    assert "cookie" not in headers and "x-internal-admin" not in headers


def test_mcp_errors_log_only_sanitized_category(monkeypatch, tmp_path, caplog):
    auth, _, _ = load_auth(monkeypatch, tmp_path)
    class Backend400:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, *args, **kwargs):
            return httpx.Response(400, json={"jsonrpc": "2.0", "id": 1, "error": {
                "code": -32020, "message": "HeaderMismatch sensitive@example.com test-secret"}})
    monkeypatch.setattr(auth.httpx, "AsyncClient", Backend400)
    monkeypatch.setenv("KRW_MCP_LOG_PROTOCOL_ERRORS", "1")
    with caplog.at_level(logging.WARNING, logger="krw.mcp"):
        with TestClient(auth.app, base_url="https://tunnel.test") as client:
            res = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert res.status_code == 400
    assert "method=tools/list" in caplog.text
    assert "category=header-validation" in caplog.text
    assert "test-secret" not in caplog.text and "sensitive@example" not in caplog.text


def test_diagnostic_category_never_echoes_backend_error(monkeypatch, tmp_path):
    auth, _, _ = load_auth(monkeypatch, tmp_path)
    assert auth.safe_mcp_error_category(b'not json') == "other"
    assert auth.safe_mcp_error_category(b'{"error":{"message":"Unsupported protocol version 123"}}') == "protocol-version"
    assert auth.discovery_method(b'{"method":"tools/call"}') == "other"

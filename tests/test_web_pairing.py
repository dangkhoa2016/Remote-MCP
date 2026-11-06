"""device enrollment owner browser pairing: live routing via ASGI, with no Render shell."""
from __future__ import annotations

import re
import secrets
from urllib.parse import urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from gateway.device_enrollment import pairing_code
from gateway.relay import State, create_app


@pytest.fixture
def pairing(monkeypatch, tmp_path):
    # Reuse the OAuth fixture to verify password and security settings are identical.
    from test_local_auth import load_auth

    monkeypatch.setenv("KRW_DEVICE_ENROLLMENT_ENABLED", "1")
    monkeypatch.setenv("KRW_DEVICE_ADMIN_TOOLS_ENABLED", "1")
    control_token = secrets.token_urlsafe(40)
    monkeypatch.setenv("KRW_CONTROL_TOKEN", control_token)
    a, _, password = load_auth(monkeypatch, tmp_path)
    state = State({}, control_token, enrollment_enabled=True,
                  enrollment_db_path=str(tmp_path / "devices.sqlite"))
    relay_app = create_app(state)
    real_async_client = httpx.AsyncClient

    class RelayClient:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            self.client = real_async_client(
                transport=httpx.ASGITransport(app=relay_app),
                base_url="http://127.0.0.1:8766",
            )
            await self.client.__aenter__()
            return self

        async def __aexit__(self, *args):
            await self.client.__aexit__(*args)

        async def request(self, method, url, **kwargs):
            assert urlparse(url).netloc == "127.0.0.1:8766"
            assert kwargs["headers"] == {"X-Control-Token": control_token}
            return await self.client.request(method, url, **kwargs)

    monkeypatch.setattr("gateway.device_admin_ui.httpx.AsyncClient", RelayClient)
    yield a, password, state


def login_nonce(client):
    page = client.get("/devices")
    assert page.status_code == 200
    return re.search(r'name="nonce" value="([A-Za-z0-9_-]{43})"', page.text).group(1)


def login_form(client, *, password, username="localuser"):
    return {"nonce": login_nonce(client), "username": username, "password": password}


def test_web_login_pairing_and_logout(pairing):
    a, password, state = pairing
    token = secrets.token_urlsafe(32)
    enrolled = state.enrollments.enroll(
        type("Device", (), {"device_id": "colab-test-1", "hostname": "<unsafe-host>",
                            "platform": "Linux", "workspace": "project"})(),
        token,
    )
    code = pairing_code(token, enrolled["challenge"])
    origin = {"Origin": "https://tunnel.test"}

    with TestClient(a.app, base_url="https://tunnel.test") as client:
        guest = client.get("/devices")
        assert guest.status_code == 200
        assert "Sign in" in guest.text
        assert "colab-test-1" not in guest.text

        foreign_login = login_form(client, password=password)
        assert client.post("/devices/login", headers={"Origin": "https://attacker.example"},
                           data=foreign_login).status_code == 403
        wrong = client.post("/devices/login", headers=origin,
                            data=login_form(client, password="invalid"))
        assert wrong.status_code == 401
        login = client.post("/devices/login", headers=origin,
                            data=login_form(client, password=password), follow_redirects=False)
        assert login.status_code == 303
        assert login.headers["location"] == "/devices"
        cookie = login.headers["set-cookie"]
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
        assert "Path=/devices" in cookie
        dashboard = client.get("/devices")
        assert dashboard.status_code == 200
        assert "colab-test-1" in dashboard.text
        assert "&lt;unsafe-host&gt;" in dashboard.text
        assert "<unsafe-host>" not in dashboard.text
        assert code not in dashboard.text
        assert token not in dashboard.text
        assert state.control_token not in dashboard.text
        assert "form-action 'self'" in dashboard.headers["content-security-policy"]
        csrf = re.search(r'name="csrf" value="([a-f0-9]{64})"', dashboard.text).group(1)
        form = {"csrf": csrf, "device_id": "colab-test-1", "pairing_code": code}

        assert client.post("/devices/approve", data=form,
                           headers={"Origin": "https://attacker.example"}).status_code == 403
        assert client.post("/devices/approve", data={**form, "csrf": "0"*64},
                           headers=origin).status_code == 403
        assert state.enrollments.authenticated("colab-test-1", token) is False

        bad = client.post("/devices/approve", data={**form, "pairing_code": "AAAAAAAAAAAA"},
                          headers=origin, follow_redirects=False)
        assert bad.status_code == 303 and "invalid" in bad.headers["location"]
        assert state.enrollments.authenticated("colab-test-1", token) is False

        approved = client.post("/devices/approve", data=form, headers=origin, follow_redirects=False)
        assert approved.status_code == 303
        assert approved.headers["location"] == "/devices?result=approved"
        assert state.enrollments.authenticated("colab-test-1", token)
        assert "1 active" in client.get("/devices").text

        sign_out = client.post("/devices/logout", data={"csrf": csrf},
                               headers=origin, follow_redirects=False)
        assert sign_out.status_code == 303
        assert "Max-Age=0" in sign_out.headers["set-cookie"]
        assert "Sign in" in client.get("/devices").text
        assert client.post("/devices/approve", data=form, headers=origin).status_code == 401


def test_password_attempts_are_rate_limited(pairing):
    a, password, state = pairing
    origin = {"Origin": "https://tunnel.test"}
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        for i in range(10):
            assert client.post("/devices/login", headers=origin,
                               data=login_form(client, password="incorrect")).status_code == 401
        assert client.post("/devices/login", headers=origin,
                           data=login_form(client, password=password)).status_code == 429


def test_web_approval_feature_flag(monkeypatch, tmp_path):
    from test_local_auth import load_auth
    monkeypatch.setenv("KRW_DEVICE_ENROLLMENT_ENABLED", "0")
    monkeypatch.setenv("KRW_DEVICE_ADMIN_TOOLS_ENABLED", "0")
    a, _, password = load_auth(monkeypatch, tmp_path)
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        assert client.get("/devices").status_code == 404
        assert client.post("/devices/login", headers={"Origin":"https://tunnel.test"},
                           data={"username":"localuser","password":password}).status_code == 404

@pytest.mark.parametrize("login_headers,action_headers", [
    ({}, {}),
    ({"Origin": "null"}, {"Origin": "null"}),
    ({"Origin": "https://tunnel.test"}, {}),
    ({}, {"Origin": "https://tunnel.test"}),
])
def test_privacy_origin_login_and_approve(pairing, login_headers, action_headers):
    """Missing/null Origin is permitted ONLY with nonce at login and CSRF after login."""
    a, password, state = pairing
    token = secrets.token_urlsafe(32)
    req = state.enrollments.enroll(
        type("Device", (), {"device_id": "colab-private", "hostname": "colab-host",
                            "platform": "Linux", "workspace": "workspace"})(), token)
    code = pairing_code(token, req["challenge"])

    with TestClient(a.app, base_url="https://tunnel.test") as client:
        form = login_form(client, password=password)
        response = client.post("/devices/login", data=form, headers=login_headers,
                               follow_redirects=False)
        assert response.status_code == 303, response.text
        dashboard = client.get("/devices")
        csrf = re.search(r'name="csrf" value="([a-f0-9]{64})"', dashboard.text).group(1)
        approval = client.post("/devices/approve", headers=action_headers, data={
            "device_id": "colab-private", "pairing_code": code, "csrf": csrf,
        }, follow_redirects=False)
        assert approval.status_code == 303, approval.text
        assert state.enrollments.authenticated("colab-private", token)
        logout = client.post("/devices/logout", headers=action_headers,
                             data={"csrf": csrf}, follow_redirects=False)
        assert logout.status_code == 303


def test_login_nonce_required_single_use_and_expiry(pairing):
    a, password, _ = pairing
    import sqlite3
    import time
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        valid = login_form(client, password=password)
        missing = client.post("/devices/login", headers={"Origin": "null"},
                              data={k:v for k,v in valid.items() if k != "nonce"})
        assert missing.status_code == 400
        forged = client.post("/devices/login", headers={"Origin": "null"},
                             data={**valid, "nonce": secrets.token_urlsafe(32)})
        assert forged.status_code == 403
        wrong = client.post("/devices/login", headers={"Origin": "null"},
                            data={**valid, "password": "wrong"})
        assert wrong.status_code == 401
        replay = client.post("/devices/login", headers={"Origin": "null"}, data=valid)
        assert replay.status_code == 403
        fresh = login_form(client, password=password)
        with sqlite3.connect(a.DB_FILE) as db:
            db.execute("UPDATE krw_admin_login_nonces SET expires_at=? "
                       "WHERE nonce_sha256=?", (int(time.time())-1, a.digest(fresh["nonce"])))
        assert client.post("/devices/login", headers={"Origin": "null"},
                           data=fresh).status_code == 403


def test_cross_site_rejected_with_real_nonce_and_csrf(pairing):
    a, password, state = pairing
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        form = login_form(client, password=password)
        assert client.post("/devices/login", headers={"Origin": "https://evil.example"},
                           data=form).status_code == 403
        assert client.post("/devices/login", data=form,
                           follow_redirects=False).status_code == 303
        csrf = re.search(r'name="csrf" value="([a-f0-9]{64})"',
                         client.get("/devices").text).group(1)
        assert client.post("/devices/logout", headers={"Origin": "https://evil.example"},
                           data={"csrf": csrf}).status_code == 403
        assert client.post("/devices/logout", headers={"Origin": "null"},
                           data={"csrf": secrets.token_hex(32)}).status_code == 403
        assert client.post("/devices/logout", headers={"Origin": "null"},
                           data={"csrf": csrf}, follow_redirects=False).status_code == 303

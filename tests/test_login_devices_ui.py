"""Responsive login/devices UI and username handling regression tests."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from gateway.ui_theme import normalize_username
from test_local_auth import begin, load_auth
from test_web_pairing import login_form, pairing


def test_whitespace_username_normalization():
    assert normalize_username(" \n lo\tcal \r user ") == "localuser"
    assert normalize_username("l o c a l u s e r") == "localuser"
    assert normalize_username("\u00a0local\u2003user\u00a0") == "localuser"
    assert normalize_username(" localuser ") == "localuser"
    assert normalize_username(" \t \r\n ") == ""


def test_oauth_login_normalizes_username_and_keeps_oauth_controls(monkeypatch, tmp_path):
    a, _, password = load_auth(monkeypatch, tmp_path)
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        page, _, nonce = begin(a, client)
        assert page.status_code == 200
        assert 'class="auth"' in page.text
        assert 'name="username"' in page.text
        assert 'name="password"' in page.text
        assert "form-action 'self' https://chatgpt.com" in page.headers["content-security-policy"]
        script = client.get("/login-guard.js")
        assert r"replace(/\s+/g" in script.text
        login = client.post("/authorize", data={
            "nonce": nonce, "username": " \n local \t user \r ", "password": password,
        }, follow_redirects=False)
        assert login.status_code == 303


def test_password_whitespace_is_never_normalized(monkeypatch, tmp_path):
    a, _, password = load_auth(monkeypatch, tmp_path)
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        _, _, nonce = begin(a, client)
        login = client.post("/authorize", data={
            "nonce": nonce, "username": " localuser ",
            "password": " " + password + " ",
        }, follow_redirects=False)
        assert login.status_code == 401


def test_devices_page_and_username_normalization(pairing):
    a, password, _ = pairing
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        login_page = client.get("/devices")
        assert login_page.status_code == 200
        assert 'class="auth"' in login_page.text
        assert "script-src 'self'" in login_page.headers["content-security-policy"]
        login = client.post("/devices/login", data=login_form(
            client, username=" local \n user ", password=password
        ), follow_redirects=False)
        assert login.status_code == 303
        dashboard = client.get("/devices")
        assert dashboard.status_code == 200
        assert "<h1>Devices</h1>" in dashboard.text
        assert 'class="stats"' in dashboard.text
        assert "Enrolled devices" in dashboard.text
        assert "form-action 'self'" in dashboard.headers["content-security-policy"]
        assert re.search(r'name="csrf" value="[a-f0-9]{64}"', dashboard.text)


def test_devices_password_is_not_trimmed(pairing):
    a, password, _ = pairing
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        login = client.post("/devices/login", data=login_form(
            client, username="localuser", password=password + "\n",
        ), follow_redirects=False)
        assert login.status_code == 401

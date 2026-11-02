"""Offline test of the self-hosted username/password OAuth bridge."""
import base64
import hashlib
import importlib
import re
import sqlite3
import secrets
import sys
import time
import types
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from fastapi.testclient import TestClient


def load_auth(monkeypatch, tmp_path):
    try:
        import mcp.server.auth.provider
    except ModuleNotFoundError:
        mods = {x: types.ModuleType(x) for x in (
            "mcp", "mcp.server", "mcp.server.auth", "mcp.server.auth.provider", "mcp.server.auth.settings"
        )}
        class TokenVerifier: pass
        class AccessToken:
            def __init__(self, **kwargs): self.__dict__.update(kwargs)
        class AuthSettings:
            def __init__(self, **kwargs): self.__dict__.update(kwargs)
        mods["mcp.server.auth.provider"].TokenVerifier = TokenVerifier
        mods["mcp.server.auth.provider"].AccessToken = AccessToken
        mods["mcp.server.auth.settings"].AuthSettings = AuthSettings
        sys.modules.update(mods)
    salt = secrets.token_bytes(16)
    password = "dev-test-password-xyz123"
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    vars = {
        "KRW_MCP_PUBLIC_URL": "https://tunnel.test/mcp",
        "KRW_LOGIN_USERNAME": "localuser",
        "KRW_LOGIN_SALT": salt.hex(),
        "KRW_LOGIN_PASSWORD_HASH": digest.hex(),
        "KRW_OAUTH_CLIENT_ID": "test-client-id",
        "KRW_OAUTH_CLIENT_SECRET": base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("="),
        "KRW_OAUTH_SIGNING_KEY": base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("="),
        "KRW_OAUTH_REDIRECT_URI": "https://chatgpt.com/connector_platform/oauth/callback",
        "KRW_AUTH_DB_PATH": str(tmp_path / "oauth.db"),
    }
    for k, v in vars.items(): monkeypatch.setenv(k, v)
    for k in ["gateway.local_security", "gateway.local_auth"]: sys.modules.pop(k, None)
    a = importlib.import_module("gateway.local_auth")
    return a, vars, password


@pytest.fixture
def ctx(monkeypatch, tmp_path):
    return load_auth(monkeypatch, tmp_path)


def begin(a, client, state="xyz", **overrides):
    verifier = "A" * 43
    params = {
        "response_type":"code", "client_id":a.CFG.client_id,
        "redirect_uri":a.CFG.callback, "resource":a.CFG.resource,
        "scope":"krw:read", "state":state,
        "code_challenge":a.pkce_s256(verifier), "code_challenge_method":"S256",
    }
    params.update(overrides)
    r = client.get("/authorize", params=params)
    return r, verifier, re.search(r'name="nonce" value="([^"]+)"', r.text).group(1) if r.status_code == 200 else None


def authenticate(client, a, password):
    r, verifier, nonce = begin(a, client)
    assert r.status_code == 200
    login = client.post("/authorize", data={"nonce": nonce, "username":a.CFG.username, "password":password}, follow_redirects=False)
    assert login.status_code == 303, login.text
    uri = urlparse(login.headers["location"])
    code = parse_qs(uri.query)["code"][0]
    assert parse_qs(uri.query)["state"] == ["xyz"]
    return verifier, code


def token_form(a, verifier, code):
    return {
        "grant_type":"authorization_code", "client_id":a.CFG.client_id,
        "client_secret":base64.urlsafe_b64encode(a.CLIENT_SECRET).decode().rstrip("="),
        "redirect_uri":a.CFG.callback, "resource":a.CFG.resource,
        "code":code, "code_verifier":verifier,
    }


def test_login_to_access_token_refresh_and_replay(ctx):
    a, v, password = ctx
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        assert client.get("/.well-known/oauth-authorization-server").json()["code_challenge_methods_supported"] == ["S256"]
        assert client.get("/.well-known/oauth-protected-resource/mcp").json()["resource"] == a.CFG.resource
        verifier, code = authenticate(client, a, password)
        data = token_form(a, verifier, code)
        ok = client.post("/token", data=data)
        assert ok.status_code == 200, ok.text
        contents = ok.json()
        assert jwt.decode(contents["access_token"], a.CFG.signing_key, algorithms=["HS256"], audience=a.CFG.resource, issuer=a.CFG.issuer)["scope"] == "krw:read"
        assert client.post("/token", data=data).json()["error"] == "invalid_grant"
        refresh_data = {"grant_type":"refresh_token", "client_id":a.CFG.client_id,
                        "client_secret":data["client_secret"], "resource":a.CFG.resource,
                        "refresh_token":contents["refresh_token"]}
        refreshed = client.post("/token", data=refresh_data)
        assert refreshed.status_code == 200, refreshed.text
        assert client.post("/token", data=refresh_data).json()["error"] == "invalid_grant"


def test_invalid_password_and_login_replay(ctx):
    a, v, password = ctx
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        r, verifier, nonce = begin(a, client)
        wrong = client.post("/authorize", data={"nonce":nonce,"username":a.CFG.username,"password":"wrong"},follow_redirects=False)
        assert wrong.status_code == 401
        good = client.post("/authorize", data={"nonce":nonce,"username":a.CFG.username,"password":password},follow_redirects=False)
        assert good.status_code == 303
        replay = client.post("/authorize", data={"nonce":nonce,"username":a.CFG.username,"password":password},follow_redirects=False)
        assert replay.status_code == 303  # short retry returns same code, not a new code
        assert replay.headers["location"] == good.headers["location"]


@pytest.mark.parametrize("bad", [
    {"redirect_uri":"https://evil.example/receive"},
    {"code_challenge_method":"plain"},
    {"resource":"https://other.example/mcp"},
    {"scope":"krw:command"},
    {"client_id":"evil-client"},
])
def test_authorize_rejects_bad_request(ctx, bad):
    a, v, _ = ctx
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        r, _, nonce = begin(a, client, **bad)
        assert r.status_code == 400
        assert nonce is None


def test_pkce_wrong_verifier_and_secret(ctx):
    a, v, password = ctx
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        verifier, code = authenticate(client, a, password)
        good = token_form(a, verifier, code)
        assert client.post("/token", data={**good, "client_secret":"bad"}).status_code == 401
        assert client.post("/token", data={**good, "code_verifier":"B" * 43}).json()["error"] == "invalid_grant"
        assert client.post("/token", data={**good, "resource":"https://evil.example/mcp"}).json()["error"] == "invalid_target"
        assert client.post("/token", data=good).status_code == 200


@pytest.mark.asyncio
async def test_verifier_rejects_invalid_signature_and_scope(ctx):
    a, v, password = ctx
    from gateway.local_security import LocalTokenVerifier
    verifier = LocalTokenVerifier(a.CFG)
    good = a.new_access("krw:read")[0]
    assert await verifier.verify_token(good) is not None
    wrong_scope = jwt.encode({"iss":a.CFG.issuer,"aud":a.CFG.resource,"sub":a.CFG.username,
                             "client_id":a.CFG.client_id,"scope":"krw:command","iat":int(time.time()),
                             "exp":int(time.time())+60,"jti":"1"}, a.CFG.signing_key, algorithm="HS256")
    assert await verifier.verify_token(wrong_scope) is None
    assert await verifier.verify_token(good + "xxx") is None


def test_login_rate_limit_and_csrf_origin(ctx):
    a, v, password = ctx
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        _, _, nonce = begin(a, client)
        bad_origin = client.post("/authorize", headers={"Origin": "https://evil.example"},
                                 data={"nonce":nonce,"username":a.CFG.username,"password":password})
        assert bad_origin.status_code == 403
        for _ in range(10):
            r = client.post("/authorize", data={"nonce":nonce,"username":a.CFG.username,"password":"wrong"})
            assert r.status_code == 401
        locked = client.post("/authorize", data={"nonce":nonce,"username":a.CFG.username,"password":password})
        assert locked.status_code == 429


def test_host_header_mismatch_is_rejected(ctx):
    a, v, password = ctx
    with TestClient(a.app, base_url="https://untrusted.example") as client:
        assert client.get("/.well-known/oauth-authorization-server").status_code == 400


def test_password_hash_never_accepts_similar_input(ctx):
    a, v, password = ctx
    assert a.check_password(password)
    assert not a.check_password(password + "x")
    assert not a.check_password("A" * 513)


def test_null_origin_login_with_nonce_and_password(ctx):
    a, _, password = ctx
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        response, verifier, nonce = begin(a, client)
        assert response.status_code == 200
        login = client.post(
            "/authorize", headers={"Origin": "null"},
            data={"nonce": nonce, "username": a.CFG.username, "password": password},
            follow_redirects=False,
        )
        assert login.status_code == 303, login.text
        code = parse_qs(urlparse(login.headers["location"]).query)["code"][0]
        assert client.post("/token", data=token_form(a, verifier, code)).status_code == 200
        assert client.post(
            "/authorize", headers={"Origin": "null"},
            data={"nonce": nonce, "username": a.CFG.username, "password": password},
            follow_redirects=False,
        ).status_code == 200  # token already redeemed; never issue another code


def test_null_origin_requires_valid_nonce_and_correct_password(ctx):
    a, _, password = ctx
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        _, _, nonce = begin(a, client)
        forged_nonce = client.post(
            "/authorize", headers={"Origin": "null"},
            data={"nonce": "forged", "username": a.CFG.username, "password": password},
            follow_redirects=False,
        )
        assert forged_nonce.status_code == 400
        wrong_password = client.post(
            "/authorize", headers={"Origin": "null"},
            data={"nonce": nonce, "username": a.CFG.username, "password": "wrong"},
            follow_redirects=False,
        )
        assert wrong_password.status_code == 401


def test_duplicate_login_reuses_code_and_code_stays_single_use(ctx):
    a, _, password = ctx
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        response, verifier, nonce = begin(a, client)
        assert response.status_code == 200
        assert 'src="/login-guard.js"' in response.text
        assert 'script-src \'self\'' in response.headers["content-security-policy"]
        js = client.get("/login-guard.js")
        assert js.status_code == 200 and "event.preventDefault()" in js.text
        form = {"nonce":nonce, "username":a.CFG.username, "password":password}
        first = client.post("/authorize", data=form, follow_redirects=False)
        second = client.post("/authorize", data=form, follow_redirects=False)
        assert first.status_code == second.status_code == 303
        assert first.headers["location"] == second.headers["location"]
        code = parse_qs(urlparse(first.headers["location"]).query)["code"][0]
        token = client.post("/token", data=token_form(a, verifier, code))
        assert token.status_code == 200, token.text
        assert client.post("/token", data=token_form(a, verifier, code)).status_code == 400
        after = client.post("/authorize", data=form, follow_redirects=False)
        assert after.status_code == 200
        assert "Already signed in" in after.text


def test_duplicate_requires_correct_password_and_same_nonce(ctx):
    a, _, password = ctx
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        _, _, nonce = begin(a, client)
        form = {"nonce":nonce, "username":a.CFG.username, "password":password}
        assert client.post("/authorize", data=form, follow_redirects=False).status_code == 303
        assert client.post("/authorize", data={**form, "password":"bad"}, follow_redirects=False).status_code == 401
        assert client.post("/authorize", data={**form, "nonce":"forged"}, follow_redirects=False).status_code == 400
        assert client.post("/authorize", data=form, headers={"Origin":"https://attacker.example"}, follow_redirects=False).status_code == 403


def test_existing_login_table_migrated_without_data_loss(ctx):
    a, _, _ = ctx
    with sqlite3.connect(a.DB_FILE) as db:
        assert "used_at" in {row[1] for row in db.execute("PRAGMA table_info(logins)")}
        before = db.execute("SELECT count(*) FROM logins").fetchone()[0]
    a.init_db()
    with sqlite3.connect(a.DB_FILE) as db:
        assert db.execute("SELECT count(*) FROM logins").fetchone()[0] == before


def test_login_form_csp_allows_registered_chatgpt_callback(ctx):
    """A 303 from POST /authorize to ChatGPT must not be blocked by CSP form-action."""
    a, _, password = ctx
    with TestClient(a.app, base_url="https://tunnel.test") as client:
        page, _, nonce = begin(a, client)
        assert page.status_code == 200
        csp = page.headers["content-security-policy"]
        assert "form-action 'self' https://chatgpt.com;" in csp
        assert "form-action *" not in csp
        assert "base-uri 'none'" in csp
        assert "frame-ancestors 'none'" in csp
        login = client.post("/authorize", data={
            "nonce": nonce, "username": a.CFG.username, "password": password
        }, follow_redirects=False)
        assert login.status_code == 303
        assert login.headers["location"].startswith(a.CFG.callback + "?")

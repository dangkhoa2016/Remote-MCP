"""Owner-only browser UI for approving Agent pairing on the public HTTPS frontend.

This does not open a controller endpoint. Only authenticated, CSRF-protected,
origin-checked form submissions can invoke the existing localhost relay.
Agent secrets and KRW_CONTROL_TOKEN never reach the browser.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Callable

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from gateway.ui_theme import STYLES, login_form, normalize_username

SESSION_COOKIE = "__Secure-krw-admin"
SESSION_TTL = 3600
LOGIN_NONCE_TTL = 300
MAX_PASSWORD_ATTEMPTS = 10
ORIGIN_RELAY = "http://127.0.0.1:8766"
DEVICE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
PAIRING_RE = re.compile(r"^[A-Z2-7]{12}$")


def hash_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def init_schema(path: Path) -> None:
    """Use the already-persistent OAuth SQLite; no extra disk or env required."""
    with sqlite3.connect(path, timeout=5) as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS krw_admin_sessions (
                session_sha256 TEXT PRIMARY KEY,
                expires_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS krw_admin_login_attempts (
                timestamp INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS krw_admin_login_nonces (
                nonce_sha256 TEXT PRIMARY KEY,
                expires_at INTEGER NOT NULL,
                used INTEGER NOT NULL DEFAULT 0
            );
        """)


def _html_page(body: str) -> HTMLResponse:
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Devices | Remote-MCP</title><style>{STYLES}</style></head>
<body><main class="page">{body}</main><script src="/login-guard.js" defer></script></body></html>'''
    return HTMLResponse(page, headers={
        "Content-Security-Policy": (
            "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
            "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
        ),
        "Cache-Control": "no-store",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    })


def build_admin_router(
    *, origin: str, db_path: Path, username: str,
    verify_password: Callable[[str], bool], csrf_secret: bytes,
    control_token: str, enabled: bool,
    form_reader: Callable,
) -> APIRouter:
    router = APIRouter()
    if enabled:
        if len(control_token) < 32:
            raise ValueError("Cannot run pairing UI without control secret")
        init_schema(db_path)

    def valid_origin(request: Request) -> bool:
        # Some privacy contexts omit Origin or send the literal "null".
        # Both are permitted ONLY with the one-time login nonce or the
        # authenticated session's CSRF token. Explicit foreign origins
        # remain rejected before any credential validation.
        return request.headers.get("origin") in (None, "null", origin)

    def csrf_for(session: str) -> str:
        return hmac.new(csrf_secret, ("krw-admin-csrf-v1:" + session).encode(), hashlib.sha256).hexdigest()

    def authenticated(request: Request) -> tuple[str, str] | None:
        token = request.cookies.get(SESSION_COOKIE, "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43,64}", token):
            return None
        with sqlite3.connect(db_path, timeout=5) as db:
            row = db.execute(
                "SELECT expires_at FROM krw_admin_sessions WHERE session_sha256=?",
                (hash_text(token),),
            ).fetchone()
        if row is None or row[0] <= int(time.time()):
            return None
        return token, csrf_for(token)

    async def relay(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        # Only fixed, locally authored paths are ever sent to this helper.
        try:
            async with httpx.AsyncClient(timeout=8, trust_env=False, follow_redirects=False) as client:
                response = await client.request(
                    method, ORIGIN_RELAY + path,
                    headers={"X-Control-Token": control_token},
                    json=payload if method == "POST" else None,
                )
            return response.status_code, response.json()
        except (httpx.HTTPError, ValueError):
            return 503, {}

    def redirect(status: str = "") -> RedirectResponse:
        allowed = {"", "approved", "expired", "invalid", "locked", "unavailable"}
        if status not in allowed:
            status = "unavailable"
        suffix = "?result=" + status if status else ""
        return RedirectResponse("/devices" + suffix, status_code=303)

    def failure(message: str, status: int = 403) -> HTMLResponse:
        res = _html_page(
            '<section class="card auth" role="alert">'
            '<p class="eyebrow">Device administration</p><h1>Request denied</h1>'
            '<p class="lead">' + html.escape(message) + '</p>'
            '<a class="btn btn-secondary" href="/devices">Back to devices</a></section>'
        )
        res.status_code = status
        return res

    def login_page() -> HTMLResponse:
        # A server-generated, single-use nonce makes browser form login safe
        # even when privacy protections remove the Origin header.
        nonce = secrets.token_urlsafe(32)
        now = int(time.time())
        with sqlite3.connect(db_path, timeout=5) as db:
            db.execute("DELETE FROM krw_admin_login_nonces WHERE expires_at <= ?", (now,))
            db.execute(
                "INSERT INTO krw_admin_login_nonces (nonce_sha256, expires_at) VALUES (?, ?)",
                (hash_text(nonce), now + LOGIN_NONCE_TTL),
            )
            # The login page is public; bound storage even if repeatedly fetched.
            db.execute(
                "DELETE FROM krw_admin_login_nonces WHERE nonce_sha256 IN ("
                "SELECT nonce_sha256 FROM krw_admin_login_nonces "
                "ORDER BY expires_at DESC, rowid DESC LIMIT -1 OFFSET 256)"
            )
        return _html_page(login_form(
            action="/devices/login", nonce=nonce, title="Device administration",
            description="Sign in with your Gateway credentials to review and approve Agents.",
            button_text="Sign in to devices",
            help_text="Use your Gateway username and password. Pairing codes come from the Agent terminal.",
        ))

    @router.get("/devices", response_class=HTMLResponse)
    async def devices_page(request: Request):
        if not enabled:
            return failure("Not found", 404)
        session = authenticated(request)
        if session is None:
            return login_page()
        _, csrf = session
        pending_status, pending = await relay("GET", "/v1/control/enrollments/pending")
        registered_status, registered = await relay("GET", "/v1/control/enrollments/registered")
        if pending_status != 200 or registered_status != 200:
            return failure("Gateway is temporarily unavailable.", 503)
        rows = pending.get("devices", [])
        registered_rows = registered.get("devices", [])
        if not isinstance(rows, list) or not isinstance(registered_rows, list):
            return failure("Gateway returned an invalid response.", 503)
        result = request.query_params.get("result", "")
        notice = {
            "approved": ("success", "Device approved. The Agent should connect automatically."),
            "expired": ("error", "Pairing request expired. Check the Agent terminal for a new code."),
            "invalid": ("error", "Incorrect code. Compare it with the Agent terminal."),
            "locked": ("error", "Too many attempts. Wait for the pairing request to renew."),
            "unavailable": ("error", "Approval could not be completed. Please retry."),
        }.get(result)
        notice_html = (
            '<div class="notice notice-' + notice[0] + '" role="status">' +
            html.escape(notice[1]) + '</div>' if notice else ""
        )
        pending_cards = []
        for index, row in enumerate(rows[:32]):
            if not isinstance(row, dict):
                continue
            device_id = str(row.get("device_id", ""))[:64]
            if not DEVICE_RE.fullmatch(device_id):
                continue
            def cell(key: str) -> str:
                return html.escape(str(row.get(key, ""))[:128], quote=True)
            try:
                remaining = max(0, int(row.get("expires_at", 0)) - int(time.time()))
            except (TypeError, ValueError, OverflowError):
                remaining = 0
            field_id = f"pairing-code-{index}"
            pending_cards.append(
                '<div class="device"><div>'
                '<p class="device-title"><code>' + html.escape(device_id) + '</code></p>'
                '<div class="device-meta"><span><strong>Host:</strong> ' + cell("hostname") + '</span>'
                '<span><strong>Workspace:</strong> ' + cell("workspace") + '</span>'
                '<span><strong>Expires in:</strong> about ' + str(remaining // 60) + ' min</span></div></div>'
                '<form action="/devices/approve" method="post">'
                '<input type="hidden" name="csrf" value="' + csrf + '">'
                '<input type="hidden" name="device_id" value="' + html.escape(device_id, quote=True) + '">'
                '<div class="field"><label for="' + field_id + '">Verification code</label>'
                '<input id="' + field_id + '" name="pairing_code" maxlength="20" '
                'pattern="[A-Za-z2-7]{12}" autocomplete="off" spellcheck="false" '
                'autocapitalize="characters" placeholder="12 characters" required>'
                '<span class="hint">Use the code displayed in the Agent terminal.</span></div>'
                '<button class="btn btn-primary" type="submit">Approve device</button></form></div>'
            )
        active = sum(1 for row in registered_rows if isinstance(row, dict) and row.get("revoked_at") is None)
        enrolled_items = []
        for entry in registered_rows[:256]:
            if not isinstance(entry, dict):
                continue
            device_id = str(entry.get("device_id", ""))[:64]
            if not DEVICE_RE.fullmatch(device_id):
                continue
            is_active = entry.get("revoked_at") is None
            label = "Active" if is_active else "Revoked"
            css = "pill-active" if is_active else ""
            enrolled_items.append(
                '<li><code>' + html.escape(device_id) + '</code>'
                '<span class="pill ' + css + '">' + label + '</span></li>'
            )
        header = (
            '<header class="topbar"><div class="brand">'
            '<span class="brand-icon" aria-hidden="true">RM</span><span>'
            '<span class="brand-title">Remote-MCP</span>'
            '<span class="brand-subtitle">Device administration</span></span></div>'
            '<form action="/devices/logout" method="post">'
            '<input type="hidden" name="csrf" value="' + csrf + '">'
            '<button class="btn btn-secondary" type="submit">Sign out</button></form></header>'
        )
        pending_html = (
            '<div class="devices">' + ''.join(pending_cards) + '</div>'
            if pending_cards else '<div class="empty"><strong>No pending requests</strong>'
            '<p>Agents waiting for approval will appear here.</p></div>'
        )
        enrolled_html = (
            '<ul class="enrolled">' + ''.join(enrolled_items) + '</ul>'
            if enrolled_items else '<div class="empty"><strong>No devices enrolled</strong>'
            '<p>Approve an Agent to add it to your device list.</p></div>'
        )
        return _html_page(
            header + '<div class="intro"><p class="eyebrow">Trusted agents</p><h1>Devices</h1>'
            '<p class="lead">Review each Agent ID, hostname and 12-character code directly '
            'in its terminal before approval.</p></div>' + notice_html +
            '<div class="stats"><div class="stat"><span class="stat-label">Pending approvals</span>'
            '<span class="stat-value">' + str(len(pending_cards)) + '</span></div>'
            '<div class="stat"><span class="stat-label">Enrolled devices</span>'
            '<span class="stat-value">' + str(active) + ' active</span></div></div>' +
            '<section class="card section" aria-labelledby="pending-heading">'
            '<div class="section-head"><h2 id="pending-heading">Pending approvals</h2>'
            '<span class="small">Verification required</span></div>' + pending_html + '</section>' +
            '<section class="card section" aria-labelledby="enrolled-heading">'
            '<div class="section-head"><h2 id="enrolled-heading">Enrolled devices</h2>'
            '<span class="small">Approved identities</span></div>' + enrolled_html +
            '<p class="footnote">Approved Agents reconnect with saved private credentials. '
            'Colab runtime resets may remove local files; never store Agent tokens in a shared workspace.</p>'
            '</section>'
        )

    @router.post("/devices/login")
    async def devices_login(request: Request):
        if not enabled:
            return failure("Not found", 404)
        if not valid_origin(request):
            return failure("Invalid request origin.")
        params = await form_reader(request)
        raw_username = params.get("username", "") if params else ""
        normalized_username = normalize_username(raw_username)
        if (not params or len(raw_username) > 256 or len(normalized_username) > 64
                or len(params.get("password", "")) > 512
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", params.get("nonce", ""))):
            return failure("Invalid login request. Reload the pairing page.", 400)
        now = int(time.time())
        with sqlite3.connect(db_path, timeout=5) as db:
            # Cross-process atomic nonce consumption; no login replay.
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM krw_admin_login_attempts WHERE timestamp < ?", (now - 900,))
            db.execute("DELETE FROM krw_admin_login_nonces WHERE expires_at <= ?", (now,))
            count = db.execute("SELECT COUNT(*) FROM krw_admin_login_attempts").fetchone()[0]
            if count >= MAX_PASSWORD_ATTEMPTS:
                return failure("Too many login attempts. Retry later.", 429)
            consumed = db.execute(
                "UPDATE krw_admin_login_nonces SET used=1 "
                "WHERE nonce_sha256=? AND used=0 AND expires_at>?",
                (hash_text(params["nonce"]), now),
            ).rowcount
            if consumed != 1:
                return failure("Login form expired or already submitted. Reload the pairing page.", 403)
            db.execute("INSERT INTO krw_admin_login_attempts VALUES (?)", (now,))
        # Always perform password verification to avoid a username-dependent timing gap.
        password_ok = verify_password(params.get("password", ""))
        username_ok = hmac.compare_digest(normalized_username, username)
        if not (password_ok and username_ok):
            return failure("Invalid username or password.", 401)
        token = secrets.token_urlsafe(32)
        with sqlite3.connect(db_path, timeout=5) as db:
            db.execute("DELETE FROM krw_admin_sessions WHERE expires_at <= ?", (now,))
            db.execute("INSERT INTO krw_admin_sessions VALUES (?, ?)", (hash_text(token), now + SESSION_TTL))
        result = redirect()
        result.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL, secure=True,
                          httponly=True, samesite="strict", path="/devices")
        return result

    @router.post("/devices/approve")
    async def devices_approve(request: Request):
        if not enabled:
            return failure("Not found", 404)
        session = authenticated(request)
        if session is None:
            return failure("Please sign in.", 401)
        if not valid_origin(request):
            return failure("Invalid request origin.")
        params = await form_reader(request)
        if not params or not hmac.compare_digest(params.get("csrf", ""), session[1]):
            return failure("Invalid CSRF token.")
        device_id = params.get("device_id", "")
        code = params.get("pairing_code", "").strip().upper().replace("-", "")
        if not DEVICE_RE.fullmatch(device_id) or not PAIRING_RE.fullmatch(code):
            return redirect("invalid")
        status, _ = await relay("POST", "/v1/control/enrollments/approve",
                                {"device_id": device_id, "pairing_code": code})
        if status == 200:
            return redirect("approved")
        if status == 403 or status == 400:
            return redirect("invalid")
        if status == 404:
            return redirect("expired")
        if status == 429:
            return redirect("locked")
        return redirect("unavailable")

    @router.post("/devices/logout")
    async def devices_logout(request: Request):
        if not enabled:
            return failure("Not found", 404)
        session = authenticated(request)
        if session is None:
            return failure("Please sign in.", 401)
        if not valid_origin(request):
            return failure("Invalid request origin.")
        params = await form_reader(request)
        if not params or not hmac.compare_digest(params.get("csrf", ""), session[1]):
            return failure("Invalid CSRF token.")
        with sqlite3.connect(db_path, timeout=5) as db:
            db.execute("DELETE FROM krw_admin_sessions WHERE session_sha256=?", (hash_text(session[0]),))
        result = redirect()
        result.delete_cookie(SESSION_COOKIE, path="/devices")
        return result

    return router

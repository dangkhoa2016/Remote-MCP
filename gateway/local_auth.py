"""Single-user username/password OAuth authorization endpoint for ChatGPT MCP.

Development bridge, NOT a general-purpose IdP. Only one pre-registered ChatGPT
client, a fixed exact callback, PKCE S256 and a single read-only scope.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
import jwt
from fastapi import FastAPI, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from gateway.local_security import LocalConfig, _secret
from gateway.ui_theme import STYLES, login_form, normalize_username

CFG = LocalConfig.from_env()
ORIGIN = CFG.issuer.rstrip("/")
DB_FILE = Path(os.getenv("KRW_AUTH_DB_PATH", ".krw-local-state/oauth.sqlite")).resolve()
CLIENT_SECRET = _secret("KRW_OAUTH_CLIENT_SECRET")
SALT = bytes.fromhex(os.environ["KRW_LOGIN_SALT"])
PASSWORD_HASH = bytes.fromhex(os.environ["KRW_LOGIN_PASSWORD_HASH"])
if len(SALT) != 16 or len(PASSWORD_HASH) != 32:
    raise RuntimeError("Invalid password hash settings")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=[urlparse(ORIGIN).hostname, "127.0.0.1", "localhost"])


def init_db() -> None:
    DB_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(DB_FILE.parent, 0o700)
    if not DB_FILE.exists():
        fd = os.open(DB_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
    with sqlite3.connect(DB_FILE, timeout=5) as db:
        db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS logins (
                nonce_hash TEXT PRIMARY KEY, expires INT NOT NULL, used INT NOT NULL DEFAULT 0,
                challenge TEXT NOT NULL, scope TEXT NOT NULL, state TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS codes (
                code_hash TEXT PRIMARY KEY, expires INT NOT NULL, used INT NOT NULL DEFAULT 0,
                challenge TEXT NOT NULL, scope TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                token_hash TEXT PRIMARY KEY, expires INT NOT NULL, used INT NOT NULL DEFAULT 0,
                scope TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts (
                timestamp INT NOT NULL);
        """)
    # Safe, additive migration for existing previous OAuth schema database files.
    with sqlite3.connect(DB_FILE, timeout=5) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(logins)")}
        if "used_at" not in columns:
            db.execute("ALTER TABLE logins ADD COLUMN used_at INTEGER")
    os.chmod(DB_FILE, 0o600)


@contextmanager
def tx():
    con = sqlite3.connect(DB_FILE, timeout=5, isolation_level=None)
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def digest(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def pkce_s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")


def stable_authorization_code(nonce: str) -> str:
    """Reconstruct the SAME opaque code for a short, authenticated duplicate POST.

    The nonce is random and issued only by /authorize; HMAC prevents predicting
    a code from a visible nonce without the server signing key. The code remains
    single-use at /token and is always bound to PKCE + one fixed callback.
    """
    mac = hmac.new(CFG.signing_key, b"krw-auth-code-v1:" + nonce.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def authorization_redirect(code: str, state: str) -> RedirectResponse:
    separator = "&" if "?" in CFG.callback else "?"
    target = CFG.callback + separator + urlencode({"code": code, "state": state, "iss": CFG.issuer})
    return RedirectResponse(target, status_code=303, headers={"Referrer-Policy": "no-referrer"})


def valid_pkce_challenge(v: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{43}", v))


def valid_verifier(v: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", v))


def parse_scope(v: str) -> bool:
    return v in ("krw:read", "krw:read offline_access", "offline_access krw:read")


def check_password(password: str) -> bool:
    if len(password) > 512:
        return False
    actual = hashlib.scrypt(password.encode("utf-8"), salt=SALT, n=2**14, r=8, p=1, dklen=32)
    return hmac.compare_digest(actual, PASSWORD_HASH)


def request_args_valid(params: dict) -> bool:
    return all([
        params.get("response_type") == "code",
        params.get("client_id") == CFG.client_id,
        params.get("redirect_uri") == CFG.callback,
        params.get("resource") == CFG.resource,
        parse_scope(params.get("scope", "")),
        params.get("code_challenge_method") == "S256",
        valid_pkce_challenge(params.get("code_challenge", "")),
        len(params.get("state", "")) <= 2048,
    ])


def new_access(scope: str) -> tuple[str, str, int]:
    now = int(time.time())
    access = jwt.encode({
        "iss": CFG.issuer, "aud": CFG.resource,
        "sub": CFG.username, "client_id": CFG.client_id,
        "scope": "krw:read", "iat": now, "nbf": now, "exp": now + 900,
        "jti": secrets.token_urlsafe(20),
    }, CFG.signing_key, algorithm="HS256")
    refresh = secrets.token_urlsafe(48)
    return access, refresh, now + (7 * 86400)


def token_response(scope: str) -> Response:
    access, refresh, deadline = new_access(scope)
    with tx() as db:
        db.execute("INSERT INTO refresh_tokens (token_hash, expires, scope) VALUES (?, ?, ?)",
                   (digest(refresh), deadline, "krw:read"))
    return JSONResponse({"access_token": access, "token_type": "Bearer", "expires_in": 900,
                         "refresh_token": refresh, "scope": "krw:read"}, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


def invalid_request(description: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": "invalid_request", "error_description": description}, status_code=status,
                        headers={"Cache-Control": "no-store"})


def oauth_error(code: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status, headers={"Cache-Control": "no-store"})


@app.middleware("http")
async def protection_headers(request: Request, call_next):
    res = await call_next(request)
    res.headers["Referrer-Policy"] = "no-referrer"
    res.headers["X-Content-Type-Options"] = "nosniff"
    res.headers["X-Frame-Options"] = "DENY"
    res.headers["Cache-Control"] = "no-store"
    return res


@app.get("/.well-known/oauth-authorization-server")
async def auth_metadata():
    return {
        "issuer": CFG.issuer, "authorization_endpoint": ORIGIN + "/authorize",
        "token_endpoint": ORIGIN + "/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": ["krw:read", "offline_access"],
    }


@app.get("/.well-known/oauth-protected-resource")
@app.get("/.well-known/oauth-protected-resource/mcp")
async def resource_metadata():
    return {"resource": CFG.resource, "authorization_servers": [CFG.issuer],
            "scopes_supported": ["krw:read"], "bearer_methods_supported": ["header"]}


@app.get("/authorize", response_class=HTMLResponse)
async def authorize(request: Request):
    p = dict(request.query_params)
    if not request_args_valid(p):
        return invalid_request("Invalid OAuth client, callback, PKCE challenge, resource or scope")
    nonce = secrets.token_urlsafe(32)
    now = int(time.time())
    with tx() as db:
        db.execute("DELETE FROM logins WHERE expires < ?", (now,))
        db.execute("INSERT INTO logins(nonce_hash,expires,challenge,scope,state) VALUES (?,?,?,?,?)",
                   (digest(nonce), now + 300, p["code_challenge"], p["scope"], p.get("state", "")))
    form_html = login_form(
        action="/authorize", nonce=nonce, title="Connect to ChatGPT",
        description="Sign in to authorize ChatGPT read-only access to your Remote-MCP workspace.",
        button_text="Sign in and authorize",
        help_text="Use your Gateway account. Your Agent token is never required here.",
    )
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in | Remote-MCP</title><style>{STYLES}</style></head>
<body><main class="page">{form_html}</main>
<script src="/login-guard.js" defer></script></body></html>'''
    # Chromium/Edge enforce CSP form-action on redirects after a form POST.
    # The login POST goes to this server, then HTTP 303 redirects to ChatGPT.
    # Allow only the registered OAuth callback *origin*, not arbitrary sites.
    callback_url = urlparse(CFG.callback)
    callback_origin = f"{callback_url.scheme}://{callback_url.netloc}"
    csp = (
        "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
        f"form-action 'self' {callback_origin}; base-uri 'none'; frame-ancestors 'none'"
    )
    return HTMLResponse(page, headers={"Content-Security-Policy": csp})


@app.get("/login-guard.js", include_in_schema=False)
async def login_guard_js():
    # Prevent accidental double-clicks and duplicate native browser submissions.
    # Server-side replay handling remains necessary if JS is unavailable.
    script = r"""(() => {
const form = document.getElementById('krw-login-form');
if (!form) return;
const username = form.querySelector('input[name="username"]');
const cleanUsername = () => {
  if (username) username.value = username.value.replace(/\s+/g, '');
};
if (username) {
  username.addEventListener('input', cleanUsername);
  username.addEventListener('change', cleanUsername);
}
let sent = false;
form.addEventListener('submit', (event) => {
  cleanUsername();
  if (sent) { event.preventDefault(); return; }
  sent = true;
  const button = form.querySelector('button[type=submit]');
  if (button) { button.disabled = true; button.textContent = 'Signing in...'; }
});
})();"""
    return Response(script, media_type="application/javascript", headers={"Cache-Control": "no-store"})


async def form_params(request: Request) -> dict[str, str] | None:
    if not request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
        return None
    body = await request.body()
    if len(body) > 8192:
        return None
    try:
        parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=16)
        if any(len(v) != 1 for v in parsed.values()):
            return None
        return {k: v[0] for k, v in parsed.items()}
    except (ValueError, UnicodeError):
        return None


def duplicate_login_response(db: sqlite3.Connection, nonce: str, now: int) -> Response:
    """Return the original callback for a bounded, authenticated duplicate submit.

    The caller MUST already have verified username/password and origin. We never
    create a second authorization code, and /token still accepts the code once.
    """
    row = db.execute(
        "SELECT state, used_at FROM logins WHERE nonce_hash=? AND used=1 AND expires>?",
        (digest(nonce), now),
    ).fetchone()
    if row and row[1] is not None and 0 <= now - row[1] <= 20:
        code = stable_authorization_code(nonce)
        code_row = db.execute(
            "SELECT used, expires FROM codes WHERE code_hash=?", (digest(code),)
        ).fetchone()
        if code_row and not code_row[0] and code_row[1] > now:
            logging.getLogger("krw.oauth").info("Duplicate login submission; resending original callback")
            return authorization_redirect(code, row[0])
        if code_row and code_row[0]:
            return HTMLResponse(
                "<h1>Already signed in</h1><p>This login was processed. Return to ChatGPT to continue.</p>",
                status_code=200,
            )
    return HTMLResponse(
        "<h1>Login was already submitted</h1><p>Return to ChatGPT and start a new Connect attempt.</p>",
        status_code=409,
    )


@app.post("/authorize")
async def authorize_login(request: Request):
    origin = request.headers.get("origin")
    # Some browser/privacy contexts submit a form with the literal Origin: null.
    # This is NOT proof of a trusted origin. Authorization still requires the
    # unpredictable, short-lived one-use login nonce, the correct password,
    # exact registered callback/client and PKCE S256 validation. Keep denying
    # any other unexpected Origin and keep TrustedHostMiddleware enabled.
    if origin not in (None, ORIGIN, "null"):
        # Log only the origin/host, never cookies, passwords, state, or OAuth query parameters.
        logging.getLogger("krw.oauth").warning(
            "Rejected OAuth login origin=%r expected=%r host=%r",
            origin[:200], ORIGIN, request.headers.get("host", "")[:200],
        )
        return invalid_request("Invalid request origin", 403)
    p = await form_params(request)
    raw_username = p.get("username", "") if p else ""
    normalized_username = normalize_username(raw_username)
    if (not p or len(p.get("nonce", "")) > 256 or len(raw_username) > 256
            or len(normalized_username) > 64):
        return invalid_request("Invalid login form")
    now = int(time.time())
    with tx() as db:
        db.execute("DELETE FROM attempts WHERE timestamp < ?", (now - 900,))
        attempts = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        if attempts >= 10:
            return invalid_request("Too many login attempts. Try again later.", 429)
        row = db.execute(
            "SELECT challenge, scope, state, used, used_at FROM logins "
            "WHERE nonce_hash=? AND expires>?",
            (digest(p.get("nonce", "")), now),
        ).fetchone()
        if row is None:
            return invalid_request("Login session expired. Restart Connect from ChatGPT.")
        db.execute("INSERT INTO attempts(timestamp) VALUES (?)", (now,))
    if not (hmac.compare_digest(normalized_username, CFG.username) and check_password(p.get("password", ""))):
        return HTMLResponse("<h1>Invalid credentials</h1><p>Please start the ChatGPT connection again.</p>", status_code=401)

    code = stable_authorization_code(p["nonce"])
    if row[3]:
        with tx() as db:
            return duplicate_login_response(db, p["nonce"], now)

    with tx() as db:
        updated = db.execute(
            "UPDATE logins SET used=1, used_at=? WHERE nonce_hash=? AND used=0 AND expires>?",
            (now, digest(p["nonce"]), now),
        ).rowcount
        if updated != 1:
            # Covers a concurrent double submit where both requests initially
            # observed used=0 but only one may atomically consume the nonce.
            return duplicate_login_response(db, p["nonce"], now)
        db.execute("INSERT INTO codes(code_hash,expires,challenge,scope) VALUES(?,?,?,?)",
                   (digest(code), now + 90, row[0], row[1]))
    return authorization_redirect(code, row[2])



def check_client_auth(request: Request, p: dict[str, str]) -> bool:
    client_id, client_secret = p.get("client_id", ""), p.get("client_secret", "")
    auth = request.headers.get("authorization", "")
    if auth.startswith("Basic "):
        try:
            userpass = base64.b64decode(auth[6:], validate=True).decode("utf-8")
            client_id, client_secret = userpass.split(":", 1)
        except (ValueError, UnicodeError):
            return False
    try:
        supplied = base64.urlsafe_b64decode(client_secret + "=" * (-len(client_secret) % 4))
    except (ValueError, base64.binascii.Error):
        return False
    return hmac.compare_digest(client_id, CFG.client_id) and hmac.compare_digest(supplied, CLIENT_SECRET)


@app.post("/token")
async def exchange_token(request: Request):
    p = await form_params(request)
    if p is None:
        return oauth_error("invalid_request")
    if not check_client_auth(request, p):
        return oauth_error("invalid_client", 401)
    if p.get("resource") != CFG.resource:
        return oauth_error("invalid_target")
    grant = p.get("grant_type")
    now = int(time.time())
    if grant == "authorization_code":
        code, verifier = p.get("code", ""), p.get("code_verifier", "")
        if p.get("redirect_uri") != CFG.callback or not valid_verifier(verifier):
            return oauth_error("invalid_grant")
        with tx() as db:
            row = db.execute("SELECT challenge,scope FROM codes WHERE code_hash=? AND used=0 AND expires>?",
                             (digest(code), now)).fetchone()
            if row is None or not hmac.compare_digest(pkce_s256(verifier), row[0]):
                return oauth_error("invalid_grant")
            db.execute("UPDATE codes SET used=1 WHERE code_hash=?", (digest(code),))
            scope = row[1]
        return token_response(scope)
    if grant == "refresh_token":
        refresh = p.get("refresh_token", "")
        with tx() as db:
            row = db.execute("SELECT scope FROM refresh_tokens WHERE token_hash=? AND used=0 AND expires>?",
                             (digest(refresh), now)).fetchone()
            if row is None:
                return oauth_error("invalid_grant")
            db.execute("UPDATE refresh_tokens SET used=1 WHERE token_hash=?", (digest(refresh),))
        return token_response(row[0])
    return oauth_error("unsupported_grant_type")


# This is a fixed, loopback-only proxy into the existing MCP SDK server.
# MCP auth checks live in the backend, not only this proxy.
#
# Modern MCP (2026-07-28) mirrors JSON-RPC method/params into headers. Losing
# Mcp-Method, Mcp-Name or Mcp-Param-* can cause the backend to reject otherwise
# valid authenticated requests with HTTP 400 (HeaderMismatch). Explicitly allow
# these protocol headers; do NOT blindly forward client-controlled headers.
_MCP_STANDARD_HEADERS = frozenset({
    "content-type", "accept", "authorization", "mcp-protocol-version",
    "mcp-session-id", "mcp-method", "mcp-name", "last-event-id",
})
_MCP_PARAM_NAME = re.compile(r"mcp-param-[a-z0-9_-]{1,80}\Z")


def mcp_forward_headers(request: Request) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, value in request.headers.items():
        name = name.lower()
        if name not in _MCP_STANDARD_HEADERS and not _MCP_PARAM_NAME.fullmatch(name):
            continue
        # Bound values without logging them. Some Mcp-Param-* values are Base64.
        if len(value) > 16384 or "\r" in value or "\n" in value:
            raise ValueError("Invalid MCP request header")
        result[name] = value
    return result


# Never log access tokens, code_verifier, MCP argument bodies or raw headers.
# The diagnostic captures only a safe protocol error category, HTTP status and
# the JSON-RPC method name from an explicit allowlist.
_MCP_DISCOVERY_METHODS = frozenset({
    "initialize", "notifications/initialized", "tools/list", "server/discover",
})


def discovery_method(raw: bytes) -> str:
    try:
        method = json.loads(raw).get("method", "")
        return method if method in _MCP_DISCOVERY_METHODS else "other"
    except (ValueError, TypeError, AttributeError):
        return "other"


def safe_mcp_error_category(body: bytes) -> str:
    try:
        msg = json.loads(body).get("error", {}).get("message", "")
        if not isinstance(msg, str):
            return "other"
        msg = msg.lower()
        if "header" in msg or "mismatch" in msg:
            return "header-validation"
        if "protocol" in msg or "version" in msg:
            return "protocol-version"
        if "session" in msg:
            return "session"
        if "request" in msg or "bad" in msg:
            return "invalid-request"
    except (ValueError, TypeError, AttributeError):
        pass
    return "other"


def log_mcp_proxy_failure(source: str, status: int, request_id: str,
                          method: str, category: str) -> None:
    """Optional sanitized diagnostics. Never log MCP arguments or auth headers."""
    if os.getenv("KRW_MCP_LOG_PROTOCOL_ERRORS", "0") == "1":
        logging.getLogger("krw.mcp").warning(
            "MCP %s HTTP %d: request_id=%s method=%s category=%s",
            source, status, request_id, method, category,
        )


@app.api_route("/mcp", methods=["POST", "GET", "DELETE"])
async def mcp_proxy(request: Request):
    # A generated ID traces frontend/backend errors, not upstream denials.
    request_id = secrets.token_hex(12)
    raw = await request.body()
    method = discovery_method(raw)
    if len(raw) > 1024 * 1024:
        log_mcp_proxy_failure("frontend", 413, request_id, method, "request-too-large")
        res = invalid_request("MCP request too large", 413)
        res.headers["X-KRW-Request-ID"] = request_id
        return res
    try:
        headers = mcp_forward_headers(request)
    except ValueError:
        log_mcp_proxy_failure("frontend", 400, request_id, method, "header-validation")
        res = invalid_request("Invalid MCP request header")
        res.headers["X-KRW-Request-ID"] = request_id
        return res
    try:
        async with httpx.AsyncClient(timeout=45, trust_env=False, follow_redirects=False) as client:
            resp = await client.request(request.method, "http://127.0.0.1:8767/mcp", content=raw, headers=headers)
    except (httpx.TimeoutException, httpx.RequestError):
        log_mcp_proxy_failure("frontend", 503, request_id, method, "backend-unavailable")
        return JSONResponse({"error": "local MCP backend unavailable"}, status_code=503,
                            headers={"X-KRW-Request-ID": request_id})
    if resp.status_code >= 400:
        log_mcp_proxy_failure("backend", resp.status_code, request_id, method,
                              safe_mcp_error_category(resp.content))
    keep = {k: v for k, v in resp.headers.items() if k.lower() in (
        "content-type", "www-authenticate", "mcp-session-id", "mcp-protocol-version", "cache-control"
    )}
    keep["X-KRW-Request-ID"] = request_id
    return Response(resp.content[:2 * 1024 * 1024], status_code=resp.status_code, headers=keep)



# Northflank deployment: same protected frontend, restricted outbound-agent ingress.
# Only register/poll/result/enroll (+ non-sensitive health) are exposed.
# The relay controller remains bound to loopback and is NOT routed here.
from gateway.agent_ingress import app as _krw_agent_ingress
app.include_router(_krw_agent_ingress.router)

init_db()

# Authenticated browser pairing: same owner credentials, separate short-lived
# HttpOnly session, strict same-origin POSTs, CSRF, localhost-only control relay.
# Enabled only alongside device enrollment enrollment and its admin opt-in flag.
from gateway.device_admin_ui import build_admin_router
app.include_router(build_admin_router(
    origin=ORIGIN, db_path=DB_FILE, username=CFG.username,
    verify_password=check_password, csrf_secret=CFG.signing_key,
    control_token=os.environ.get("KRW_CONTROL_TOKEN", ""),
    enabled=(os.getenv("KRW_DEVICE_ENROLLMENT_ENABLED", "0") == "1" and
             os.getenv("KRW_DEVICE_ADMIN_TOOLS_ENABLED", "0") == "1"),
    form_reader=form_params,
))

# Public installer; only explicit read-only Agent files are downloadable.
from gateway.bootstrap import router as _agent_bootstrap_router
app.include_router(_agent_bootstrap_router)

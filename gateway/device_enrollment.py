"""Persistent approval-gated, per-device credentials.

Enrollment is opt-in, existing KRW_DEVICE_TOKENS_JSON credentials remain valid.
No bearer secrets or verification codes are written to SQLite.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

DEVICE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
CODE_RE = re.compile(r"^[A-Z2-7]{12}$")
ENROLLMENT_TTL = 600
MAX_PENDING = 32
MAX_ATTEMPTS = 5


def token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def pairing_code(token: str, challenge: str) -> str:
    raw = hmac.digest(token.encode("utf-8"), challenge.encode("ascii"), "sha256")
    return base64.b32encode(raw[:8]).decode("ascii").rstrip("=")[:12]


class DeviceEnrollmentStore:
    def __init__(self, db_path: str, legacy_device_ids: set[str] | None = None):
        if not db_path:
            raise ValueError("Persistent enrollment database path is required")
        self.path = Path(db_path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.legacy_device_ids = set(legacy_device_ids or ())
        self.lock = threading.RLock()
        with self._connect() as db:
            db.executescript(
                """CREATE TABLE IF NOT EXISTS krw_enrolled_devices (
                       device_id TEXT PRIMARY KEY,
                       token_sha256 TEXT NOT NULL,
                       enrolled_at INTEGER NOT NULL,
                       revoked_at INTEGER
                   );
                   CREATE TABLE IF NOT EXISTS krw_pending_enrollments (
                       device_id TEXT PRIMARY KEY,
                       token_sha256 TEXT NOT NULL,
                       code_sha256 TEXT NOT NULL,
                       challenge TEXT NOT NULL,
                       hostname TEXT NOT NULL,
                       platform TEXT NOT NULL,
                       workspace TEXT NOT NULL,
                       created_at INTEGER NOT NULL,
                       expires_at INTEGER NOT NULL,
                       failed_attempts INTEGER NOT NULL DEFAULT 0
                   );"""
            )
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.path), timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _prune(db: sqlite3.Connection, now: int) -> None:
        db.execute("DELETE FROM krw_pending_enrollments WHERE expires_at<=?", (now,))

    def authenticated(self, device_id: str, token: str) -> bool:
        with self.lock, self._connect() as db:
            row = db.execute(
                "SELECT token_sha256,revoked_at FROM krw_enrolled_devices WHERE device_id=?",
                (device_id,),
            ).fetchone()
        return bool(row and row["revoked_at"] is None
                    and hmac.compare_digest(row["token_sha256"], token_digest(token)))

    def _reserved(self, db: sqlite3.Connection, device_id: str) -> bool:
        return (device_id in self.legacy_device_ids
                or db.execute("SELECT 1 FROM krw_enrolled_devices WHERE device_id=?",
                              (device_id,)).fetchone() is not None)

    def enroll(self, info, token: str) -> dict:
        if not DEVICE_ID_RE.fullmatch(info.device_id):
            raise HTTPException(400, "Invalid device ID")
        if not 43 <= len(token) <= 256:
            raise HTTPException(400, "Invalid Agent secret length")
        now = int(time.time())
        secret_hash = token_digest(token)
        with self.lock, self._connect() as db:
            self._prune(db, now)
            if self._reserved(db, info.device_id):
                raise HTTPException(409, "Device identity already assigned")
            existing = db.execute(
                "SELECT * FROM krw_pending_enrollments WHERE device_id=?",
                (info.device_id,),
            ).fetchone()
            if existing:
                if not hmac.compare_digest(existing["token_sha256"], secret_hash):
                    raise HTTPException(409, "Device enrollment already pending")
                return {"status": "pending", "challenge": existing["challenge"],
                        "expires_in": max(0, existing["expires_at"] - now)}
            if db.execute("SELECT count(*) FROM krw_pending_enrollments").fetchone()[0] >= MAX_PENDING:
                raise HTTPException(429, "Too many pending enrollments")
            challenge = secrets.token_urlsafe(24)
            code = pairing_code(token, challenge)
            db.execute(
                """INSERT INTO krw_pending_enrollments
                   (device_id,token_sha256,code_sha256,challenge,hostname,platform,
                    workspace,created_at,expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (info.device_id, secret_hash, token_digest(code), challenge,
                 info.hostname, info.platform, info.workspace, now, now + ENROLLMENT_TTL),
            )
        return {"status": "pending", "challenge": challenge, "expires_in": ENROLLMENT_TTL}

    def pending(self) -> list[dict]:
        with self.lock, self._connect() as db:
            self._prune(db, int(time.time()))
            return [dict(row) for row in db.execute(
                """SELECT device_id,hostname,platform,workspace,created_at,expires_at,
                          failed_attempts FROM krw_pending_enrollments
                   ORDER BY created_at ASC"""
            ).fetchall()]

    def approve(self, device_id: str, code: str) -> dict:
        if not DEVICE_ID_RE.fullmatch(device_id):
            raise HTTPException(400, "Invalid device ID")
        code = code.strip().upper().replace("-", "")
        if not CODE_RE.fullmatch(code):
            raise HTTPException(400, "Invalid pairing code")
        with self.lock, self._connect() as db:
            self._prune(db, int(time.time()))
            request = db.execute(
                "SELECT * FROM krw_pending_enrollments WHERE device_id=?", (device_id,)
            ).fetchone()
            if not request:
                raise HTTPException(404, "Pending enrollment not found")
            if request["failed_attempts"] >= MAX_ATTEMPTS:
                raise HTTPException(429, "Pairing attempts exhausted until expiration")
            if not hmac.compare_digest(request["code_sha256"], token_digest(code)):
                db.execute(
                    """UPDATE krw_pending_enrollments
                       SET failed_attempts=failed_attempts+1 WHERE device_id=?""",
                    (device_id,),
                )
                db.commit()  # save failed attempt even though HTTP request will fail
                raise HTTPException(403, "Incorrect pairing code")
            if self._reserved(db, device_id):
                raise HTTPException(409, "Device identity already assigned")
            db.execute(
                """INSERT INTO krw_enrolled_devices (device_id,token_sha256,enrolled_at)
                   VALUES (?,?,?)""",
                (device_id, request["token_sha256"], int(time.time())),
            )
            db.execute("DELETE FROM krw_pending_enrollments WHERE device_id=?", (device_id,))
        return {"device_id": device_id, "status": "approved"}

    def registered(self) -> list[dict]:
        with self.lock, self._connect() as db:
            return [dict(row) for row in db.execute(
                """SELECT device_id,enrolled_at,revoked_at FROM krw_enrolled_devices
                   ORDER BY device_id"""
            ).fetchall()]

    def revoke(self, device_id: str) -> dict:
        if not DEVICE_ID_RE.fullmatch(device_id):
            raise HTTPException(400, "Invalid device ID")
        with self.lock, self._connect() as db:
            updated = db.execute(
                """UPDATE krw_enrolled_devices SET revoked_at=?
                   WHERE device_id=? AND revoked_at IS NULL""",
                (int(time.time()), device_id),
            )
            if updated.rowcount != 1:
                raise HTTPException(404, "Active enrolled device not found")
        return {"device_id": device_id, "status": "revoked"}

"""Isolated device enrollment end-to-end smoke test (no production access)."""
from __future__ import annotations

import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx
import uvicorn

from gateway.relay import State, create_app

ROOT = Path(__file__).resolve().parent.parent
CTRL = secrets.token_urlsafe(40)
DEVICES = ("enrollment-smoke-a", "enrollment-smoke-b")


def poll_until(predicate, timeout=30):
    expires = time.monotonic() + timeout
    while time.monotonic() < expires:
        result = predicate()
        if result:
            return result
        time.sleep(0.2)
    raise AssertionError("staging operation timed out")


with tempfile.TemporaryDirectory(prefix="krw-device-enrollment-staging-") as tmp:
    td = Path(tmp)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        PORT = sock.getsockname()[1]
    state = State({}, CTRL, enrollment_enabled=True, enrollment_db_path=str(td / "device-credentials.sqlite"))
    app = create_app(state)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{PORT}"
    ctrl_headers = {"X-Control-Token": CTRL}
    procs = {}
    logs = {}
    tokens = {}
    try:
        with httpx.Client(base_url=base, timeout=25, trust_env=False) as http:
            poll_until(lambda: http.get("/health").status_code == 200, timeout=12)
            for dev in DEVICES:
                workspace = td / dev
                workspace.mkdir()
                token = secrets.token_urlsafe(32)
                tokens[dev] = token
                env = dict(os.environ)
                env.update({
                    "KRW_DEVICE_ID": dev,
                    "KRW_AGENT_TOKEN": token,
                    "KRW_AUTO_ENROLL": "1",
                    "KRW_WORKSPACE_ROOT": str(workspace),
                    "KRW_RELAY_URL": base,
                    "KRW_COMMANDS_ENABLED": "0",
                    "KRW_ALLOW_FILE_WRITES": "0",
                    "KRW_ALLOW_GIT_WRITES": "0",
                    "KRW_ALLOW_GIT_PUSH": "0",
                    "KRW_ALLOW_TEST_TASKS": "0",
                    "PYTHONPATH": str(ROOT) + os.pathsep + os.getenv("PYTHONPATH", ""),
                })
                lf = td / f"{dev}.log"
                logs[dev] = lf
                writer = open(lf, "w", encoding="utf-8")
                proc = subprocess.Popen([sys.executable, "-m", "agent.agent"],
                                        cwd=ROOT, env=env, stdout=writer,
                                        stderr=subprocess.STDOUT)
                procs[dev] = (proc, writer)
            # Enrollment requests must appear, but devices must not be online before approval.
            poll_until(lambda: len(http.get("/v1/control/enrollments/pending", headers=ctrl_headers).json()["devices"]) == 2)
            assert not state.list_devices()
            print("STAGING pending_enrollments=2, preapproval_devices=0", flush=True)
            for dev in DEVICES:
                def code_in_log():
                    found = re.search(r"verification_code=([A-Z2-7]{12})", logs[dev].read_text(errors="replace"))
                    return found.group(1) if found else None
                code = poll_until(code_in_log, timeout=20)
                response = http.post("/v1/control/enrollments/approve",headers=ctrl_headers,
                                     json={"device_id":dev, "pairing_code":code})
                assert response.status_code == 200, (dev, response.status_code)
            def both_online():
                rows = http.get("/v1/control/devices",headers=ctrl_headers).json()["devices"]
                return len(rows) == 2 and all(r["online"] for r in rows)
            poll_until(both_online, timeout=30)
            for dev in DEVICES:
                response = http.post("/v1/control/dispatch",headers=ctrl_headers,
                                     json={"device_id":dev, "operation":"get_device_info", "arguments":{}})
                assert response.status_code == 200 and response.json()["ok"], (dev,response.text[:300])
            print("STAGING approved=2, agents_online=2, dispatch_success=2",flush=True)
            response=http.post("/v1/control/enrollments/revoke",headers=ctrl_headers,
                               json={"device_id":DEVICES[0]})
            assert response.status_code==200
            r=http.post("/v1/agent/poll",json={"device_id":DEVICES[0]},
                        headers={"Authorization":"Bearer "+tokens[DEVICES[0]]})
            assert r.status_code==401
            response=http.post("/v1/control/dispatch",headers=ctrl_headers,
                               json={"device_id":DEVICES[1],"operation":"get_device_info","arguments":{}})
            assert response.status_code==200 and response.json()["ok"]
            print("STAGING revoked_agent_401=yes, unaffected_agent_dispatch=PASS",flush=True)
            raw=(td/"device-credentials.sqlite").read_bytes()
            assert all(t.encode() not in raw for t in tokens.values())
            print("STAGING no_plaintext_secrets_in_db=PASS",flush=True)
    finally:
        for proc,writer in procs.values():
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            writer.close()
        server.should_exit = True
        thread.join(timeout=7)
print("DEVICE_ENROLLMENT_STAGING_E2E_PASS", flush=True)

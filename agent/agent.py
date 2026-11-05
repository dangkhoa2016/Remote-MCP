"""Outbound-only Agent: uses HTTPS polls; no inbound SSH or listener."""
from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import signal
import time
from pathlib import Path

import httpx

from agent.worker import WorkspaceError
from agent.workspace_routes import WorkspaceRouter
import base64
import hmac

LOG = logging.getLogger("krw.agent")
STOP = False


def verification_code(token: str, challenge: str) -> str:
    raw = hmac.digest(token.encode("utf-8"), challenge.encode("ascii"), "sha256")
    return base64.b32encode(raw[:8]).decode("ascii").rstrip("=")[:12]


def stop(*_):
    global STOP
    STOP = True


def run() -> None:
    device_id = os.getenv("KRW_DEVICE_ID", "")
    token = os.getenv("KRW_AGENT_TOKEN", "")
    url = os.getenv("KRW_RELAY_URL", "http://127.0.0.1:8766").rstrip("/")
    root = os.getenv("KRW_WORKSPACE_ROOT", "")
    auto_enroll = os.getenv("KRW_AUTO_ENROLL", "0") == "1"
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", device_id):
        raise SystemExit("Set a valid KRW_DEVICE_ID")
    if len(token) < 32 or not root:
        raise SystemExit("Set KRW_AGENT_TOKEN (>=32 chars) and KRW_WORKSPACE_ROOT")
    if not (url.startswith("https://") or url.startswith("http://127.0.0.1:") or url.startswith("http://localhost:")):
        raise SystemExit("Remote KRW_RELAY_URL requires HTTPS")
    worker = WorkspaceRouter.from_env(Path(root))
    headers = {"Authorization": f"Bearer {token}"}
    info = {"device_id": device_id, "hostname": platform.node()[:128] or "unknown",
            "platform": platform.system()[:128], "workspace": worker.workers["default"].root.name[:128]}
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        with httpx.Client(base_url=url, headers=headers, timeout=15, follow_redirects=False, trust_env=False) as client:
            registered = False
            last_pairing_code = ""
            while not STOP:
                try:
                    if not registered:
                        response = client.post("/v1/agent/register", json=info)
                        if response.status_code == 401 and auto_enroll:
                            enrollment = client.post("/v1/agent/enroll", json=info)
                            enrollment.raise_for_status()
                            code = verification_code(token, enrollment.json()["challenge"])
                            if code != last_pairing_code:
                                LOG.warning("PENDING PAIRING: device=%s verification_code=%s "
                                            "(verify directly on the device console)", device_id, code)
                                last_pairing_code = code
                            time.sleep(3)
                            continue
                        response.raise_for_status()
                        registered = True
                        last_pairing_code = ""
                        LOG.info("registered device=%s", device_id)
                    response = client.post("/v1/agent/poll", json={"device_id": device_id})
                    response.raise_for_status()
                    job = response.json().get("job")
                    if not job:
                        continue
                    try:
                        data = worker.dispatch(job["operation"], job.get("arguments", {}))
                        result = {"device_id": device_id, "job_id": job["job_id"], "ok": True, "data": data}
                    except (OSError, ValueError, WorkspaceError, subprocess.SubprocessError) as exc:
                        result = {"device_id": device_id, "job_id": job["job_id"], "ok": False,
                                  "data": {}, "error": type(exc).__name__ + ": " + str(exc)[:256]}
                    response = client.post("/v1/agent/result", json=result)
                    response.raise_for_status()
                except (httpx.HTTPError, ValueError) as exc:
                    registered = False
                    LOG.warning("relay error: %s; reconnecting", type(exc).__name__)
                    time.sleep(2)

    finally:
        worker.shutdown()


if __name__ == "__main__":
    run()

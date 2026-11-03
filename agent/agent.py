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

from agent.worker import Worker, WorkspaceError

LOG = logging.getLogger("krw.agent")
STOP = False


def stop(*_):
    global STOP
    STOP = True


def run() -> None:
    device_id = os.getenv("KRW_DEVICE_ID", "")
    token = os.getenv("KRW_AGENT_TOKEN", "")
    url = os.getenv("KRW_RELAY_URL", "http://127.0.0.1:8766").rstrip("/")
    root = os.getenv("KRW_WORKSPACE_ROOT", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", device_id):
        raise SystemExit("Set a valid KRW_DEVICE_ID")
    if len(token) < 32 or not root:
        raise SystemExit("Set KRW_AGENT_TOKEN (>=32 chars) and KRW_WORKSPACE_ROOT")
    if not (url.startswith("https://") or url.startswith("http://127.0.0.1:") or url.startswith("http://localhost:")):
        raise SystemExit("Remote KRW_RELAY_URL requires HTTPS")
    worker = Worker(Path(root), commands_enabled=os.getenv("KRW_COMMANDS_ENABLED", "0") == "1",
                    tests_enabled=os.getenv("KRW_ALLOW_TEST_COMMANDS", "0") == "1",
                    write_enabled=os.getenv("KRW_ALLOW_FILE_WRITES", "0") == "1",
                    checks_enabled=os.getenv("KRW_ALLOW_STATIC_CHECKS", "0") == "1")
    headers = {"Authorization": f"Bearer {token}"}
    info = {"device_id": device_id, "hostname": platform.node()[:128] or "unknown",
            "platform": platform.system()[:128], "workspace": worker.root.name[:128]}
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with httpx.Client(base_url=url, headers=headers, timeout=15, follow_redirects=False, trust_env=False) as client:
        registered = False
        while not STOP:
            try:
                if not registered:
                    response = client.post("/v1/agent/register", json=info)
                    response.raise_for_status()
                    registered = True
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



if __name__ == "__main__":
    run()

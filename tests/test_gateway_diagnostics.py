"""Gateway diagnostics: sanitized MCP diagnostics and bounded background-job history."""
from __future__ import annotations

import logging
import re
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from agent.long_tasks import MAX_RETAINED
from agent.worker import Worker, WorkspaceError
from test_local_auth import load_auth

TERMINAL = {"succeeded", "failed", "cancelled", "timed_out", "output_limit"}


def _done(worker, job_id, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = worker.get_cli_job({"job_id": job_id})
        if state["state"] in TERMINAL:
            return state
        time.sleep(0.02)
    raise AssertionError("CLI job failed to finish")


def test_backend_403_request_id_and_redacted_logging(monkeypatch, tmp_path, caplog):
    auth, _, _ = load_auth(monkeypatch, tmp_path)
    monkeypatch.setenv("KRW_MCP_LOG_PROTOCOL_ERRORS", "1")

    class Backend:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, *args, **kwargs):
            return httpx.Response(403, json={"error": {"message": "private-upstream-detail"}})

    monkeypatch.setattr(auth.httpx, "AsyncClient", Backend)
    with caplog.at_level(logging.WARNING, logger="krw.mcp"):
        with TestClient(auth.app, base_url="https://tunnel.test") as client:
            res = client.post("/mcp", json={"method": "tools/call", "params": {
                "name": "run_shell", "arguments": {"script": "secret-shell-script"},
            }}, headers={"Authorization": "Bearer private-access-token"})
    rid = res.headers["X-KRW-Request-ID"]
    assert res.status_code == 403 and re.fullmatch(r"[0-9a-f]{24}", rid)
    assert f"MCP backend HTTP 403: request_id={rid}" in caplog.text
    assert "method=other category=other" in caplog.text
    for secret in ("private-upstream-detail", "secret-shell-script", "private-access-token", "run_shell"):
        assert secret not in caplog.text


def test_frontend_error_is_traced_and_redacted(monkeypatch, tmp_path, caplog):
    auth, _, _ = load_auth(monkeypatch, tmp_path)
    monkeypatch.setenv("KRW_MCP_LOG_PROTOCOL_ERRORS", "1")
    with caplog.at_level(logging.WARNING, logger="krw.mcp"):
        with TestClient(auth.app, base_url="https://tunnel.test") as client:
            res = client.post("/mcp", json={"method": "tools/list"},
                              headers={"Mcp-Param-Demo": "private-" + "x" * 16390})
    assert res.status_code == 400
    assert f"request_id={res.headers['X-KRW-Request-ID']}" in caplog.text
    assert "MCP frontend HTTP 400" in caplog.text
    assert "category=header-validation" in caplog.text
    assert "private-" not in caplog.text


def test_backend_unavailable_does_not_log_exception(monkeypatch, tmp_path, caplog):
    auth, _, _ = load_auth(monkeypatch, tmp_path)
    monkeypatch.setenv("KRW_MCP_LOG_PROTOCOL_ERRORS", "1")
    class Offline:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, *args, **kwargs):
            raise httpx.ConnectError("private-backend-address")
    monkeypatch.setattr(auth.httpx, "AsyncClient", Offline)
    with caplog.at_level(logging.WARNING, logger="krw.mcp"):
        with TestClient(auth.app, base_url="https://tunnel.test") as client:
            res = client.post("/mcp", json={"method": "tools/list"})
    assert res.status_code == 503
    assert f"request_id={res.headers['X-KRW-Request-ID']}" in caplog.text
    assert "category=backend-unavailable" in caplog.text
    assert "private-backend-address" not in caplog.text


def test_request_ids_are_unique_and_not_client_controlled(monkeypatch, tmp_path, caplog):
    auth, _, _ = load_auth(monkeypatch, tmp_path)
    monkeypatch.setenv("KRW_MCP_LOG_PROTOCOL_ERRORS", "0")
    class Backend:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, *args, **kwargs):
            return httpx.Response(200, json={"ok": True})
    monkeypatch.setattr(auth.httpx, "AsyncClient", Backend)
    with caplog.at_level(logging.WARNING, logger="krw.mcp"):
        with TestClient(auth.app, base_url="https://tunnel.test") as client:
            first = client.post("/mcp", json={"method": "tools/list"},
                                headers={"X-KRW-Request-ID": "spoofed"})
            second = client.post("/mcp", json={"method": "tools/list"})
    x, y = first.headers["X-KRW-Request-ID"], second.headers["X-KRW-Request-ID"]
    assert re.fullmatch(r"[0-9a-f]{24}", x)
    assert re.fullmatch(r"[0-9a-f]{24}", y)
    assert x != y and x != "spoofed"
    assert not [r for r in caplog.records if r.name == "krw.mcp"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_old_finished_jobs_are_evicted_when_history_is_full(tmp_path):
    worker = Worker(tmp_path, cli_enabled=True)
    ids = []
    try:
        for n in range(MAX_RETAINED + 3):
            job = worker.run_cli({"argv": [sys.executable, "-c", f"print({n})"]})
            assert _done(worker, job["job_id"])["state"] == "succeeded"
            ids.append(job["job_id"])
        for job_id in ids[:3]:
            with pytest.raises(WorkspaceError, match="not found"):
                worker.get_cli_job({"job_id": job_id})
        assert len(worker.long_task_manager._jobs) == MAX_RETAINED
    finally:
        worker.long_task_manager.shutdown()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_running_job_is_preserved_during_eviction(tmp_path):
    worker = Worker(tmp_path, cli_enabled=True)
    try:
        finished = []
        for n in range(MAX_RETAINED - 1):
            job = worker.run_cli({"argv": [sys.executable, "-c", f"print({n})"]})
            assert _done(worker, job["job_id"])["state"] == "succeeded"
            finished.append(job["job_id"])
        running = worker.run_cli({"argv": [sys.executable, "-c", "import time;time.sleep(5)"]})
        deadline = time.monotonic() + 2
        while worker.get_cli_job({"job_id": running["job_id"]})["state"] == "queued":
            assert time.monotonic() < deadline
            time.sleep(0.02)
        queued = worker.run_cli({"argv": [sys.executable, "-c", "print('queued')"]})
        assert worker.get_cli_job({"job_id": running["job_id"]})["state"] == "running"
        with pytest.raises(WorkspaceError, match="not found"):
            worker.get_cli_job({"job_id": finished[0]})
        worker.cancel_cli_job({"job_id": running["job_id"]})
        assert _done(worker, running["job_id"])["state"] == "cancelled"
        assert _done(worker, queued["job_id"])["state"] == "succeeded"
    finally:
        worker.long_task_manager.shutdown()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_active_history_is_never_evicted(tmp_path, monkeypatch):
    import agent.long_tasks as tasks
    monkeypatch.setattr(tasks, "MAX_RETAINED", 1)
    worker = Worker(tmp_path, cli_enabled=True)
    try:
        running = worker.run_cli({"argv": [sys.executable, "-c", "import time;time.sleep(5)"]})
        deadline = time.monotonic() + 2
        while worker.get_cli_job({"job_id": running["job_id"]})["state"] == "queued":
            assert time.monotonic() < deadline
            time.sleep(0.02)
        with pytest.raises(WorkspaceError, match="full of active jobs"):
            worker.run_cli({"argv": [sys.executable, "-c", "print(1)"]})
        assert worker.get_cli_job({"job_id": running["job_id"]})["state"] == "running"
        worker.cancel_cli_job({"job_id": running["job_id"]})
        assert _done(worker, running["job_id"])["state"] == "cancelled"
    finally:
        worker.long_task_manager.shutdown()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_queue_full_rejection_preserves_finished_history(tmp_path, monkeypatch):
    import agent.long_tasks as tasks
    monkeypatch.setattr(tasks, "MAX_RETAINED", 4)
    worker = Worker(tmp_path, cli_enabled=True)
    try:
        old = worker.run_cli({"argv": [sys.executable, "-c", "print('old')"]})
        assert _done(worker, old["job_id"])["state"] == "succeeded"
        running = worker.run_cli({"argv": [sys.executable, "-c", "import time;time.sleep(5)"]})
        deadline = time.monotonic() + 2
        while worker.get_cli_job({"job_id": running["job_id"]})["state"] == "queued":
            assert time.monotonic() < deadline
            time.sleep(0.02)
        queued = [worker.run_cli({"argv": [sys.executable, "-c", "print('queued')"]}) for _ in range(2)]
        with pytest.raises(WorkspaceError, match="queue is full"):
            worker.run_cli({"argv": [sys.executable, "-c", "print('reject')"]})
        assert worker.get_cli_job({"job_id": old["job_id"]})["state"] == "succeeded"
        for job in queued:
            worker.cancel_cli_job({"job_id": job["job_id"]})
        worker.cancel_cli_job({"job_id": running["job_id"]})
    finally:
        worker.long_task_manager.shutdown()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_workspace_isolation_after_eviction(tmp_path, monkeypatch):
    import agent.long_tasks as tasks
    from agent.workspace_routes import WorkspaceRouter
    monkeypatch.setattr(tasks, "MAX_RETAINED", 2)
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    router = WorkspaceRouter(left, {"right": str(right)}, cli_enabled=True)
    try:
        ids = []
        for n in range(2):
            job = router.dispatch("run_cli", {"workspace_id": "default",
                                              "argv": [sys.executable, "-c", f"print({n})"]})
            deadline = time.monotonic() + 3
            while router.dispatch("get_cli_job", {"workspace_id": "default", "job_id": job["job_id"]})["state"] not in TERMINAL:
                assert time.monotonic() < deadline
                time.sleep(0.02)
            ids.append(job["job_id"])
        other = router.dispatch("run_cli", {"workspace_id": "right",
                                            "argv": [sys.executable, "-c", "print('right')"]})
        with pytest.raises(WorkspaceError, match="not found"):
            router.dispatch("get_cli_job", {"workspace_id": "right", "job_id": ids[1]})
        with pytest.raises(WorkspaceError, match="not found"):
            router.dispatch("read_cli_log", {"workspace_id": "default", "job_id": other["job_id"]})
        with pytest.raises(WorkspaceError, match="not found"):
            router.dispatch("get_cli_job", {"workspace_id": "default", "job_id": ids[0]})
    finally:
        router.shutdown()

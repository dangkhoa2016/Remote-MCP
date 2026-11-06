"""background test jobs: real asynchronous task lifecycle, bounded queues, logs and cancellation."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

from agent.long_tasks import LongTaskManager
from agent.worker import Worker, WorkspaceError
from agent.workspace_routes import WorkspaceRouter
from gateway.relay import Dispatch, State

TERMINAL = {"succeeded", "failed", "cancelled", "timed_out", "output_limit"}


def _wait(manager: LongTaskManager, job_id: str, workspace_id: str = "default",
          timeout: float = 10) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = manager.status(job_id, workspace_id=workspace_id)
        if state["state"] in TERMINAL:
            return state
        time.sleep(0.04)
    raise AssertionError(f"task did not finish: {job_id}")


def _file(root: Path, name: str, body: str) -> str:
    tests = root / "tests"
    tests.mkdir(exist_ok=True)
    (tests / name).write_text(body, encoding="utf-8")
    return f"tests/{name}"


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
def test_successful_background_task_and_paged_logs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KRW_AGENT_TOKEN", "SECRET_AGENT_TOKEN_MUST_NOT_APPEAR")
    monkeypatch.setenv("KRW_GIT_PUSH_TOKEN", "SECRET_GITHUB_TOKEN_MUST_NOT_APPEAR")
    name = _file(tmp_path, "test_ok.py", (
        "import os\n"
        "def test_ok():\n"
        "    assert 'KRW_AGENT_TOKEN' not in os.environ\n"
        "    assert 'KRW_GIT_PUSH_TOKEN' not in os.environ\n"
        "    print('SMOKE_test_OK')\n"
    ))
    w = Worker(tmp_path, tasks_enabled=True, test_tasks_enabled=True,
               long_tasks_enabled=True)
    start = time.monotonic()
    result = w.start_long_task({"task_id": "pytest", "target": name})
    assert time.monotonic() - start < 2
    assert len(result["job_id"]) == 32
    final = _wait(w.long_task_manager, result["job_id"])
    assert final["state"] == "succeeded" and final["exit_code"] == 0, final
    assert final["started_at"] and final["finished_at"]
    parts = []
    offset = 0
    while True:
        chunk = w.read_long_task_log({"job_id": result["job_id"], "offset": offset, "max_bytes": 32})
        parts.append(chunk["text"])
        offset = chunk["next_offset"]
        if offset == chunk["total_bytes"]:
            break
    log = "".join(parts)
    assert "1 passed" in log, log
    assert "SECRET_AGENT_TOKEN" not in log
    assert "SECRET_GITHUB_TOKEN" not in log
    assert w.get_long_task({"job_id": result["job_id"]})["state"] == "succeeded"
    w.long_task_manager.shutdown()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
def test_running_task_cancel_and_idempotent_cancel(tmp_path: Path):
    target = _file(tmp_path, "test_sleep.py",
                   "import time\ndef test_sleep():\n    time.sleep(9)\n")
    w = Worker(tmp_path, tasks_enabled=True, test_tasks_enabled=True,
               long_tasks_enabled=True)
    job = w.start_long_task({"task_id": "pytest", "target": target})
    deadline = time.monotonic() + 4
    while w.get_long_task({"job_id": job["job_id"]})["state"] == "queued" and time.monotonic() < deadline:
        time.sleep(0.02)
    cancelled = w.cancel_long_task({"job_id": job["job_id"]})
    assert cancelled["cancel_requested"]
    final = _wait(w.long_task_manager, job["job_id"])
    assert final["state"] == "cancelled", final
    assert w.cancel_long_task({"job_id": job["job_id"]})["state"] == "cancelled"
    w.long_task_manager.shutdown()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
def test_one_running_two_queued_capacity_and_cancel(tmp_path: Path):
    target = _file(tmp_path, "test_queue.py",
                   "import time\ndef test_queue():\n    time.sleep(8)\n")
    w = Worker(tmp_path, tasks_enabled=True, test_tasks_enabled=True,
               long_tasks_enabled=True)
    first = w.start_long_task({"task_id": "pytest", "target": target})
    deadline = time.monotonic() + 4
    while w.get_long_task({"job_id": first["job_id"]})["state"] == "queued" and time.monotonic() < deadline:
        time.sleep(0.02)
    second = w.start_long_task({"task_id": "pytest", "target": target})
    third = w.start_long_task({"task_id": "pytest", "target": target})
    assert w.get_long_task({"job_id": second["job_id"]})["state"] == "queued"
    assert w.get_long_task({"job_id": third["job_id"]})["state"] == "queued"
    with pytest.raises(WorkspaceError, match="queue is full"):
        w.start_long_task({"task_id": "pytest", "target": target})
    for item in (second, third, first):
        w.cancel_long_task({"job_id": item["job_id"]})
    for item in (first, second, third):
        assert _wait(w.long_task_manager, item["job_id"])["state"] == "cancelled"
    w.long_task_manager.shutdown()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
def test_long_task_timeout(tmp_path: Path, monkeypatch):
    import agent.long_tasks as module
    monkeypatch.setattr(module, "MAX_TASK_SECONDS", 1)
    target = _file(tmp_path, "test_timeout.py",
                   "import time\ndef test_timeout():\n    time.sleep(9)\n")
    w = Worker(tmp_path, tasks_enabled=True, test_tasks_enabled=True,
               long_tasks_enabled=True)
    job = w.start_long_task({"task_id": "pytest", "target": target})
    final = _wait(w.long_task_manager, job["job_id"])
    assert final["state"] == "timed_out", final
    assert final["timed_out"]
    w.long_task_manager.shutdown()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
def test_long_task_output_limit(tmp_path: Path, monkeypatch):
    import agent.long_tasks as module
    monkeypatch.setattr(module, "MAX_LOG_BYTES", 512)
    target = _file(tmp_path, "test_noisy.py",
                   "def test_noisy():\n    print('Z' * 40000)\n    assert False\n")
    w = Worker(tmp_path, tasks_enabled=True, test_tasks_enabled=True,
               long_tasks_enabled=True)
    job = w.start_long_task({"task_id": "pytest", "target": target})
    final = _wait(w.long_task_manager, job["job_id"])
    assert final["state"] == "output_limit", final
    assert final["output_limit_hit"]
    chunk = w.read_long_task_log({"job_id": job["job_id"], "offset": 0, "max_bytes": 8192})
    assert len(chunk["text"].encode()) <= 512
    w.long_task_manager.shutdown()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
def test_cross_workspace_job_ids_are_not_accessible(tmp_path: Path):
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    target = _file(left, "test_left.py", "def test_left():\n    assert True\n")
    router = WorkspaceRouter(
        left, {"right": str(right)},
        tasks_enabled=True, test_tasks_enabled=True, long_tasks_enabled=True,
    )
    job = router.dispatch("start_long_task", {
        "workspace_id": "default", "task_id": "pytest", "target": target,
    })
    for op in ("get_long_task", "read_long_task_log", "cancel_long_task"):
        with pytest.raises(WorkspaceError, match="not found in workspace"):
            router.dispatch(op, {"workspace_id": "right", "job_id": job["job_id"]})
    assert _wait(router.long_task_manager, job["job_id"])["state"] == "succeeded"
    assert router.dispatch("get_long_task", {"job_id": job["job_id"]})["state"] == "succeeded"
    router.shutdown()


def test_invalid_ids_targets_pagination_and_disabled_gate(tmp_path: Path):
    w = Worker(tmp_path, tasks_enabled=True, test_tasks_enabled=True,
               long_tasks_enabled=False)
    with pytest.raises(WorkspaceError, match="disabled"):
        w.start_long_task({"task_id": "pytest"})
    w = Worker(tmp_path, tasks_enabled=True, test_tasks_enabled=True,
               long_tasks_enabled=True)
    for task_id in ("bash", "git_status", "pytest -k x", "rails -e production"):
        with pytest.raises(WorkspaceError, match="only allow"):
            w.start_long_task({"task_id": task_id})
    with pytest.raises(WorkspaceError, match="Invalid task job ID"):
        w.get_long_task({"job_id": "../private"})
    with pytest.raises(WorkspaceError, match="not found"):
        w.get_long_task({"job_id": "a" * 32})
    with pytest.raises(WorkspaceError, match="Invalid task log pagination"):
        w.read_long_task_log({"job_id": "a" * 32, "offset": -1})
    with pytest.raises(WorkspaceError, match="Invalid task log pagination"):
        w.read_long_task_log({"job_id": "a" * 32, "max_bytes": 100000})
    w.long_task_manager.shutdown()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
def test_shutdown_cancels_all_tasks(tmp_path: Path):
    target = _file(tmp_path, "test_wait.py",
                   "import time\ndef test_wait():\n    time.sleep(9)\n")
    manager = LongTaskManager()
    w = Worker(tmp_path, tasks_enabled=True, test_tasks_enabled=True,
               long_tasks_enabled=True, long_task_manager=manager)
    first = w.start_long_task({"task_id": "pytest", "target": target})
    second = w.start_long_task({"task_id": "pytest", "target": target})
    manager.shutdown()
    assert _wait(manager, first["job_id"])["state"] == "cancelled"
    assert _wait(manager, second["job_id"])["state"] == "cancelled"
    with pytest.raises(WorkspaceError, match="shutting down"):
        w.start_long_task({"task_id": "pytest", "target": target})


@pytest.mark.asyncio
async def test_relay_requires_explicit_opt_in():
    base = {"local-dev": "a" * 48}
    body = Dispatch(device_id="local-dev", operation="start_long_task",
                    arguments={"task_id": "pytest", "target": "tests/test_ok.py"})
    for kw in (
        {},
        {"tasks_enabled": True, "test_tasks_enabled": True},
        {"tasks_enabled": True, "long_tasks_enabled": True},
        {"test_tasks_enabled": True, "long_tasks_enabled": True},
    ):
        with pytest.raises(HTTPException) as exc:
            await State(base, "b" * 48, **kw).submit(body)
        assert exc.value.status_code == 403
    enabled = State(
        base, "b" * 48, tasks_enabled=True,
        test_tasks_enabled=True, long_tasks_enabled=True,
    )
    for op in ("start_long_task", "get_long_task", "read_long_task_log", "cancel_long_task"):
        with pytest.raises(HTTPException) as exc:
            await enabled.submit(Dispatch(device_id="local-dev", operation=op,
                                          arguments={"task_id": "pytest"}))
        assert exc.value.status_code == 503
    with pytest.raises(HTTPException) as exc:
        await enabled.submit(Dispatch(device_id="local-dev", operation="start_long_task",
                                      arguments={"task_id": "bash"}))
    assert exc.value.status_code == 403

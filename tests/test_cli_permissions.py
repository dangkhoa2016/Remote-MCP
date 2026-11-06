"""CLI permissions: explicit CLI execution gates and noninteractive interpreter commands."""
from __future__ import annotations
import os
import time
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from agent.worker import Worker, WorkspaceError
from agent.workspace_routes import WorkspaceRouter
from gateway.relay import Dispatch, State



TERMINAL = {"succeeded", "failed", "cancelled", "timed_out", "output_limit"}


def _done(worker: Worker, job_id: str, timeout: float = 8) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = worker.get_cli_job({"job_id": job_id})
        if state["state"] in TERMINAL:
            return state
        time.sleep(0.03)
    raise AssertionError("CLI job did not finish")


def _output(worker: Worker, job_id: str) -> str:
    return worker.read_cli_log({"job_id": job_id})["text"]


def test_cli_denied_by_default(tmp_path):
    with pytest.raises(WorkspaceError, match="CLI execution disabled"):
        Worker(tmp_path).dispatch("run_cli", {"argv": ["python3", "--version"]})


def test_cli_invalid_args(tmp_path):
    worker = Worker(tmp_path, cli_enabled=True)
    for bad in (None, "ls", [], [""], [0], ["bash", "\x00"], ["a" * 4097], ["bash"] * 33):
        with pytest.raises(WorkspaceError, match="Invalid CLI argv"):
            worker.dispatch("run_cli", {"argv": bad})


@pytest.mark.skipif(os.name != "posix", reason="Requires POSIX process groups")
def test_cli_exec_literal_python_arguments(tmp_path):
    worker = Worker(tmp_path, cli_enabled=True)
    result = worker.dispatch("run_cli", {"argv": [
        sys.executable, "-c", "import sys; print(sys.argv[1])", "$HOME;echo not-expanded"
    ]})
    assert result["timeout_seconds"] == 300
    assert _done(worker, result["job_id"])["exit_code"] == 0
    assert "$HOME;echo not-expanded" in _output(worker, result["job_id"])
    worker.long_task_manager.shutdown()


@pytest.mark.skipif(os.name != "posix", reason="Requires POSIX process groups")
def test_cli_exec_explicit_bash(tmp_path):
    worker = Worker(tmp_path, cli_enabled=True)
    result = worker.dispatch("run_cli", {
        "argv": ["bash", "-c", "pwd; printf 'shell-ok\\n'"]
    })
    assert _done(worker, result["job_id"])["exit_code"] == 0
    output = _output(worker, result["job_id"])
    assert str(tmp_path) in output
    assert "shell-ok" in output
    worker.long_task_manager.shutdown()


@pytest.mark.skipif(os.name != "posix", reason="Requires POSIX process groups")
def test_cli_does_not_inherit_agent_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("KRW_AGENT_TOKEN", "secret-must-not-leak")
    worker = Worker(tmp_path, cli_enabled=True)
    result = worker.dispatch("run_cli", {"argv": [sys.executable, "-c",
        'import os; print(os.environ.get("KRW_AGENT_TOKEN", "missing"))']})
    assert _done(worker, result["job_id"])["exit_code"] == 0
    assert _output(worker, result["job_id"]).strip() == "missing"
    assert "secret-must-not-leak" not in _output(worker, result["job_id"])
    worker.long_task_manager.shutdown()


def test_cli_missing_executable_fails_job_without_stopping_agent(tmp_path):
    worker = Worker(tmp_path, cli_enabled=True)
    result = worker.dispatch("run_cli", {"argv": ["krw-binary-does-not-exist-20261106"]})
    assert _done(worker, result["job_id"])["state"] == "failed"
    worker.long_task_manager.shutdown()


def test_cli_disallows_broad_workspace_root(tmp_path):
    broad = Path("/content") if Path("/content").is_dir() else Path.home()
    with pytest.raises(ValueError, match="too broad"):
        Worker(broad, cli_enabled=True)


def test_cli_agent_optin_from_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("KRW_ALLOW_CLI", raising=False)
    assert WorkspaceRouter.from_env(tmp_path).workers["default"].cli_enabled is False
    monkeypatch.setenv("KRW_ALLOW_CLI", "1")
    assert WorkspaceRouter.from_env(tmp_path).workers["default"].cli_enabled is True


@pytest.mark.asyncio
async def test_gateway_cli_permission_gate():
    tokens = {"test-agent": "a" * 48}
    denied = State(tokens, "b" * 48)
    with pytest.raises(HTTPException) as e:
        await denied.submit(Dispatch(device_id="test-agent", operation="run_cli",
                                     arguments={"argv": ["python3", "--version"]}))
    assert e.value.status_code == 403
    allowed = State(tokens, "b" * 48, cli_enabled=True)
    with pytest.raises(HTTPException) as e:
        await allowed.submit(Dispatch(device_id="test-agent", operation="run_cli",
                                      arguments={"argv": ["python3", "--version"]}))
    assert e.value.status_code == 503


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
def test_cli_asynchronous_and_300_second_timeout(tmp_path):
    worker = Worker(tmp_path, cli_enabled=True)
    start = time.monotonic()
    job = worker.run_cli({"argv": [sys.executable, "-c",
                          "import time; time.sleep(0.30); print('complete')"]})
    assert time.monotonic() - start < 0.25
    assert job["timeout_seconds"] == 300
    assert _done(worker, job["job_id"])["state"] == "succeeded"
    assert "complete" in _output(worker, job["job_id"])
    worker.long_task_manager.shutdown()


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
def test_cli_timeout_and_cancellation(tmp_path, monkeypatch):
    import agent.long_tasks as module
    monkeypatch.setattr(module, "MAX_CLI_SECONDS", 1)
    worker = Worker(tmp_path, cli_enabled=True)
    job = worker.run_cli({"argv": [sys.executable, "-c", "import time; time.sleep(10)"]})
    assert job["timeout_seconds"] == 1
    final = _done(worker, job["job_id"], timeout=4)
    assert final["state"] == "timed_out" and final["timed_out"]
    another = worker.run_cli({"argv": [sys.executable, "-c", "import time; time.sleep(9)"]})
    worker.cancel_cli_job({"job_id": another["job_id"]})
    assert _done(worker, another["job_id"])["state"] == "cancelled"
    worker.long_task_manager.shutdown()


def test_cli_job_workspace_isolation(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    router = WorkspaceRouter(left, {"right": str(right)}, cli_enabled=True)
    job = router.dispatch("run_cli", {"argv": ["bash", "-c", "echo isolation"]})
    for op in ("get_cli_job", "read_cli_log", "cancel_cli_job"):
        with pytest.raises(WorkspaceError, match="not found in workspace"):
            router.dispatch(op, {"workspace_id": "right", "job_id": job["job_id"]})
    router.shutdown()


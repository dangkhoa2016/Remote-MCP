"""controlled tasks: explicit task IDs, separate opt-in, safe targets, bounded execution."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

from agent.task_runner import MAX_CAPTURE_BYTES, TaskError, TaskRunner
from agent.worker import Worker, WorkspaceError
from agent.workspace_routes import WorkspaceRouter
from gateway.relay import Dispatch, State


def test_list_tasks_does_not_enable_execution(tmp_path: Path):
    worker = Worker(tmp_path)
    listing = worker.dispatch("list_tasks", {})
    assert len(listing["tasks"]) == 5
    assert all(not task["enabled"] for task in listing["tasks"])
    assert listing["arbitrary_shell"] is False
    with pytest.raises(WorkspaceError, match="disabled"):
        worker.dispatch("run_task", {"task_id": "git_status"})
    with pytest.raises(WorkspaceError, match="disabled"):
        Worker(tmp_path, tasks_enabled=True).dispatch(
            "run_task", {"task_id": "pytest"})


def test_strict_task_ids_do_not_accept_commands_or_user_flags(tmp_path: Path):
    worker = Worker(tmp_path, tasks_enabled=True, test_tasks_enabled=True)
    for task_id in ("bash", "sh", "git_push", "bundle exec rspec", "pytest -k x",
                    "python -c 'print(1)'", "", None, ["pytest"]):
        with pytest.raises(WorkspaceError, match="not allowed"):
            worker.run_task({"task_id": task_id})
    for target in ("--pdb", "-k", "../outside.py", "tests/../../outside.py",
                   "/etc/passwd", "tests/test_sample.py\n--pdb",
                   "tests/test_sample.py:1", "Gemfile", "tests/.env"):
        with pytest.raises(WorkspaceError):
            worker.run_task({"task_id": "pytest", "target": target})
    with pytest.raises(WorkspaceError, match="Targets are only"):
        worker.run_task({"task_id": "git_status", "target": "tests/test_any.py"})


def test_target_validation_rejects_symlink_and_bad_extension(tmp_path: Path):
    worker = Worker(tmp_path, tasks_enabled=True, test_tasks_enabled=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "note.txt").write_text("data")
    (tmp_path / "tests" / "link_test.py").symlink_to(tmp_path / "tests" / "note.txt")
    for name in ("tests/note.txt", "tests/link_test.py", "tests/nonexistent.py"):
        with pytest.raises(WorkspaceError):
            worker.run_task({"task_id": "pytest", "target": name})


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
def test_pytest_task_runs_with_bounded_output_and_no_agent_secrets(tmp_path: Path, monkeypatch):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_safe.py").write_text(
        "import os\n"
        "def test_environment():\n"
        "    assert 'KRW_AGENT_TOKEN' not in os.environ\n"
        "    assert 'KRW_GIT_PUSH_TOKEN' not in os.environ\n"
        "    assert os.environ['RAILS_ENV'] == 'test'\n"
        "    assert 2 + 2 == 4\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KRW_AGENT_TOKEN", "SECRET_MUST_NOT_LEAK")
    monkeypatch.setenv("KRW_GIT_PUSH_TOKEN", "ANOTHER_SECRET")
    worker = Worker(tmp_path, tasks_enabled=True, test_tasks_enabled=True)
    result = worker.run_task({"task_id": "pytest", "target": "tests/test_safe.py"})
    assert result["exit_code"] == 0, result
    assert not result["timed_out"]
    assert "1 passed" in result["stdout"]
    assert "SECRET_MUST_NOT_LEAK" not in str(result)
    assert len(result["stdout"].encode("utf-8")) <= MAX_CAPTURE_BYTES


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
def test_task_runner_enforces_timeout(tmp_path: Path, monkeypatch):
    import agent.task_runner as module

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_wait.py").write_text(
        "import time\n"
        "def test_wait():\n"
        "    time.sleep(10)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "TASK_TIMEOUT_SECONDS", 2)
    runner = TaskRunner(tmp_path, lambda path: tmp_path / path,
                        tasks_enabled=True, test_tasks_enabled=True)
    result = runner.run_task("pytest", "tests/test_wait.py")
    assert result["timed_out"] is True
    assert result["elapsed_ms"] < 5_000


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
def test_output_truncation_is_bounded(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_noisy.py").write_text(
        "def test_noisy():\n"
        "    print('A' * 90000)\n"
        "    assert False\n",
        encoding="utf-8",
    )
    worker = Worker(tmp_path, tasks_enabled=True, test_tasks_enabled=True)
    result = worker.run_task({"task_id": "pytest", "target": "tests/test_noisy.py"})
    assert result["exit_code"] != 0
    assert result["output_truncated"] is True
    assert len(result["stdout"].encode("utf-8")) <= MAX_CAPTURE_BYTES
    assert len(result["stderr"].encode("utf-8")) <= MAX_CAPTURE_BYTES


def test_pytest_uses_agent_interpreter_module(tmp_path: Path, monkeypatch):
    runner = TaskRunner(tmp_path, lambda path: tmp_path / path,
                        tasks_enabled=True, test_tasks_enabled=True)
    # A console-script may be installed but cannot reliably import local packages.
    monkeypatch.setattr("agent.task_runner.shutil.which",
                        lambda name, path=None: "/usr/local/bin/pytest")
    monkeypatch.setattr("agent.task_runner.importlib.util.find_spec",
                        lambda name: object() if name == "pytest_asyncio" else None)
    assert runner._argv("pytest", "tests/test_local.py") == [
        sys.executable, "-m", "pytest", "-q", "--disable-warnings",
        "-p", "pytest_asyncio.plugin", "--", "tests/test_local.py",
    ]
    monkeypatch.setattr("agent.task_runner.importlib.util.find_spec",
                        lambda name: None)
    assert runner._argv("pytest", "tests/test_local.py") == [
        sys.executable, "-m", "pytest", "-q", "--disable-warnings",
        "--", "tests/test_local.py",
    ]


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
def test_pytest_imports_project_local_package(tmp_path: Path):
    package = tmp_path / "local_package"
    package.mkdir()
    (package / "__init__.py").write_text("ANSWER = 42\n")
    suite = tmp_path / "tests"
    suite.mkdir()
    (suite / "test_local.py").write_text(
        "from local_package import ANSWER\n"
        "def test_import():\n"
        "    assert ANSWER == 42\n"
    )
    worker = Worker(tmp_path, tasks_enabled=True, test_tasks_enabled=True)
    result = worker.run_task({"task_id": "pytest", "target": "tests/test_local.py"})
    assert result["exit_code"] == 0, result
    assert "1 passed" in result["stdout"]


@pytest.mark.skipif(os.name != "posix", reason="POSIX process groups required")
def test_controlled_pytest_explicitly_loads_only_asyncio_plugin(tmp_path: Path):
    # Installed via requirements-dev.txt for CI. Autoload is disabled by
    # _execute, so the async test passes only if -p loads the one safe plugin.
    pytest.importorskip("pytest_asyncio")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_async.py").write_text(
        "import asyncio\n"
        "import pytest\n"
        "@pytest.mark.asyncio\n"
        "async def test_async():\n"
        "    await asyncio.sleep(0)\n"
        "    assert True\n"
    )
    worker = Worker(tmp_path, tasks_enabled=True, test_tasks_enabled=True)
    result = worker.run_task({"task_id": "pytest", "target": "tests/test_async.py"})
    assert result["exit_code"] == 0, result
    assert "1 passed" in result["stdout"]


def test_fixed_rspec_and_rails_argv_no_shell(tmp_path: Path, monkeypatch):
    worker = Worker(tmp_path, tasks_enabled=True, test_tasks_enabled=True)
    (tmp_path / "spec").mkdir()
    (tmp_path / "test").mkdir()
    (tmp_path / "spec" / "user_spec.rb").write_text("describe('ok') {}")
    (tmp_path / "test" / "user_test.rb").write_text("class UserTest; end")
    monkeypatch.setattr(TaskRunner, "_binary", staticmethod(lambda x: "/usr/bin/" + x))
    runner = worker._task_runner()
    assert runner._argv("rspec", "spec/user_spec.rb") == [
        "/usr/bin/bundle", "exec", "rspec", "--format", "progress", "spec/user_spec.rb"
    ]
    assert runner._argv("rails_test", "test/user_test.rb") == [
        "/usr/bin/bundle", "exec", "rails", "test", "test/user_test.rb"
    ]
    assert runner._target("rspec", "spec/user_spec.rb") == "spec/user_spec.rb"
    assert runner._target("rails_test", "test/user_test.rb") == "test/user_test.rb"
    with pytest.raises(TaskError):
        runner._target("rspec", "test/user_test.rb")
    with pytest.raises(TaskError):
        runner._target("rails_test", "spec/user_spec.rb")


def test_git_tasks_use_existing_sanitized_reader(tmp_path: Path):
    if shutil.which("git") is None:
        pytest.skip("Git not available")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    worker = Worker(tmp_path, tasks_enabled=True)
    result = worker.run_task({"task_id": "git_status"})
    assert result["exit_code"] == 0
    assert result["result"]["read_only"] is True
    assert result["task_id"] == "git_status"
    with pytest.raises(WorkspaceError, match="Target"):
        worker.run_task({"task_id": "git_log", "target": "tests/example.py"})


def test_named_workspace_tasks_are_isolated(tmp_path: Path):
    a = tmp_path / "one"
    b = tmp_path / "two"
    a.mkdir()
    b.mkdir()
    router = WorkspaceRouter(a, {"two": str(b)}, tasks_enabled=True)
    assert router.dispatch("list_tasks", {"workspace_id": "two"})["tasks"][0]["enabled"]
    with pytest.raises(WorkspaceError, match="not configured"):
        router.dispatch("run_task", {"workspace_id": "other", "task_id": "git_status"})
    with pytest.raises(WorkspaceError, match="disabled"):
        router.dispatch("run_task", {"workspace_id": "two", "task_id": "pytest"})


@pytest.mark.asyncio
async def test_relay_permission_gates():
    s = State({"local-dev": "a" * 48}, "b" * 48)
    with pytest.raises(HTTPException) as err:
        await s.submit(Dispatch(device_id="local-dev", operation="run_task",
                                arguments={"task_id": "git_status"}))
    assert err.value.status_code == 403
    s = State({"local-dev": "a" * 48}, "b" * 48, tasks_enabled=True)
    with pytest.raises(HTTPException) as err:
        await s.submit(Dispatch(device_id="local-dev", operation="run_task",
                                arguments={"task_id": "pytest"}))
    assert err.value.status_code == 403
    # Authorization has passed, but this test deliberately has no online Agent.
    with pytest.raises(HTTPException) as err:
        await s.submit(Dispatch(device_id="local-dev", operation="run_task",
                                arguments={"task_id": "git_status"}))
    assert err.value.status_code == 503

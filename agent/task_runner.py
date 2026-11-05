"""Phase 7: finite, opt-in task runner. Never accepts a command string.

Test tasks execute repository code and therefore MUST be used only with trusted
projects in an isolated Agent environment. This module is NOT an OS sandbox.
"""
from __future__ import annotations

import os
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from agent.git_readonly import GitReadOnly, GitReadOnlyError

TASK_TIMEOUT_SECONDS = 15
MAX_CAPTURE_BYTES = 16_384
MAX_TOTAL_OUTPUT_BYTES = 1_048_576
TEST_TASKS = frozenset({"pytest", "rspec", "rails_test"})
GIT_TASKS = frozenset({"git_status", "git_log"})
TASKS = TEST_TASKS | GIT_TASKS
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"


class TaskError(Exception):
    pass


class TaskRunner:
    def __init__(self, root: Path, validate_path: Callable[[str], Path],
                 *, tasks_enabled: bool = False, test_tasks_enabled: bool = False):
        self.root = root
        self.validate_path = validate_path
        self.tasks_enabled = tasks_enabled
        self.test_tasks_enabled = test_tasks_enabled

    def list_tasks(self) -> dict[str, Any]:
        return {
            "tasks": [
                {"task_id": key, "requires_test_opt_in": key in TEST_TASKS,
                 "enabled": self.tasks_enabled and (
                     key not in TEST_TASKS or self.test_tasks_enabled)}
                for key in ("git_status", "git_log", "pytest", "rspec", "rails_test")
            ],
            "arbitrary_shell": False, "timeout_seconds": TASK_TIMEOUT_SECONDS,
        }

    def _target(self, task_id: str, target: str) -> str:
        if type(target) is not str or len(target) > 300 or "\x00" in target:
            raise TaskError("Invalid test target")
        if not target:
            return ""
        if task_id not in TEST_TASKS:
            raise TaskError("Targets are only permitted for test tasks")
        if target.startswith("-") or any(ord(c) < 32 or ord(c) == 127 for c in target):
            raise TaskError("Invalid test target")
        pieces = Path(target).parts
        if not pieces or pieces[0] not in ("test", "tests", "spec"):
            raise TaskError("Test target must be under test/, tests/ or spec/")
        expected_suffix = ".py" if task_id == "pytest" else ".rb"
        if Path(target).suffix.lower() != expected_suffix:
            raise TaskError("Test target has wrong file extension")
        if task_id == "rspec" and not target.startswith("spec/"):
            raise TaskError("RSpec targets must be under spec/")
        if task_id == "rails_test" and not target.startswith("test/"):
            raise TaskError("Rails test targets must be under test/")
        try:
            validated = self.validate_path(target)
        except Exception as exc:
            raise TaskError("Test target is restricted") from exc
        if not validated.is_file() or validated.is_symlink():
            raise TaskError("Test target must be a regular file")
        if not os.access(validated, os.R_OK):
            raise TaskError("Test target unavailable")
        # Recheck no-follow descriptor access when opening the requested path.
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise TaskError("Safe target validation unavailable")
        parent_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for piece in pieces[:-1]:
                next_fd = os.open(piece, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                  dir_fd=parent_fd)
                os.close(parent_fd)
                parent_fd = next_fd
            file_fd = os.open(pieces[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
            try:
                if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                    raise TaskError("Test target must be a regular file")
            finally:
                os.close(file_fd)
        except OSError as exc:
            raise TaskError("Test target unavailable") from exc
        finally:
            os.close(parent_fd)
        return Path(*pieces).as_posix()

    @staticmethod
    def _binary(name: str) -> str:
        executable = shutil.which(name, path=SAFE_PATH)
        if not executable:
            raise TaskError(f"Required executable unavailable: {name}")
        return executable

    def _argv(self, task_id: str, target: str) -> list[str]:
        if task_id == "pytest":
            executable = shutil.which("pytest", path=SAFE_PATH)
            args = [executable] if executable else [sys.executable, "-m", "pytest"]
            args += ["-q", "--disable-warnings"]
            if target:
                args += ["--", target]
            return args
        if task_id == "rspec":
            args = [self._binary("bundle"), "exec", "rspec", "--format", "progress"]
            return args + ([target] if target else [])
        if task_id == "rails_test":
            args = [self._binary("bundle"), "exec", "rails", "test"]
            return args + ([target] if target else [])
        raise TaskError("Task ID is not allowed")

    @staticmethod
    def _limits() -> None:
        # Process-level limits are defense in depth, not an isolation boundary.
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_CPU, (TASK_TIMEOUT_SECONDS, TASK_TIMEOUT_SECONDS))
        resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))

    @staticmethod
    def _terminate_group(process: subprocess.Popen) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _execute(self, argv: list[str], task_id: str, target: str) -> dict[str, Any]:
        if os.name != "posix":
            raise TaskError("Task runner requires POSIX process groups")
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="krw-task-") as temporary:
            env = {
                "PATH": SAFE_PATH,
                "HOME": temporary,
                "TMPDIR": temporary,
                "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTEST_ADDOPTS": "",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_NO_LAZY_FETCH": "1",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_PAGER": "cat",
                "BUNDLE_USER_HOME": temporary,
                "RAILS_ENV": "test",
                "RACK_ENV": "test",
            }
            try:
                process = subprocess.Popen(
                    argv, cwd=self.root, env=env, stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    close_fds=True, start_new_session=True, preexec_fn=self._limits,
                )
            except OSError as exc:
                raise TaskError("Task executable could not start") from exc

            streams = {"stdout": bytearray(), "stderr": bytearray()}
            total_seen = 0
            truncated = False
            timed_out = False
            output_limit_hit = False
            selector = selectors.DefaultSelector()
            try:
                assert process.stdout is not None and process.stderr is not None
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                while selector.get_map():
                    remaining = TASK_TIMEOUT_SECONDS - (time.monotonic() - started)
                    if remaining <= 0:
                        timed_out = True
                        self._terminate_group(process)
                        break
                    for key, _ in selector.select(timeout=min(remaining, 0.2)):
                        data = os.read(key.fileobj.fileno(), 4096)
                        if not data:
                            selector.unregister(key.fileobj)
                            continue
                        total_seen += len(data)
                        captured = streams[key.data]
                        available = max(0, MAX_CAPTURE_BYTES - len(captured))
                        if available < len(data):
                            truncated = True
                        captured.extend(data[:available])
                        if total_seen > MAX_TOTAL_OUTPUT_BYTES:
                            output_limit_hit = True
                            truncated = True
                            self._terminate_group(process)
                            break
                    if output_limit_hit:
                        break
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self._terminate_group(process)
                    process.wait(timeout=1)
            finally:
                selector.close()
                for pipe in (process.stdout, process.stderr):
                    if pipe is not None:
                        pipe.close()
                if process.poll() is None:
                    self._terminate_group(process)
                    process.wait(timeout=1)

        return {
            "task_id": task_id, "target": target,
            "exit_code": process.returncode,
            "timed_out": timed_out, "output_limit_hit": output_limit_hit,
            "output_truncated": truncated,
            "stdout": streams["stdout"].decode("utf-8", "replace"),
            "stderr": streams["stderr"].decode("utf-8", "replace"),
            "elapsed_ms": int((time.monotonic() - started) * 1000),
        }

    def run_task(self, task_id: str, target: str = "") -> dict[str, Any]:
        if type(task_id) is not str or task_id not in TASKS:
            raise TaskError("Task ID is not allowed")
        if not self.tasks_enabled:
            raise TaskError("Task execution disabled on Agent")
        if task_id in TEST_TASKS and not self.test_tasks_enabled:
            raise TaskError("Test task execution disabled on Agent")
        target = self._target(task_id, target)
        if task_id in GIT_TASKS:
            try:
                reader = GitReadOnly(self.root, self.validate_path)
                data = reader.status() if task_id == "git_status" else reader.log(10)
            except GitReadOnlyError as exc:
                raise TaskError(str(exc)) from exc
            return {"task_id": task_id, "target": "", "exit_code": 0,
                    "timed_out": False, "output_truncated": False,
                    "result": data}
        return self._execute(self._argv(task_id, target), task_id, target)

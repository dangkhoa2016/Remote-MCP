"""background test jobs: bounded, Agent-local background test task lifecycle.

This is NOT a sandbox. Only pre-authorized, trusted test source may run.
The Agent's HTTPS polling thread never waits for a long task to finish.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import secrets
import selectors
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any

from agent.task_runner import SAFE_PATH, TEST_TASKS, TaskError, TaskRunner

MAX_TASK_SECONDS = 180
MAX_CLI_SECONDS = 300
MAX_LOG_BYTES = 262_144
MAX_LOG_CHUNK = 8192
MAX_QUEUED = 2
MAX_RETAINED = 12
RETAIN_SECONDS = 3600
_ID = re.compile(r"[0-9a-f]{32}\Z")


@dataclass
class _Job:
    job_id: str
    workspace_id: str
    task_id: str
    target: str
    root: Path
    argv: list[str]
    runner: TaskRunner = field(repr=False)
    state: str = "queued"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    exit_code: int | None = None
    cancel_requested: bool = False
    timed_out: bool = False
    output_limit_hit: bool = False
    log: bytearray = field(default_factory=bytearray)
    process: subprocess.Popen | None = field(default=None, repr=False)
    timeout_seconds: int = MAX_TASK_SECONDS


class LongTaskManager:
    """One running task per Agent, two queued, retained results held in RAM."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, _Job] = {}
        self._queue: deque[str] = deque()
        self._active = False
        self._closed = False
        self._thread: threading.Thread | None = None

    def _owned(self, job_id: str, workspace_id: str) -> _Job:
        if type(job_id) is not str or not _ID.fullmatch(job_id):
            raise TaskError("Invalid task job ID")
        job = self._jobs.get(job_id)
        if job is None or job.workspace_id != workspace_id:
            raise TaskError("Task job not found in workspace")
        return job

    @staticmethod
    def _summary(job: _Job) -> dict[str, Any]:
        return {
            "job_id": job.job_id, "workspace_id": job.workspace_id,
            "task_id": job.task_id, "target": job.target,
            "state": job.state,
            "created_at": job.created_at, "started_at": job.started_at,
            "finished_at": job.finished_at, "exit_code": job.exit_code,
            "cancel_requested": job.cancel_requested,
            "timed_out": job.timed_out, "output_limit_hit": job.output_limit_hit,
            "log_bytes": len(job.log), "timeout_seconds": job.timeout_seconds,
        }

    def _prune(self) -> None:
        now = time.time()
        terminal = {"succeeded", "failed", "cancelled", "timed_out", "output_limit"}
        for identifier, job in list(self._jobs.items()):
            if job.state in terminal and job.finished_at is not None and (
                now - job.finished_at >= RETAIN_SECONDS
            ):
                del self._jobs[identifier]
        # Evict only completed records, oldest first. Never interrupt active work.
        if len(self._jobs) >= MAX_RETAINED:
            completed = sorted(
                (job for job in self._jobs.values()
                 if job.state in terminal and job.finished_at is not None),
                key=lambda job: (job.finished_at, job.created_at, job.job_id),
            )
            for job in completed:
                if len(self._jobs) < MAX_RETAINED:
                    break
                del self._jobs[job.job_id]
        if len(self._jobs) >= MAX_RETAINED:
            raise TaskError("Task history is full of active jobs")

    def start(self, runner: TaskRunner, *, workspace_id: str,
              task_id: str, target: str = "") -> dict[str, Any]:
        if type(task_id) is not str or task_id not in TEST_TASKS:
            raise TaskError("Long-running tasks only allow pytest, rspec and rails_test")
        if not runner.tasks_enabled or not runner.test_tasks_enabled:
            raise TaskError("Long-running test tasks disabled on Agent")
        target = runner._target(task_id, target)
        argv = runner._argv(task_id, target)
        if os.name != "posix":
            raise TaskError("Long task runner requires POSIX process groups")
        with self._lock:
            if self._closed:
                raise TaskError("Task manager is shutting down")
            if len(self._queue) >= MAX_QUEUED:
                raise TaskError("Task queue is full")
            self._prune()
            job_id = secrets.token_hex(16)
            job = _Job(job_id, workspace_id, task_id, target, runner.root, argv, runner,
                       timeout_seconds=MAX_TASK_SECONDS)
            self._jobs[job_id] = job
            self._queue.append(job_id)
            if not self._active:
                self._active = True
                self._thread = threading.Thread(
                    target=self._drive, daemon=True, name="krw-long-tasks"
                )
                self._thread.start()
            return self._summary(job)

    def start_cli(self, runner: TaskRunner, *, workspace_id: str,
                  argv: list[str]) -> dict[str, Any]:
        """Queue a five-minute CLI without blocking the Agent polling loop."""
        if os.name != "posix":
            raise TaskError("CLI jobs require POSIX process groups")
        argv = TaskRunner.validate_cli_argv(argv)
        with self._lock:
            if self._closed:
                raise TaskError("Task manager is shutting down")
            if len(self._queue) >= MAX_QUEUED:
                raise TaskError("Task queue is full")
            self._prune()
            job_id = secrets.token_hex(16)
            job = _Job(job_id, workspace_id, "cli", "", runner.root, argv,
                       runner, timeout_seconds=MAX_CLI_SECONDS)
            self._jobs[job_id] = job
            self._queue.append(job_id)
            if not self._active:
                self._active = True
                self._thread = threading.Thread(
                    target=self._drive, daemon=True, name="krw-long-tasks")
                self._thread.start()
            return self._summary(job)

    def _cli_owned(self, job_id: str, workspace_id: str) -> _Job:
        job = self._owned(job_id, workspace_id)
        if job.task_id != "cli":
            raise TaskError("CLI job not found in workspace")
        return job

    def cli_status(self, job_id: str, *, workspace_id: str) -> dict[str, Any]:
        with self._lock:
            return self._summary(self._cli_owned(job_id, workspace_id))

    def cli_log(self, job_id: str, *, workspace_id: str,
                offset: int = 0, max_bytes: int = 4096) -> dict[str, Any]:
        with self._lock:
            self._cli_owned(job_id, workspace_id)
            return self.log(job_id, workspace_id=workspace_id,
                            offset=offset, max_bytes=max_bytes)

    def cli_cancel(self, job_id: str, *, workspace_id: str) -> dict[str, Any]:
        with self._lock:
            self._cli_owned(job_id, workspace_id)
            return self.cancel(job_id, workspace_id=workspace_id)

    def status(self, job_id: str, *, workspace_id: str) -> dict[str, Any]:
        with self._lock:
            return self._summary(self._owned(job_id, workspace_id))

    def log(self, job_id: str, *, workspace_id: str,
            offset: int = 0, max_bytes: int = 4096) -> dict[str, Any]:
        if type(offset) is not int or offset < 0 or type(max_bytes) is not int or not 1 <= max_bytes <= MAX_LOG_CHUNK:
            raise TaskError("Invalid task log pagination")
        with self._lock:
            job = self._owned(job_id, workspace_id)
            if offset > len(job.log):
                raise TaskError("Log offset is beyond available output")
            end = min(len(job.log), offset + max_bytes)
            raw = bytes(job.log[offset:end])
            return {"job_id": job_id, "offset": offset, "next_offset": end,
                    "total_bytes": len(job.log), "state": job.state,
                    "output_limit_hit": job.output_limit_hit,
                    "text": raw.decode("utf-8", "replace")}

    @staticmethod
    def _kill(process: subprocess.Popen) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def cancel(self, job_id: str, *, workspace_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._owned(job_id, workspace_id)
            if job.state == "queued":
                job.cancel_requested = True
                job.state = "cancelled"
                job.finished_at = time.time()
                try:
                    self._queue.remove(job_id)
                except ValueError:
                    pass
            elif job.state == "running":
                job.cancel_requested = True
                if job.process is not None:
                    self._kill(job.process)
            return self._summary(job)

    @staticmethod
    def _environment(temporary: str) -> dict[str, str]:
        # Deliberately does not inherit Agent tokens, Git credentials, or proxies.
        return {
            "PATH": SAFE_PATH, "HOME": temporary, "TMPDIR": temporary,
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTEST_ADDOPTS": "",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull, "GIT_TERMINAL_PROMPT": "0",
            "GIT_NO_LAZY_FETCH": "1", "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat", "BUNDLE_USER_HOME": temporary,
            "RAILS_ENV": "test", "RACK_ENV": "test",
        }

    def _execute(self, job: _Job) -> None:
        started = time.monotonic()
        process: subprocess.Popen | None = None
        timed_out = False
        output_limit = False
        result_code: int | None = None
        try:
            # A queued target may be removed or replaced before it starts.
            # Recheck the file, symlinks and allowed path immediately pre-launch.
            if job.task_id != "cli":
                job.runner._target(job.task_id, job.target)
            with tempfile.TemporaryDirectory(prefix="krw-long-task-") as temporary:
                # start_new_session allows cancellation of the entire process group.
                process = subprocess.Popen(
                    job.argv, cwd=job.root, env=self._environment(temporary),
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, close_fds=True, start_new_session=True,
                )
                with self._lock:
                    job.process = process
                    if job.cancel_requested or self._closed:
                        self._kill(process)
                selector = selectors.DefaultSelector()
                try:
                    assert process.stdout is not None
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while selector.get_map():
                        if time.monotonic() - started >= job.timeout_seconds:
                            timed_out = True
                            self._kill(process)
                            break
                        with self._lock:
                            cancelled = job.cancel_requested or self._closed
                        if cancelled:
                            self._kill(process)
                            break
                        for key, _ in selector.select(timeout=0.1):
                            raw = os.read(key.fileobj.fileno(), 4096)
                            if not raw:
                                selector.unregister(key.fileobj)
                                continue
                            with self._lock:
                                available = MAX_LOG_BYTES - len(job.log)
                                job.log.extend(raw[:max(0, available)])
                                if len(raw) > available:
                                    output_limit = True
                            if output_limit:
                                self._kill(process)
                                break
                        if output_limit:
                            break
                    try:
                        result_code = process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self._kill(process)
                        result_code = process.wait(timeout=2)
                finally:
                    selector.close()
                    if process.stdout is not None:
                        process.stdout.close()
        except (OSError, ValueError, subprocess.SubprocessError, TaskError):
            # Do not leak command errors containing environment or filesystem data.
            result_code = -1
        finally:
            if process is not None and process.poll() is None:
                self._kill(process)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            with self._lock:
                job.process = None
                job.exit_code = result_code
                job.timed_out = timed_out
                job.output_limit_hit = output_limit
                job.finished_at = time.time()
                if job.cancel_requested or self._closed:
                    job.state = "cancelled"
                elif timed_out:
                    job.state = "timed_out"
                elif output_limit:
                    job.state = "output_limit"
                elif result_code == 0:
                    job.state = "succeeded"
                else:
                    job.state = "failed"

    def _drive(self) -> None:
        while True:
            with self._lock:
                while self._queue:
                    identifier = self._queue.popleft()
                    job = self._jobs[identifier]
                    if job.state == "queued":
                        job.state = "running"
                        job.started_at = time.time()
                        break
                else:
                    self._active = False
                    self._thread = None
                    return
            try:
                self._execute(job)
            except Exception:
                # Fail this job instead of leaving the queue permanently active.
                with self._lock:
                    job.process = None
                    job.exit_code = -1
                    job.finished_at = time.time()
                    job.state = "cancelled" if job.cancel_requested else "failed"

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            for job in self._jobs.values():
                if job.state in ("queued", "running"):
                    job.cancel_requested = True
                    if job.state == "queued":
                        job.state = "cancelled"
                        job.finished_at = time.time()
                    if job.process is not None:
                        self._kill(job.process)
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)

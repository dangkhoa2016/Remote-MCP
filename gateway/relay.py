"""Agent relay. No MCP tool access is exposed on this HTTP listener."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
from pathlib import Path
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from gateway.device_enrollment import DeviceEnrollmentStore
from gateway.version import APP_VERSION
from pydantic import BaseModel, Field

LOG = logging.getLogger("krw.gateway")
DEVICE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
VALID_OPERATIONS = {"get_device_info", "list_directory", "read_file", "git_status", "git_diff", "git_log", "file_sha256", "write_file", "check_syntax", "execute_command", "run_cli", "get_cli_job", "read_cli_log", "cancel_cli_job", "edit_file", "search_files", "create_directory", "move_file", "delete_file", "list_workspaces", "move_directory", "delete_directory", "git_stage", "git_commit", "git_branch_create", "git_branch_switch", "git_push", "git_fetch", "git_pull", "git_branches", "git_unstage", "list_tasks", "run_task", "start_long_task", "get_long_task", "read_long_task_log", "cancel_long_task"}


def _separate_mount_for(database: str | None) -> bool | None:
    """Best-effort mount check, not proof of persistent-disk durability.

    A Docker image can precreate /data/krw; writable alone is insufficient.
    """
    if not database:
        return None
    try:
        directory = Path(database).resolve().parent
        points = []
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            left = line.split(" - ", 1)[0].split()
            if len(left) >= 5:
                raw = left[4]
                point = Path(raw.replace(r"\040", " ").replace(r"\011", "\t"))
                if directory == point or directory.is_relative_to(point):
                    points.append(point)
        return any(point != Path("/") for point in points)
    except (OSError, ValueError):
        return None


class Registration(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)
    hostname: str = Field(min_length=1, max_length=128)
    platform: str = Field(min_length=1, max_length=128)
    workspace: str = Field(min_length=1, max_length=128)


class ApproveDevice(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)
    pairing_code: str = Field(min_length=12, max_length=24)


class RevokeDevice(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)


class Poll(BaseModel):
    device_id: str


class Result(BaseModel):
    device_id: str
    job_id: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class Dispatch(BaseModel):
    device_id: str
    operation: Literal["get_device_info", "list_directory", "read_file", "git_status", "git_diff", "git_log", "file_sha256", "write_file", "check_syntax", "execute_command", "run_cli", "get_cli_job", "read_cli_log", "cancel_cli_job", "edit_file", "search_files", "create_directory", "move_file", "delete_file", "list_workspaces", "move_directory", "delete_directory", "git_stage", "git_commit", "git_branch_create", "git_branch_switch", "git_push", "git_fetch", "git_pull", "git_branches", "git_unstage", "list_tasks", "run_task", "start_long_task", "get_long_task", "read_long_task_log", "cancel_long_task"]
    arguments: dict[str, Any] = Field(default_factory=dict)


@dataclass
class Device:
    info: Registration
    last_seen: float
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(maxsize=32))


class State:
    def __init__(self, device_tokens: dict[str, str], control_token: str, commands_enabled: bool = False,
                 writes_enabled: bool = False, checks_enabled: bool = False,
                 git_writes_enabled: bool = False, git_push_enabled: bool = False,
                 tasks_enabled: bool = False, test_tasks_enabled: bool = False,
                 long_tasks_enabled: bool = False, cli_enabled: bool = False,
                 enrollment_enabled: bool = False, enrollment_db_path: str | None = None):
        if any(not DEVICE_ID_RE.fullmatch(k) or not isinstance(v, str) or len(v) < 32
               for k, v in device_tokens.items()):
            raise ValueError("Device IDs and legacy tokens must be valid")
        if not device_tokens and not enrollment_db_path:
            raise ValueError("Configure legacy tokens or enrollment database")
        if len(control_token) < 32:
            raise ValueError("KRW_CONTROL_TOKEN must contain at least 32 characters")
        self.device_tokens = device_tokens
        self.enrollment_enabled = enrollment_enabled
        self.enrollments = (DeviceEnrollmentStore(enrollment_db_path, set(device_tokens))
                            if enrollment_db_path else None)
        if enrollment_enabled and self.enrollments is None:
            raise ValueError("Enrollment enabled without device database")
        self.started_at = time.monotonic()
        self.enrollment_separate_mount_detected = _separate_mount_for(enrollment_db_path)
        self.control_token = control_token
        self.commands_enabled = commands_enabled
        self.writes_enabled = writes_enabled
        self.checks_enabled = checks_enabled
        self.git_writes_enabled = git_writes_enabled
        self.git_push_enabled = git_push_enabled
        self.tasks_enabled = tasks_enabled
        self.test_tasks_enabled = test_tasks_enabled
        self.long_tasks_enabled = long_tasks_enabled
        self.cli_enabled = cli_enabled
        self.devices: dict[str, Device] = {}
        self.pending: dict[str, tuple[str, asyncio.Future]] = {}
        self.lock = asyncio.Lock()

    def check_agent(self, device_id: str, authorization: str | None) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Unauthorized device")
        bearer = authorization[7:]
        if device_id in self.device_tokens:
            allowed = hmac.compare_digest(self.device_tokens[device_id], bearer)
        else:
            allowed = bool(self.enrollments and self.enrollments.authenticated(device_id, bearer))
        if not allowed:
            raise HTTPException(401, "Unauthorized device")

    def check_control(self, token: str | None) -> None:
        if not token or not hmac.compare_digest(self.control_token, token):
            raise HTTPException(401, "Unauthorized controller")

    async def register(self, info: Registration) -> None:
        async with self.lock:
            old = self.devices.get(info.device_id)
            # Keep the queue if the same agent re-registers after network failure.
            queue = old.queue if old else asyncio.Queue(maxsize=32)
            self.devices[info.device_id] = Device(info, time.monotonic(), queue)
            LOG.info("agent_registered device=%s", info.device_id)

    def touch(self, device_id: str) -> Device:
        device = self.devices.get(device_id)
        if not device:
            raise HTTPException(409, "Agent must register first")
        device.last_seen = time.monotonic()
        return device

    def online(self, device: Device) -> bool:
        return (time.monotonic() - device.last_seen) < 40

    def list_devices(self) -> list[dict[str, Any]]:
        return [
            {"device_id": key, "hostname": dev.info.hostname, "platform": dev.info.platform,
             "workspace": dev.info.workspace, "online": self.online(dev)}
            for key, dev in sorted(self.devices.items())
        ]

    async def next_job(self, device_id: str) -> dict[str, Any] | None:
        device = self.touch(device_id)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                job = await asyncio.wait_for(device.queue.get(), timeout=max(0.01, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                break
            if job["job_id"] in self.pending:
                return job
        return None

    async def submit(self, req: Dispatch) -> dict[str, Any]:
        if req.operation not in VALID_OPERATIONS:
            raise HTTPException(400, "Operation not supported")
        if req.operation in {"run_cli", "get_cli_job", "read_cli_log", "cancel_cli_job"} and not self.cli_enabled:
            raise HTTPException(403, "CLI execution disabled on gateway")
        if req.operation == "execute_command" and not self.commands_enabled:
            raise HTTPException(403, "Command execution disabled on gateway")
        if req.operation in {"write_file", "edit_file", "create_directory", "move_file", "delete_file", "move_directory", "delete_directory"} and not self.writes_enabled:
            raise HTTPException(403, "Workspace writes disabled on gateway")
        if req.operation in {"git_stage", "git_commit", "git_branch_create", "git_branch_switch", "git_push", "git_fetch", "git_pull", "git_unstage"} and not self.git_writes_enabled:
            raise HTTPException(403, "Git writes disabled on gateway")
        if req.operation == "git_push" and not self.git_push_enabled:
            raise HTTPException(403, "Git push disabled on gateway")
        if req.operation == "run_task":
            if not self.tasks_enabled:
                raise HTTPException(403, "Controlled tasks disabled on gateway")
            if req.arguments.get("task_id") in {"pytest", "rspec", "rails_test"} and not self.test_tasks_enabled:
                raise HTTPException(403, "Test tasks disabled on gateway")
        if req.operation in {"start_long_task", "get_long_task", "read_long_task_log", "cancel_long_task"}:
            if not (self.tasks_enabled and self.test_tasks_enabled and self.long_tasks_enabled):
                raise HTTPException(403, "Long-running test tasks disabled on gateway")
            if req.operation == "start_long_task" and req.arguments.get("task_id") not in {"pytest", "rspec", "rails_test"}:
                raise HTTPException(403, "Long tasks only allow approved test runners")
        if req.operation == "check_syntax" and not self.checks_enabled:
            raise HTTPException(403, "Static checks disabled on gateway")
        async with self.lock:
            device = self.devices.get(req.device_id)
            if not device or not self.online(device):
                raise HTTPException(503, "Device is offline")
            if device.queue.full():
                raise HTTPException(429, "Device queue full")
            job_id = uuid.uuid4().hex
            future = asyncio.get_running_loop().create_future()
            self.pending[job_id] = (req.device_id, future)
            device.queue.put_nowait({"job_id": job_id, "operation": req.operation, "arguments": req.arguments})
        try:
            result = await asyncio.wait_for(future, timeout=22)
            LOG.info("job_completed device=%s operation=%s ok=%s", req.device_id, req.operation, result["ok"])
            return result
        except asyncio.TimeoutError:
            LOG.warning("job_timeout device=%s operation=%s", req.device_id, req.operation)
            raise HTTPException(504, "Agent response timeout")
        finally:
            self.pending.pop(job_id, None)

    def resolve_result(self, result: Result) -> None:
        pending = self.pending.get(result.job_id)
        if not pending or pending[0] != result.device_id:
            raise HTTPException(409, "Unknown or expired job")
        future = pending[1]
        if future.done():
            raise HTTPException(409, "Job already completed")
        encoded = json.dumps(result.data, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > 786_432:
            raise HTTPException(413, "Result too large")
        future.set_result({"ok": result.ok, "data": result.data, "error": (result.error or "")[:512]})


def state_from_env() -> State:
    raw = os.getenv("KRW_DEVICE_TOKENS_JSON", "{}") or "{}"
    try:
        tokens = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError("Set KRW_DEVICE_TOKENS_JSON to a JSON object") from e
    if not isinstance(tokens, dict):
        raise ValueError("KRW_DEVICE_TOKENS_JSON must be a JSON object")
    return State(tokens, os.getenv("KRW_CONTROL_TOKEN", ""),
                 enrollment_enabled=os.getenv("KRW_DEVICE_ENROLLMENT_ENABLED", "0") == "1",
                 enrollment_db_path=os.getenv("KRW_DEVICE_DB_PATH") or None,
                 commands_enabled=os.getenv("KRW_COMMANDS_ENABLED", "0") == "1",
                 writes_enabled=os.getenv("KRW_WRITE_ENABLED", "0") == "1",
                 checks_enabled=os.getenv("KRW_STATIC_CHECKS_ENABLED", "0") == "1",
                 git_writes_enabled=os.getenv("KRW_GIT_WRITES_ENABLED", "0") == "1",
                 git_push_enabled=os.getenv("KRW_GIT_PUSH_ENABLED", "0") == "1",
                 tasks_enabled=os.getenv("KRW_TASKS_ENABLED", "0") == "1",
                 test_tasks_enabled=os.getenv("KRW_TEST_TASKS_ENABLED", "0") == "1",
                 long_tasks_enabled=os.getenv("KRW_LONG_TASKS_ENABLED", "0") == "1",
                 cli_enabled=os.getenv("KRW_CLI_ENABLED", "0") == "1")


def create_app(state: State) -> FastAPI:
    app = FastAPI(title="Remote-MCP Agent Relay", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.relay = state

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "krw-agent-relay", "version": APP_VERSION}

    @app.post("/v1/agent/enroll")
    async def enroll(body: Registration, authorization: str | None = Header(default=None)):
        if not state.enrollment_enabled or state.enrollments is None:
            raise HTTPException(403, "Device enrollment disabled")
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Unauthorized enrollment request")
        return state.enrollments.enroll(body, authorization[7:])

    @app.post("/v1/agent/register")
    async def register(body: Registration, authorization: str | None = Header(default=None)):
        state.check_agent(body.device_id, authorization)
        await state.register(body)
        return {"status": "registered", "poll_seconds": 8}

    @app.post("/v1/agent/poll")
    async def poll(body: Poll, authorization: str | None = Header(default=None)):
        state.check_agent(body.device_id, authorization)
        return {"job": await state.next_job(body.device_id)}

    @app.post("/v1/agent/result")
    async def result(body: Result, authorization: str | None = Header(default=None)):
        state.check_agent(body.device_id, authorization)
        state.touch(body.device_id)
        state.resolve_result(body)
        return {"status": "accepted"}

    @app.get("/v1/control/capabilities")
    async def capabilities(x_control_token: str | None = Header(default=None)):
        state.check_control(x_control_token)
        return {"mode": "device-relay", "device_agent_connected": any(state.online(d) for d in state.devices.values()),
                "available_tools": ["health_check", "list_capabilities", "list_devices", "get_device_info", "list_directory", "read_file", "git_status", "git_diff", "git_log", "file_sha256", "write_file", "check_syntax", "execute_command", "run_cli", "run_shell", "get_cli_job", "read_cli_log", "cancel_cli_job", "edit_file", "search_files", "create_directory", "move_file", "delete_file", "list_workspaces", "move_directory", "delete_directory", "git_stage", "git_commit", "git_branch_create", "git_branch_switch", "git_push", "git_fetch", "git_pull", "git_branches", "git_unstage", "list_tasks", "run_task", "start_long_task", "get_long_task", "read_long_task_log", "cancel_long_task", "list_pending_devices", "approve_device",
                                     "list_registered_devices", "revoke_device"],
                "filesystem_access": True, "command_execution": state.commands_enabled,
                "cli_execution": state.cli_enabled,
                "cli_timeout_seconds": 300,
                "relay_uptime_seconds": int(time.monotonic() - state.started_at),
                "enrollment_separate_mount_detected": state.enrollment_separate_mount_detected,
                "filesystem_writes": state.writes_enabled, "static_checks": state.checks_enabled,
                "git_writes": state.git_writes_enabled, "git_push": state.git_push_enabled,
                "controlled_tasks": state.tasks_enabled,
                "test_tasks": state.tasks_enabled and state.test_tasks_enabled,
                "long_tasks": state.tasks_enabled and state.test_tasks_enabled and state.long_tasks_enabled,
                "device_enrollment": state.enrollment_enabled}

    @app.get("/v1/control/enrollments/pending")
    async def pending_devices(x_control_token: str | None = Header(default=None)):
        state.check_control(x_control_token)
        return {"devices": state.enrollments.pending() if state.enrollments else []}

    @app.post("/v1/control/enrollments/approve")
    async def approve_device(body: ApproveDevice, x_control_token: str | None = Header(default=None)):
        state.check_control(x_control_token)
        if not state.enrollment_enabled or not state.enrollments:
            raise HTTPException(403, "Device enrollment disabled")
        return state.enrollments.approve(body.device_id, body.pairing_code)

    @app.get("/v1/control/enrollments/registered")
    async def registered_devices(x_control_token: str | None = Header(default=None)):
        state.check_control(x_control_token)
        return {"devices": state.enrollments.registered() if state.enrollments else []}

    @app.post("/v1/control/enrollments/revoke")
    async def revoke_device(body: RevokeDevice, x_control_token: str | None = Header(default=None)):
        state.check_control(x_control_token)
        if not state.enrollments:
            raise HTTPException(403, "Device enrollment disabled")
        result = state.enrollments.revoke(body.device_id)
        async with state.lock:
            state.devices.pop(body.device_id, None)
        return result

    @app.get("/v1/control/devices")
    async def list_devices(x_control_token: str | None = Header(default=None)):
        state.check_control(x_control_token)
        return {"devices": state.list_devices()}

    @app.post("/v1/control/dispatch")
    async def dispatch(body: Dispatch, x_control_token: str | None = Header(default=None)):
        state.check_control(x_control_token)
        return await state.submit(body)

    return app


# Uvicorn discovers this app. The explicit factory allows tests without environment secrets.
# All routes that access device information require a token.
class _LazyApp:
    """Construct only after KRW_* environment variables have been loaded."""
    def __init__(self):
        self._app = None

    async def __call__(self, scope, receive, send):
        if self._app is None:
            self._app = create_app(state_from_env())
        await self._app(scope, receive, send)


app = _LazyApp()

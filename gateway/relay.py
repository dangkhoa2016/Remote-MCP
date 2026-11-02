"""Agent relay. No MCP tool access is exposed on this HTTP listener."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

LOG = logging.getLogger("krw.gateway")
DEVICE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
VALID_OPERATIONS = {"get_device_info", "list_directory", "read_file", "execute_command"}


class Registration(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)
    hostname: str = Field(min_length=1, max_length=128)
    platform: str = Field(min_length=1, max_length=128)
    workspace: str = Field(min_length=1, max_length=128)


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
    operation: Literal["get_device_info", "list_directory", "read_file", "execute_command"]
    arguments: dict[str, Any] = Field(default_factory=dict)


@dataclass
class Device:
    info: Registration
    last_seen: float
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(maxsize=32))


class State:
    def __init__(self, device_tokens: dict[str, str], control_token: str, commands_enabled: bool = False):
        if not device_tokens or any(not DEVICE_ID_RE.fullmatch(k) or len(v) < 32 for k, v in device_tokens.items()):
            raise ValueError("Configure one or more device IDs and >=32-character tokens")
        if len(control_token) < 32:
            raise ValueError("KRW_CONTROL_TOKEN must contain at least 32 characters")
        self.device_tokens = device_tokens
        self.control_token = control_token
        self.commands_enabled = commands_enabled
        self.devices: dict[str, Device] = {}
        self.pending: dict[str, tuple[str, asyncio.Future]] = {}
        self.lock = asyncio.Lock()

    def check_agent(self, device_id: str, authorization: str | None) -> None:
        token = self.device_tokens.get(device_id)
        if not token or not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Unauthorized device")
        if not hmac.compare_digest(token, authorization[7:]):
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
        if req.operation == "execute_command" and not self.commands_enabled:
            raise HTTPException(403, "Command execution disabled on gateway")
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
        if len(encoded.encode("utf-8")) > 48_000:
            raise HTTPException(413, "Result too large")
        future.set_result({"ok": result.ok, "data": result.data, "error": (result.error or "")[:512]})


def state_from_env() -> State:
    raw = os.getenv("KRW_DEVICE_TOKENS_JSON", "")
    try:
        tokens = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError("Set KRW_DEVICE_TOKENS_JSON to a JSON object") from e
    if not isinstance(tokens, dict):
        raise ValueError("KRW_DEVICE_TOKENS_JSON must be a JSON object")
    return State(tokens, os.getenv("KRW_CONTROL_TOKEN", ""), os.getenv("KRW_COMMANDS_ENABLED", "0") == "1")


def create_app(state: State) -> FastAPI:
    app = FastAPI(title="Khoa Remote Workspace Agent Relay", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.relay = state

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "krw-agent-relay", "version": "0.2.0"}

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
                "available_tools": ["health_check", "list_capabilities", "list_devices", "get_device_info", "list_directory", "read_file", "execute_command"],
                "filesystem_access": True, "command_execution": state.commands_enabled}

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

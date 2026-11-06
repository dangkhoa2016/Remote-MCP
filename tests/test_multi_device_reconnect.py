"""multi-device reconnect: multi-device routing and reconnect regressions, simulated in-process."""
import asyncio
import importlib
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from gateway.relay import Dispatch, Registration, Result, State, create_app
from gateway.device_enrollment import pairing_code

CONTROL = "c" * 48
TOKENS = {"colab-a": "a" * 48, "colab-b": "b" * 48}


def info(device):
    return {"device_id": device, "hostname": device,
            "platform": "Linux", "workspace": "project-" + device}


@pytest.mark.asyncio
async def test_simultaneous_routing_and_cross_device_result_denial():
    state = State(TOKENS, CONTROL)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(state)), base_url="http://test"
    ) as http:
        for device, token in TOKENS.items():
            r = await http.post("/v1/agent/register", json=info(device),
                                headers={"Authorization": "Bearer " + token})
            assert r.status_code == 200
        ctrl = {"X-Control-Token": CONTROL}
        callers = {
            dev: asyncio.create_task(http.post(
                "/v1/control/dispatch", headers=ctrl,
                json={"device_id": dev, "operation": "get_device_info", "arguments": {}}
            )) for dev in TOKENS
        }
        await asyncio.sleep(0.04)
        jobs = {}
        for dev in ("colab-b", "colab-a"):
            response = await http.post("/v1/agent/poll", json={"device_id": dev},
                headers={"Authorization": "Bearer " + TOKENS[dev]})
            assert response.status_code == 200
            jobs[dev] = response.json()["job"]
            assert jobs[dev]["operation"] == "get_device_info"
        assert jobs["colab-a"]["job_id"] != jobs["colab-b"]["job_id"]
        wrong = await http.post("/v1/agent/result",
            headers={"Authorization": "Bearer " + TOKENS["colab-a"]},
            json={"device_id": "colab-b", "job_id": jobs["colab-b"]["job_id"],
                  "ok": True, "data": {"origin": "spoof"}})
        assert wrong.status_code == 401
        with pytest.raises(HTTPException) as error:
            state.resolve_result(Result(device_id="colab-a",
                job_id=jobs["colab-b"]["job_id"], ok=True, data={}))
        assert error.value.status_code == 409
        for dev in ("colab-b", "colab-a"):
            ack = await http.post("/v1/agent/result",
                headers={"Authorization": "Bearer " + TOKENS[dev]},
                json={"device_id": dev, "job_id": jobs[dev]["job_id"],
                      "ok": True, "data": {"origin": dev}})
            assert ack.status_code == 200
        for dev, request in callers.items():
            result = await request
            assert result.status_code == 200
            assert result.json()["data"] == {"origin": dev}


@pytest.mark.asyncio
async def test_reregister_keeps_pending_job_on_same_gateway():
    state = State({"colab-a": TOKENS["colab-a"]}, CONTROL)
    registration = Registration(**info("colab-a"))
    await state.register(registration)
    caller = asyncio.create_task(state.submit(
        Dispatch(device_id="colab-a", operation="get_device_info")))
    await asyncio.sleep(0.03)
    await state.register(registration)
    job = await state.next_job("colab-a")
    assert job["operation"] == "get_device_info"
    state.resolve_result(Result(device_id="colab-a", job_id=job["job_id"],
                                ok=True, data={"recovered": True}))
    assert (await caller)["data"]["recovered"] is True


@pytest.mark.asyncio
async def test_gateway_restart_keeps_pairing_but_requires_registration(tmp_path):
    database = str(tmp_path / "devices.sqlite")
    ctrl = {"X-Control-Token": CONTROL}
    first = State({}, CONTROL, enrollment_enabled=True, enrollment_db_path=database)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(first)), base_url="http://test"
    ) as http:
        for dev, token in TOKENS.items():
            auth = {"Authorization": "Bearer " + token}
            enrollment = await http.post("/v1/agent/enroll", json=info(dev), headers=auth)
            assert enrollment.status_code == 200
            approved = await http.post("/v1/control/enrollments/approve", headers=ctrl,
                json={"device_id": dev,
                      "pairing_code": pairing_code(token, enrollment.json()["challenge"])})
            assert approved.status_code == 200
            assert (await http.post("/v1/agent/register",
                headers=auth, json=info(dev))).status_code == 200
    second = State({}, CONTROL, enrollment_enabled=True, enrollment_db_path=database)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(second)), base_url="http://test"
    ) as http:
        assert (await http.get("/v1/control/devices", headers=ctrl)).json()["devices"] == []
        for dev, token in TOKENS.items():
            auth = {"Authorization": "Bearer " + token}
            assert (await http.post("/v1/agent/poll", headers=auth,
                                    json={"device_id": dev})).status_code == 409
            assert (await http.post("/v1/agent/register", headers=auth,
                                    json=info(dev))).status_code == 200
        devices = (await http.get("/v1/control/devices", headers=ctrl)).json()["devices"]
        assert {item["device_id"] for item in devices} == set(TOKENS)
        assert all(item["online"] for item in devices)


def test_agent_reregisters_after_transient_connection_failure(tmp_path, monkeypatch):
    module = importlib.import_module("agent.agent")
    seen = []
    class Router:
        workers = {"default": SimpleNamespace(root=tmp_path)}
        stopped = False
        def shutdown(self):
            self.stopped = True
    router = Router()
    monkeypatch.setattr(module.WorkspaceRouter, "from_env", lambda root: router)
    monkeypatch.setattr(module.signal, "signal", lambda *args: None)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: seen.append(("sleep", seconds)))
    monkeypatch.setattr(module, "STOP", False)
    monkeypatch.setenv("KRW_DEVICE_ID", "colab-a")
    monkeypatch.setenv("KRW_AGENT_TOKEN", TOKENS["colab-a"])
    monkeypatch.setenv("KRW_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("KRW_RELAY_URL", "https://relay.example.test")
    monkeypatch.setenv("KRW_AUTO_ENROLL", "0")
    class FakeClient:
        polls = 0
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def post(self, path, *, json):
            seen.append(("post", path))
            request = httpx.Request("POST", "https://relay.example.test" + path)
            if path == "/v1/agent/poll":
                self.polls += 1
                if self.polls == 1:
                    raise httpx.ConnectError("simulated outage", request=request)
                module.STOP = True
                return httpx.Response(200, json={"job": None}, request=request)
            return httpx.Response(200, json={"status": "registered"}, request=request)
    monkeypatch.setattr(module.httpx, "Client", FakeClient)
    module.run()
    assert seen.count(("post", "/v1/agent/register")) == 2
    assert seen.count(("post", "/v1/agent/poll")) == 2
    assert ("sleep", 2) in seen
    assert router.stopped is True

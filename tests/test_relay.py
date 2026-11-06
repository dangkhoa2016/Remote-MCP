import asyncio
import json

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from gateway.relay import Dispatch, Registration, State, create_app

TOKEN = "a" * 48
CONTROL = "b" * 48


@pytest.mark.asyncio
async def test_auth_register_poll_and_dispatch():
    state = State({"local-dev": TOKEN}, CONTROL)
    app = create_app(state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        assert (await http.get("/health")).status_code == 200
        registration = {"device_id": "local-dev", "hostname": "test-host", "platform": "Linux", "workspace": "safe"}
        assert (await http.post("/v1/agent/register", json=registration)).status_code == 401
        assert (await http.post("/v1/agent/register", headers={"Authorization": f"Bearer {TOKEN}"}, json=registration)).status_code == 200
        assert (await http.get("/v1/control/devices")).status_code == 401
        headers = {"X-Control-Token": CONTROL}
        assert (await http.get("/v1/control/devices", headers=headers)).json()["devices"][0]["online"]
        caller = asyncio.create_task(http.post("/v1/control/dispatch", headers=headers, json={"device_id": "local-dev", "operation": "get_device_info", "arguments": {}}))
        await asyncio.sleep(0.04)
        polled = await http.post("/v1/agent/poll", headers={"Authorization": f"Bearer {TOKEN}"}, json={"device_id": "local-dev"})
        job = polled.json()["job"]
        assert job["operation"] == "get_device_info"
        ack = await http.post("/v1/agent/result", headers={"Authorization": f"Bearer {TOKEN}"}, json={"device_id": "local-dev", "job_id": job["job_id"], "ok": True, "data": {"python": "3.x"}})
        assert ack.status_code == 200
        response = await caller
        assert response.status_code == 200
        assert response.json()["data"]["python"] == "3.x"


@pytest.mark.asyncio
async def test_command_off_on_relay():
    state = State({"local-dev": TOKEN}, CONTROL, commands_enabled=False)
    await state.register(Registration(device_id="local-dev", hostname="h", platform="Linux", workspace="tmp"))
    with pytest.raises(HTTPException) as exc:
        await state.submit(Dispatch(device_id="local-dev", operation="execute_command", arguments={"command_id": "python_version"}))
    assert exc.value.status_code == 403


def test_reject_weak_secrets():
    with pytest.raises(ValueError):
        State({"dev": "short"}, CONTROL)
    with pytest.raises(ValueError):
        State({"dev": TOKEN}, "short")

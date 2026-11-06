"""device enrollment regression: per-device pairing, auth, revocation and restart."""
import sqlite3
import secrets
import time

import pytest
from httpx import ASGITransport, AsyncClient

from agent.agent import verification_code
from gateway.device_enrollment import pairing_code
from gateway.relay import State, create_app

CONTROL = "c" * 48
LEGACY = "l" * 48


def info(device_id):
    return {"device_id":device_id, "hostname":"test-host", "platform":"Linux",
            "workspace":"project"}


@pytest.mark.asyncio
async def test_pairing_approval_restart_revocation(tmp_path):
    path = str(tmp_path / "devices.sqlite")
    token = secrets.token_urlsafe(32)
    bearer = {"Authorization":"Bearer "+token}
    state = State({"legacy":LEGACY}, CONTROL, enrollment_enabled=True, enrollment_db_path=path)
    ctrl = {"X-Control-Token":CONTROL}
    async with AsyncClient(transport=ASGITransport(app=create_app(state)), base_url="http://test") as http:
        assert (await http.post("/v1/agent/register", json=info("node-1"), headers=bearer)).status_code == 401
        assert (await http.post("/v1/agent/enroll", json=info("node-1"))).status_code == 401
        response = await http.post("/v1/agent/enroll", json=info("node-1"), headers=bearer)
        assert response.status_code == 200
        code = pairing_code(token, response.json()["challenge"])
        assert code == verification_code(token, response.json()["challenge"])
        assert len(code) == 12
        assert "code" not in str(response.json()).lower()
        assert (await http.get("/v1/control/enrollments/pending")).status_code == 401
        pending = await http.get("/v1/control/enrollments/pending",headers=ctrl)
        assert pending.status_code == 200
        assert pending.json()["devices"][0]["device_id"] == "node-1"
        assert code not in pending.text and token not in pending.text
        assert (await http.post("/v1/control/enrollments/approve",json={
            "device_id":"node-1","pairing_code":code})).status_code==401
        bad = await http.post("/v1/control/enrollments/approve",headers=ctrl,json={
            "device_id":"node-1","pairing_code":"AAAAAAAAAAAA"})
        assert bad.status_code == 403
        approved = await http.post("/v1/control/enrollments/approve",headers=ctrl,json={
            "device_id":"node-1","pairing_code":code})
        assert approved.status_code==200,approved.text
        assert (await http.post("/v1/agent/register",json=info("node-1"),headers=bearer)).status_code==200
        assert (await http.post("/v1/agent/register",json=info("legacy"),headers={
            "Authorization":"Bearer "+LEGACY})).status_code==200
        registered = await http.get("/v1/control/enrollments/registered",headers=ctrl)
        assert registered.status_code==200
        assert token not in registered.text
        assert (await http.post("/v1/agent/enroll",json=info("node-1"),headers=bearer)).status_code==409
    state2 = State({"legacy":LEGACY}, CONTROL, enrollment_enabled=True, enrollment_db_path=path)
    async with AsyncClient(transport=ASGITransport(app=create_app(state2)),base_url="http://test") as http:
        assert (await http.post("/v1/agent/register",json=info("node-1"),headers=bearer)).status_code==200
        assert (await http.post("/v1/control/enrollments/revoke",headers=ctrl,json={
            "device_id":"node-1"})).status_code==200
        assert (await http.post("/v1/agent/poll",json={"device_id":"node-1"},headers=bearer)).status_code==401
        assert (await http.post("/v1/agent/enroll",json=info("node-1"),headers=bearer)).status_code==409
        assert (await http.post("/v1/agent/register",json=info("legacy"),headers={
            "Authorization":"Bearer "+LEGACY})).status_code==200
        assert (await http.post("/v1/control/enrollments/revoke",headers=ctrl,json={
            "device_id":"legacy"})).status_code==404
    binary = open(path,"rb").read()
    assert token.encode() not in binary and code.encode() not in binary


@pytest.mark.asyncio
async def test_two_devices_token_isolation(tmp_path):
    state = State({}, CONTROL, enrollment_enabled=True,
                  enrollment_db_path=str(tmp_path/"multi.sqlite"))
    ctrl={"X-Control-Token":CONTROL}
    tokens={name:secrets.token_urlsafe(32) for name in ("host-a","host-b")}
    async with AsyncClient(transport=ASGITransport(app=create_app(state)),base_url="http://test") as http:
        for name,secret in tokens.items():
            bearer={"Authorization":"Bearer "+secret}
            request=await http.post("/v1/agent/enroll",json=info(name),headers=bearer)
            assert request.status_code==200
            assert (await http.post("/v1/control/enrollments/approve",headers=ctrl,json={
                "device_id":name,"pairing_code":pairing_code(secret,request.json()["challenge"])})).status_code==200
            assert (await http.post("/v1/agent/register",json=info(name),headers=bearer)).status_code==200
        assert (await http.post("/v1/agent/register",json=info("host-b"),headers={
            "Authorization":"Bearer "+tokens["host-a"]})).status_code==401
        assert (await http.post("/v1/control/enrollments/revoke",headers=ctrl,json={
            "device_id":"host-a"})).status_code==200
        assert (await http.post("/v1/agent/register",json=info("host-a"),headers={
            "Authorization":"Bearer "+tokens["host-a"]})).status_code==401
        assert (await http.post("/v1/agent/register",json=info("host-b"),headers={
            "Authorization":"Bearer "+tokens["host-b"]})).status_code==200


@pytest.mark.asyncio
async def test_failed_attempts_collision_expiry(tmp_path):
    path=str(tmp_path/"devices.sqlite")
    state=State({},CONTROL,enrollment_enabled=True,enrollment_db_path=path)
    secret=secrets.token_urlsafe(32)
    other=secrets.token_urlsafe(32)
    ctrl={"X-Control-Token":CONTROL}
    async with AsyncClient(transport=ASGITransport(app=create_app(state)),base_url="http://test") as http:
        req=await http.post("/v1/agent/enroll",json=info("node"),headers={"Authorization":"Bearer "+secret})
        assert req.status_code==200
        assert (await http.post("/v1/agent/enroll",json=info("node"),headers={
            "Authorization":"Bearer "+other})).status_code==409
        again=await http.post("/v1/agent/enroll",json=info("node"),headers={
            "Authorization":"Bearer "+secret})
        assert again.json()["challenge"]==req.json()["challenge"]
        for _ in range(5):
            assert (await http.post("/v1/control/enrollments/approve",headers=ctrl,json={
                "device_id":"node","pairing_code":"AAAAAAAAAAAA"})).status_code==403
        correct=pairing_code(secret,req.json()["challenge"])
        assert (await http.post("/v1/control/enrollments/approve",headers=ctrl,json={
            "device_id":"node","pairing_code":correct})).status_code==429
        with sqlite3.connect(path) as db:
            db.execute("UPDATE krw_pending_enrollments SET expires_at=?",(int(time.time())-1,))
        assert (await http.post("/v1/control/enrollments/approve",headers=ctrl,json={
            "device_id":"node","pairing_code":correct})).status_code==404


@pytest.mark.asyncio
async def test_feature_opt_in(tmp_path):
    state=State({"legacy":LEGACY},CONTROL,enrollment_db_path=str(tmp_path/"db.sqlite"))
    async with AsyncClient(transport=ASGITransport(app=create_app(state)),base_url="http://test") as http:
        assert (await http.post("/v1/agent/enroll",json=info("new"),headers={
            "Authorization":"Bearer "+secrets.token_urlsafe(32)})).status_code==403
        assert (await http.post("/v1/agent/register",json=info("legacy"),headers={
            "Authorization":"Bearer "+LEGACY})).status_code==200


def test_bootstrap_and_tool_permissions():
    from pathlib import Path
    base=Path(__file__).resolve().parents[1]
    script=(base/"gateway/setup.sh").read_text()
    server=(base/"gateway/server.py").read_text()
    assert "secrets.token_urlsafe(32)" in script
    assert "uuid.uuid4()" in script
    assert "KRW_AUTO_ENROLL" in script
    assert "Device token (input hidden)" not in script
    assert "KRW_DEVICE_ADMIN_TOOLS_ENABLED" in server

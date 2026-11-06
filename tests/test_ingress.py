import pytest
from httpx import ASGITransport, AsyncClient
from gateway.agent_ingress import app


@pytest.mark.asyncio
async def test_control_route_not_exposed():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/v1/control/devices")).status_code == 404
        assert (await client.post("/v1/agent/dispatch", json={})).status_code == 404
        assert (await client.get("/health")).json()["status"] == "ok"

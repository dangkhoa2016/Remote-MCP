"""Optional public ingress. Only allowlisted Agent endpoints are exposed, never /control."""
from __future__ import annotations

import os
from fastapi import FastAPI, HTTPException, Request, Response
import httpx

PRIVATE_RELAY = "http://127.0.0.1:8766"
ALLOWED = {"register", "poll", "result", "enroll"}
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "krw-agent-ingress"}


@app.post("/v1/agent/{operation}")
async def agent_endpoint(operation: str, request: Request):
    if operation not in ALLOWED:
        raise HTTPException(404, "Not found")
    raw = await request.body()
    if len(raw) > 48_000:
        raise HTTPException(413, "Payload too large")
    authorization = request.headers.get("authorization", "")
    async with httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False) as client:
        try:
            upstream = await client.post(PRIVATE_RELAY + "/v1/agent/" + operation, content=raw,
                                         headers={"Authorization": authorization, "Content-Type": "application/json"})
        except httpx.HTTPError:
            raise HTTPException(502, "Private relay unreachable")
    return Response(content=upstream.content, status_code=upstream.status_code, media_type="application/json")

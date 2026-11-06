"""Deployment-only regression: public ingress exposure is restricted."""
from pathlib import Path
import ast
import pytest


def test_gateway_routes_agent_only():
    from gateway.agent_ingress import ALLOWED, PRIVATE_RELAY
    assert ALLOWED == {'register','poll','result','enroll'}
    assert PRIVATE_RELAY == 'http://127.0.0.1:8766'


def test_frontend_mounts_ingress():
    source = (Path(__file__).resolve().parents[1] / 'gateway/local_auth.py').read_text()
    assert 'app.include_router(_krw_agent_ingress.router)' in source
    ast.parse(source)


def test_no_commands_unlocked():
    source = (Path(__file__).resolve().parents[1] / 'gateway/server.py').read_text()
    assert 'Remote command execution disabled in local-login build' in source


def test_ingress_app_routes():
    from gateway.agent_ingress import app
    allowed = {(m, route.path) for route in app.routes for m in getattr(route, 'methods', [])}
    assert ('POST','/v1/agent/{operation}') in allowed
    assert not any('/v1/control' in path for _,path in allowed)


def test_auth_frontend_exposes_only_agent_allowlisted_routes(monkeypatch, tmp_path):
    from test_local_auth import load_auth
    from fastapi.testclient import TestClient
    auth, _, _ = load_auth(monkeypatch, tmp_path)
    with TestClient(auth.app, base_url='https://tunnel.test') as client:
        assert client.get('/health').status_code == 200
        assert client.get('/v1/control/devices').status_code == 404
        assert client.post('/v1/agent/dispatch', json={}).status_code == 404

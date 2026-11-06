"""Public agent distribution must never contain credentials or arbitrary files."""
from __future__ import annotations

import gzip
import hashlib
import io
import tarfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from gateway import bootstrap


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    for name in bootstrap.AGENT_FILES:
        f = tmp_path / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text('safe content', encoding='utf-8')
    (tmp_path / 'agent' / '.env.dev').write_text('FORBIDDEN_SECRET', encoding='utf-8')
    (tmp_path / 'gateway' / 'setup.sh').write_text(
        '#!/bin/bash\nBASE_URL=__KRW_PUBLIC_ORIGIN__\nSHA=__KRW_AGENT_BUNDLE_SHA256__\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(bootstrap, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setenv('KRW_MCP_PUBLIC_URL', 'https://gateway.example.com/mcp')
    bootstrap.build_agent_bundle.cache_clear()
    app = FastAPI()
    app.include_router(bootstrap.router)
    yield TestClient(app)
    bootstrap.build_agent_bundle.cache_clear()


def test_script_uses_pinned_origin_and_archive_hash(app_client):
    script = app_client.get('/setup.sh')
    archive = app_client.get('/agent-bundle.tar.gz')
    assert script.status_code == archive.status_code == 200
    assert 'https://gateway.example.com' in script.text
    assert '__KRW_' not in script.text
    assert hashlib.sha256(archive.content).hexdigest() in script.text
    assert script.headers['cache-control'] == 'no-store'
    assert archive.headers['cache-control'] == 'no-store'


def test_only_explicit_agent_files_are_downloadable(app_client):
    data = app_client.get('/agent-bundle.tar.gz').content
    assert b'FORBIDDEN_SECRET' not in gzip.decompress(data)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tf:
        assert sorted(tf.getnames()) == sorted([
            'agent/__init__.py', 'agent/agent.py', 'agent/worker.py',
            'agent/git_readonly.py', 'agent/git_write.py', 'agent/workspace_routes.py',
            'agent/task_runner.py', 'agent/long_tasks.py',
                'agent/workspace_edit.py', 'agent/workspace_manage.py',
                'agent-requirements.txt',
        ])
        assert all(m.isfile() and m.uid == 0 and m.gid == 0 for m in tf.getmembers())


def test_archive_is_reproducible(app_client):
    first = app_client.get('/agent-bundle.tar.gz').content
    bootstrap.build_agent_bundle.cache_clear()
    second = app_client.get('/agent-bundle.tar.gz').content
    assert first == second


def test_invalid_public_origin_is_rejected(app_client, monkeypatch):
    for value in ('http://insecure.example/mcp', 'https://evil@example.com/mcp',
                  'https://evil.example\nInjected: x/mcp'):
        monkeypatch.setenv('KRW_MCP_PUBLIC_URL', value)
        assert app_client.get('/setup.sh').status_code == 503


def test_archive_does_not_allow_arbitrary_path_requests(app_client):
    assert app_client.get('/agent-bundle.tar.gz?file=.env.dev').status_code == 200
    assert app_client.get('/agent/.env.dev').status_code == 404

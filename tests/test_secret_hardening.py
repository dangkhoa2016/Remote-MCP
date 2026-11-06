"""Regression tests against the actual patched Agent Worker and secret relocation."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import pytest

from agent.worker import Worker, WorkspaceError


@pytest.mark.parametrize('name', [
    'env.dev.txt', 'env.production', 'config.env',
    'credentials.backup', 'service-token.json', 'secret.txt',
    'api-key.json', 'passwords.txt', 'private_key.pem',
    'ENV.Dev.Txt', 'token.txt',
])
def test_secret_file_cannot_be_listed_or_read(tmp_path, name):
    (tmp_path / name).write_text('DO-NOT-DISCLOSE', encoding='utf-8')
    worker = Worker(tmp_path)
    assert name not in [e['name'] for e in worker.list_directory({'path': '.'})['entries']]
    with pytest.raises(WorkspaceError, match='restricted'):
        worker.read_file({'path': name})


def test_nested_secret_name_hidden_and_denied(tmp_path):
    docs = tmp_path / 'docs'
    docs.mkdir()
    (docs / 'env.dev.txt').write_text('SENTINEL', encoding='utf-8')
    (docs / 'readme.txt').write_text('safe', encoding='utf-8')
    worker = Worker(tmp_path)
    assert [e['name'] for e in worker.list_directory({'path': 'docs'})['entries']] == ['readme.txt']
    with pytest.raises(WorkspaceError):
        worker.read_file({'path': 'docs/env.dev.txt'})
    assert worker.read_file({'path': 'docs/readme.txt'})['content'] == 'safe'


def test_denied_directory_component(tmp_path):
    (tmp_path / 'secrets').mkdir()
    (tmp_path / 'secrets' / 'example.txt').write_text('NO')
    worker = Worker(tmp_path)
    assert 'secrets' not in [e['name'] for e in worker.list_directory({'path': '.'})['entries']]
    with pytest.raises(WorkspaceError):
        worker.read_file({'path': 'secrets/example.txt'})


def test_utf8_boundary_does_not_reject_valid_text(tmp_path):
    source = 'A' * 1023 + 'ộ' + 'X'
    (tmp_path / 'README.md').write_text(source, encoding='utf-8')
    worker = Worker(tmp_path)
    partial = worker.read_file({'path': 'README.md', 'max_bytes': 1024})
    assert partial['truncated'] is True
    assert partial['content'] == 'A' * 1023
    assert partial['bytes_read'] == 1023
    complete = worker.read_file({'path': 'README.md', 'max_bytes': 3000})
    assert complete['content'] == source
    assert complete['truncated'] is False


def test_binary_text_still_rejected(tmp_path):
    (tmp_path / 'binary.txt').write_bytes(b'abc\xffdef')
    with pytest.raises(WorkspaceError, match='not UTF-8'):
        Worker(tmp_path).read_file({'path': 'binary.txt', 'max_bytes': 8192})


def test_incomplete_file_utf8_still_rejected(tmp_path):
    (tmp_path / 'broken.txt').write_bytes(b'abc\xe1')
    with pytest.raises(WorkspaceError, match='not UTF-8'):
        Worker(tmp_path).read_file({'path': 'broken.txt', 'max_bytes': 8192})

"""Phase 4-A regressions for symlink bypasses and legacy ingress port conflict."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest
from agent.worker import Worker, WorkspaceError


def test_internal_symlink_to_hidden_file_is_denied(tmp_path):
    (tmp_path / '.env.dev').write_text('DO-NOT-READ', encoding='utf-8')
    (tmp_path / 'alias.txt').symlink_to('.env.dev')
    w = Worker(tmp_path)
    with pytest.raises(WorkspaceError):
        w.read_file({'path': 'alias.txt'})
    assert 'alias.txt' not in [e['name'] for e in w.list_directory({'path': '.'})['entries']]


def test_internal_symlink_to_regular_file_is_denied(tmp_path):
    (tmp_path / 'normal.txt').write_text('regular', encoding='utf-8')
    (tmp_path / 'alias.txt').symlink_to('normal.txt')
    with pytest.raises(WorkspaceError):
        Worker(tmp_path).read_file({'path': 'alias.txt'})


def test_intermediate_symlink_is_denied(tmp_path):
    directory = tmp_path / 'real'
    directory.mkdir()
    (directory / 'ok.txt').write_text('safe', encoding='utf-8')
    (tmp_path / 'aliasdir').symlink_to('real', target_is_directory=True)
    w = Worker(tmp_path)
    with pytest.raises(WorkspaceError):
        w.read_file({'path': 'aliasdir/ok.txt'})
    with pytest.raises(WorkspaceError):
        w.list_directory({'path': 'aliasdir'})


def test_normal_nested_reads_and_lists_still_work(tmp_path):
    directory = tmp_path / 'docs'
    directory.mkdir()
    (directory / 'hello.txt').write_text('Xin chào', encoding='utf-8')
    w = Worker(tmp_path)
    assert w.read_file({'path': 'docs/hello.txt', 'max_bytes': 64})['content'] == 'Xin chào'
    assert 'hello.txt' in [e['name'] for e in w.list_directory({'path': 'docs'})['entries']]


@pytest.mark.parametrize('script', ['agent_quick_tunnel.sh', 'run_ingress.sh'])
def test_legacy_public_ingress_scripts_fail_closed(script):
    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(['bash', str(project / 'scripts' / script)],
                            cwd=project, env={'PATH': '/usr/bin:/bin'},
                            capture_output=True, text=True, timeout=3, check=False)
    assert result.returncode == 2
    assert 'DISABLED' in result.stderr

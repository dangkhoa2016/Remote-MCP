"""Phase 4-C: gated, no-follow text edits, source hashing, static checks."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path

import pytest
from fastapi import HTTPException
from agent.worker import Worker, WorkspaceError
from gateway.relay import State, Dispatch


def digest(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def test_writes_and_checks_disabled_by_default(tmp_path):
    w = Worker(tmp_path)
    with pytest.raises(WorkspaceError, match='disabled'):
        w.write_file({'path':'new.md','content':'hello'})
    with pytest.raises(WorkspaceError, match='disabled'):
        w.check_syntax({'path':'a.py'})
    with pytest.raises(WorkspaceError, match='disabled'):
        w.execute_command({'command_id':'python_version'})


def test_create_read_hash_and_update(tmp_path):
    w = Worker(tmp_path, write_enabled=True, checks_enabled=True)
    created = w.dispatch('write_file', {'path':'guide.md','content':'hello\n'})
    assert created['action'] == 'created'
    assert created['sha256'] == digest('hello\n')
    assert w.dispatch('file_sha256', {'path':'guide.md'})['sha256'] == digest('hello\n')
    assert w.read_file({'path':'guide.md'})['content'] == 'hello\n'
    with pytest.raises(WorkspaceError, match='expected_sha256'):
        w.write_file({'path':'guide.md','content':'no precondition'})
    with pytest.raises(WorkspaceError, match='mismatch'):
        w.write_file({'path':'guide.md','content':'x','expected_sha256':'0'*64})
    updated = w.write_file({'path':'guide.md','content':'new\n','expected_sha256':digest('hello\n')})
    assert updated['action'] == 'updated'
    assert w.read_file({'path':'guide.md'})['content'] == 'new\n'


@pytest.mark.parametrize('path', [
    '../outside.md', '/etc/passwd', '.env', 'env.dev.txt', 'service-token.json',
    'credentials.backup', 'secret.key', 'run.sh', 'dir/../bad.md'
])
def test_dangerous_paths_denied(tmp_path, path):
    w = Worker(tmp_path, write_enabled=True)
    with pytest.raises(WorkspaceError):
        w.write_file({'path':path,'content':'x'})
    with pytest.raises(WorkspaceError):
        w.file_sha256({'path':path})


def test_symlink_paths_denied(tmp_path):
    outside = tmp_path.parent / 'outside-danger.md'
    outside.write_text('do not modify')
    (tmp_path/'alias.md').symlink_to(outside)
    (tmp_path/'linkdir').symlink_to(tmp_path.parent, target_is_directory=True)
    w = Worker(tmp_path, write_enabled=True)
    for p in ('alias.md','linkdir/outside-danger.md'):
        with pytest.raises(WorkspaceError):
            w.write_file({'path':p,'content':'bad'})
    assert outside.read_text() == 'do not modify'


def test_limits_immutable_on_failure(tmp_path):
    w = Worker(tmp_path, write_enabled=True)
    (tmp_path/'a.txt').write_text('original')
    for content in ('a'*16385,'x\x00y'):
        with pytest.raises(WorkspaceError):
            w.write_file({'path':'a.txt','content':content,'expected_sha256':digest('original')})
    assert (tmp_path/'a.txt').read_text() == 'original'
    (tmp_path/'big.md').write_text('x'*262145)
    with pytest.raises(WorkspaceError, match='too large'):
        w.file_sha256({'path':'big.md'})


def test_hardlinks_readonly_file_denied(tmp_path):
    w = Worker(tmp_path, write_enabled=True)
    p = tmp_path/'a.md'
    p.write_text('old')
    os.link(p, tmp_path/'b.md')
    with pytest.raises(WorkspaceError, match='Hard-linked'):
        w.write_file({'path':'a.md','content':'new','expected_sha256':digest('old')})
    os.unlink(tmp_path/'b.md')
    p.chmod(0o400)
    with pytest.raises(WorkspaceError, match='read-only'):
        w.write_file({'path':'a.md','content':'new','expected_sha256':digest('old')})


def test_static_checks_parse_without_exec(tmp_path):
    w = Worker(tmp_path, checks_enabled=True)
    marker = tmp_path.parent / 'not-executed-test-marker'
    dangerous = 'from pathlib import Path\nPath(' + repr(str(marker)) + ').write_text("oops")\n'
    (tmp_path/'code.py').write_text(dangerous)
    good = w.check_syntax({'path':'code.py'})
    assert good['valid'] is True and good['executed'] is False
    assert not marker.exists()
    (tmp_path/'code.py').write_text('def broken(:\n')
    bad = w.check_syntax({'path':'code.py'})
    assert bad['valid'] is False and bad['executed'] is False
    (tmp_path/'data.json').write_text('{"ok":true}')
    assert w.check_syntax({'path':'data.json'})['valid'] is True
    (tmp_path/'data.toml').write_text('[app]\nvalue=1\n')
    assert w.check_syntax({'path':'data.toml'})['valid'] is True


@pytest.mark.asyncio
async def test_relay_denies_new_operations_without_separate_opt_in():
    state = State({'local-dev':'a'*48}, 'b'*48, commands_enabled=False)
    for operation in ('write_file','check_syntax'):
        with pytest.raises(HTTPException) as exc:
            await state.submit(Dispatch(device_id='local-dev',operation=operation,arguments={}))
        assert exc.value.status_code == 403


def test_write_opt_in_does_not_enable_shell(tmp_path):
    w=Worker(tmp_path, write_enabled=True, checks_enabled=True)
    with pytest.raises(WorkspaceError, match='disabled'):
        w.execute_command({'command_id':'python_version'})
    relay=State({'local-dev':'a'*48}, 'b'*48, writes_enabled=True, checks_enabled=True)
    assert relay.commands_enabled is False

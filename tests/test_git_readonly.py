"""Git reading: isolated Git read-only regression tests."""
from __future__ import annotations

import subprocess
from pathlib import Path
import pytest
from agent.git_readonly import GitReadOnly, GitReadOnlyError
from agent.worker import Worker, WorkspaceError


def git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.name', 'Test')
    git(tmp_path, 'config', 'user.email', 'test@example.invalid')
    (tmp_path / 'README.md').write_text('hello\n')
    (tmp_path / '.env.dev').write_text('TEST_PASSWORD=sensitive\n')
    git(tmp_path, 'add', 'README.md', '.env.dev')
    git(tmp_path, 'commit', '-qm', 'Initial commit')
    return tmp_path


def inspector(repo):
    worker = Worker(repo)
    return GitReadOnly(repo, worker.path)


def test_status_excludes_hidden_names(repo):
    (repo / 'README.md').write_text('updated\n')
    (repo / '.env.dev').write_text('changed-secret\n')
    (repo / 'new.py').write_text('print(1)\n')
    result = inspector(repo).status()
    assert {v['path'] for v in result['entries']} == {'README.md', 'new.py'}
    assert result['read_only']
    assert result['working_tree_clean'] is False
    assert result['hidden_changes'] is True


def test_diff_file_and_staged(repo):
    (repo / 'README.md').write_text('hello\nadded\n')
    r = inspector(repo).diff('README.md')
    assert '+added' in r['diff']
    git(repo, 'add', 'README.md')
    assert '+added' in inspector(repo).diff('README.md', staged=True)['diff']
    assert inspector(repo).diff('README.md')['diff'] == ''


def test_never_diff_secrets(repo):
    for path in ('.env.dev', '../x', '/etc/passwd', 'fake.pem'):
        with pytest.raises(GitReadOnlyError):
            inspector(repo).diff(path)


def test_symlinks_rejected(repo):
    (repo / 'alias.md').symlink_to('README.md')
    with pytest.raises(GitReadOnlyError):
        inspector(repo).diff('alias.md')


def test_log_bounds(repo):
    log = inspector(repo).log(5)
    assert len(log['commits']) == 1
    assert log['commits'][0]['subject'] == 'Initial commit'
    for count in (0, -1, 100, True, '5'):
        with pytest.raises(GitReadOnlyError):
            inspector(repo).log(count)


def test_requires_local_git_directory(tmp_path):
    with pytest.raises(GitReadOnlyError):
        GitReadOnly(tmp_path, Worker(tmp_path).path)


def test_no_arbitrary_git_commands(repo, monkeypatch):
    seen = []
    real = subprocess.run
    def spy(*args, **kwargs):
        seen.append((args[0], kwargs))
        return real(*args, **kwargs)
    monkeypatch.setattr(subprocess, 'run', spy)
    inspector(repo).status()
    argv, options = seen[-1]
    assert options['stdin'] == subprocess.DEVNULL
    assert options['env']['GIT_OPTIONAL_LOCKS'] == '0'
    assert options['env']['GIT_CONFIG_GLOBAL'] == '/dev/null'
    assert 'sh' not in argv and '--exec-path' not in argv
    assert options.get('shell') is not True


def test_worker_exposes_only_specific_git_operations(repo):
    worker = Worker(repo)
    log = worker.dispatch('git_log', {'count': 1})
    assert len(log['commits']) == 1
    assert worker.dispatch('git_status', {})['read_only'] is True
    (repo / 'README.md').write_text('new line\n')
    assert worker.dispatch('git_diff', {'path': 'README.md'})['read_only'] is True
    with pytest.raises(WorkspaceError):
        worker.dispatch('git_diff', {'path': '.env.dev'})


def test_relay_accepts_git_operations_but_denies_remote_shell():
    from gateway.relay import Dispatch, State
    for op in ('git_status', 'git_diff', 'git_log'):
        assert Dispatch(device_id='local-dev', operation=op, arguments={}).operation == op
    # Command execution is still blocked by the Relay regardless of Git read operations.
    state = State({'local-dev': 'a'*48}, 'b'*48, commands_enabled=False)
    assert state.commands_enabled is False


def test_no_sensitive_names_in_git_status_or_diff(repo):
    (repo / 'env.dev.txt').write_text('SENSITIVE=NO\n')
    (repo / 'service-token.json').write_text('NO\n')
    (repo / 'config.py').write_text('print(1)\n')
    st = inspector(repo).status()
    paths = {x['path'] for x in st['entries']}
    assert 'env.dev.txt' not in paths
    assert 'service-token.json' not in paths
    assert 'config.py' in paths
    for name in ('env.dev.txt','service-token.json','config.env'):
        with pytest.raises(GitReadOnlyError):
            inspector(repo).diff(name)

def test_diff_limit_no_shell_and_readonly(repo):
    (repo / 'README.md').write_text('hello\n' + ('a'*20000) + '\n')
    result = inspector(repo).diff('README.md')
    assert result['truncated'] is True
    assert len(result['diff']) == 12000
    assert result['read_only'] is True


def test_status_exposes_safe_untracked_directory_as_directory(repo):
    # Git --untracked-files=normal returns '?? benchmarks/' (not child files).
    nested = repo / 'benchmarks' / 'qwen-image-q4ks-t4x2'
    nested.mkdir(parents=True)
    (nested / 'README.md').write_text('untracked benchmark fixture\n')
    status = inspector(repo).status()
    assert status['working_tree_clean'] is False
    assert status['hidden_changes'] is False
    assert status['limited'] is False
    assert {'state': '??', 'path': 'benchmarks/'} in status['entries']


def test_status_flags_hidden_only_changes_without_disclosing_names(repo):
    (repo / 'service-token.json').write_text('sensitive content\n')
    state = inspector(repo).status()
    assert state['entries'] == []
    assert state['working_tree_clean'] is False
    assert state['hidden_changes'] is True
    assert 'service-token.json' not in str(state)


def test_status_hides_restricted_untracked_directories(repo):
    hidden = repo / 'secret-token'
    hidden.mkdir()
    (hidden / 'note.md').write_text('do not disclose directory\n')
    state = inspector(repo).status()
    assert state['entries'] == []
    assert state['working_tree_clean'] is False
    assert state['hidden_changes'] is True
    assert 'secret-token' not in str(state)


def test_status_clean_when_no_changes(repo):
    state = inspector(repo).status()
    assert state['entries'] == []
    assert state['working_tree_clean'] is True
    assert state['hidden_changes'] is False

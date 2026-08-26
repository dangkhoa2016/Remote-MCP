import importlib.util
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_scanner():
    path = ROOT / 'scripts' / 'scan-release-artifact.py'
    spec = importlib.util.spec_from_file_location('scan_release_artifact', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scan_artifact = _load_scanner().scan_artifact


def _make_zip(path: Path, members: list[tuple[str, bytes]]) -> None:
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, content in members:
            zf.writestr(name, content)


def test_safe_archive_passes(tmp_path):
    z = tmp_path / 'safe.zip'
    _make_zip(z, [('README.md', b'hello world'), ('app/main.py', b'print(1)')])
    assert scan_artifact(z) == []


def test_archive_with_secrets_api_key_member_fails(tmp_path):
    z = tmp_path / 'bad-secret.zip'
    _make_zip(z, [('secrets/api-key', b'secret-value')])
    findings = scan_artifact(z)
    assert findings
    names = [f['member'] for f in findings]
    assert any('api-key' in name for name in names)
    assert all('secret-value' not in f['reason'] for f in findings)


def test_archive_with_raw_trycloudflare_hostname_fails(tmp_path):
    z = tmp_path / 'bad-host.zip'
    _make_zip(z, [('evidence/run.txt', b'live at https://abc-xyz.trycloudflare.com now')])
    findings = scan_artifact(z)
    assert any('trycloudflare' in f['reason'] for f in findings)


def test_archive_with_authorization_bearer_text_fails(tmp_path):
    z = tmp_path / 'bad-auth.zip'
    token = 'sk-ephemeral-topsecret123'
    _make_zip(z, [('notes.txt', f'Authorization: Bearer {token}'.encode('utf-8'))])
    findings = scan_artifact(z)
    assert any('Authorization' in f['reason'] for f in findings)
    blob = repr(findings)
    assert token not in blob


def test_archive_with_pycache_member_fails(tmp_path):
    z = tmp_path / 'bad-cache.zip'
    _make_zip(z, [('__pycache__/x.pyc', b'\x00\x01')])
    findings = scan_artifact(z)
    assert any('cache' in f['reason'] for f in findings)
    assert any('__pycache__' in f['member'] for f in findings)


def test_archive_with_config_pyc_member_fails(tmp_path):
    z = tmp_path / 'bad-pyc.zip'
    _make_zip(z, [('app/config.pyc', b'\x00\x01')])
    findings = scan_artifact(z)
    assert any('cache' in f['reason'] for f in findings)


def _git(*args, cwd):
    proc = subprocess.run(
        ['git', *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**__import__('os').environ, 'GIT_TERMINAL_PROMPT': '0'},
    )
    return proc


@pytest.fixture(scope='module')
def packaged_release(tmp_path_factory):
    """Run scripts/package-release.sh once into a temp out dir."""
    out = tmp_path_factory.mktemp('release-out')
    proc = subprocess.run(
        ['bash', str(ROOT / 'scripts' / 'package-release.sh'), f'--out={out}'],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert proc.returncode == 0, f'package-release.sh failed:\n{proc.stdout}\n{proc.stderr}'
    return out


def test_with_git_archive_is_local_only_and_fsck_clean(packaged_release):
    with_git = packaged_release / 'qwen3-embedding-8b-t4x2-v1.0.0-with-git.zip'
    assert with_git.is_file()
    extract = packaged_release / 'extracted-with-git'
    extract.mkdir()
    # Extract with the real unzip so executable bits are preserved, exactly
    # like the release-verification path does.
    assert subprocess.run(
        ['unzip', '-q', str(with_git), '-d', str(extract)],
        capture_output=True,
    ).returncode == 0

    assert b'' == _git('remote', cwd=extract).stdout.encode().strip()
    assert b'' == _git('tag', '-l', cwd=extract).stdout.encode().strip()
    assert b'' == _git('status', '--porcelain', cwd=extract).stdout.encode().strip()

    fsck = _git('fsck', '--full', cwd=extract)
    assert fsck.returncode == 0, fsck.stderr

    assert not (extract / '.git' / 'refs' / 'remotes' / 'origin' / 'HEAD').exists()
    assert not (extract / '.git' / 'refs' / 'remotes').exists()
    assert not (extract / '.git' / 'logs' / 'refs' / 'remotes').exists()

    computed_head = _git('rev-parse', 'HEAD', cwd=extract).stdout.strip()
    source_head = _git('rev-parse', 'HEAD', cwd=ROOT).stdout.strip()
    assert computed_head == source_head
    count = int(_git('rev-list', '--count', 'HEAD', cwd=extract).stdout.strip())
    source_count = int(_git('rev-list', '--count', 'HEAD', cwd=ROOT).stdout.strip())
    assert count == source_count


def test_checksum_manifest_is_portable_and_relocatable(packaged_release):
    manifest = packaged_release / 'qwen3-embedding-8b-t4x2-v1.0.0-artifacts.sha256'
    assert manifest.is_file()
    rows = manifest.read_text().splitlines()
    assert len(rows) == 3
    for row in rows:
        checksum, name = row.split()
        assert len(checksum) == 64
        assert Path(name).name == name
        assert '/' not in name

    relocated = packaged_release / 'relocated'
    relocated.mkdir()
    for name in ('qwen3-embedding-8b-t4x2-v1.0.0.zip',
                 'qwen3-embedding-8b-t4x2-v1.0.0-with-git.zip',
                 'qwen3-embedding-8b-t4x2-v1.0.0-evidence.tar.gz'):
        shutil.copy2(packaged_release / name, relocated / name)
    shutil.copy2(manifest, relocated / manifest.name)

    result = subprocess.run(
        ['sha256sum', '-c', manifest.name],
        cwd=relocated,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout

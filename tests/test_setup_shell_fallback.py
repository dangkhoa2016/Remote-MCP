"""Regression: installer supports Colab when ensurepip-backed venv creation fails."""
from __future__ import annotations

import hashlib
import io
import os
import shlex
import sys
from pathlib import Path
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / 'bundle.tar.gz'
    with tarfile.open(bundle, 'w:gz') as tar:
        for name in ('agent/__init__.py', 'agent/agent.py', 'agent/worker.py',
                     'agent/git_readonly.py', 'agent/git_write.py', 'agent/workspace_routes.py',
                     'agent/workspace_edit.py',
                     'agent/workspace_manage.py', 'agent-requirements.txt'):
            raw = b'httpx>=0.27,<1\n' if name.endswith('requirements.txt') else b'# test\n'
            meta = tarfile.TarInfo(name)
            meta.size = len(raw)
            tar.addfile(meta, io.BytesIO(raw))
    return bundle


@pytest.mark.parametrize('venv_mode', ['broken', 'works'])
def test_installer_handles_colab_venv_failure_and_good_venv(tmp_path, venv_mode):
    bundle = _bundle(tmp_path)
    script = ROOT / 'gateway' / 'setup.sh'
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    rendered = script.read_text().replace('__KRW_AGENT_BUNDLE_SHA256__', digest).replace(
        '__KRW_PUBLIC_ORIGIN__', 'https://example.test')
    assert '__KRW_PUBLIC_ORIGIN__' not in rendered
    assert '__KRW_AGENT_BUNDLE_SHA256__' not in rendered
    installer = tmp_path / 'setup.sh'
    installer.write_text(rendered)
    fakebin = tmp_path / 'fakebin'
    fakebin.mkdir()
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    install = tmp_path / 'install'
    config = tmp_path / 'config'

    fake_python = fakebin / 'python3'
    fake_python.write_text("""#!/usr/bin/env bash
set -e
if [[ "$1" == '-c' ]]; then exec /usr/bin/python3 "$@"; fi
if [[ "$1" == '-m' && "$2" == 'venv' ]]; then
  if [[ "$KRW_TEST_VENV_MODE" == works ]]; then
    mkdir -p "$3/bin"
    cp "$KRW_TEST_PY_WRAPPER" "$3/bin/python"
    exit 0
  fi
  exit 1
fi
if [[ "$1" == '-m' && "$2" == pip ]]; then
  if [[ "$3" == --version ]]; then printf 'mock pip\\n'; exit 0; fi
  printf 'PIP %s\\n' "$*" >> "$KRW_TEST_LOG"
  exit 0
fi
if [[ "$1" == '-m' && "$2" == agent.agent ]]; then
  printf 'AGENT_STARTED device=%s commands=%s path=%s\\n' "$KRW_DEVICE_ID" "$KRW_COMMANDS_ENABLED" "${PYTHONPATH:-}" >> "$KRW_TEST_LOG"
  exit 0
fi
exit 90
""".replace("/usr/bin/python3", shlex.quote(sys.executable)))
    fake_python.chmod(0o755)
    fake_curl = fakebin / 'curl'
    fake_curl.write_text("""#!/usr/bin/env bash
set -e
if [[ "$*" != *agent-bundle.tar.gz* ]]; then exit 10; fi
for ((i=1; i<=$#; i++)); do
  if [[ "${!i}" == -o ]]; then
    j=$((i+1)); cp "$KRW_TEST_ARCHIVE" "${!j}"; exit 0
  fi
done
exit 11
""")
    fake_curl.chmod(0o755)
    log = tmp_path / 'actions.log'
    env = dict(os.environ, PATH=f'{fakebin}:{os.environ["PATH"]}',
               KRW_DEVICE_ID='colab-test', KRW_WORKSPACE_ROOT=str(workspace),
               KRW_AGENT_TOKEN='a' * 48, KRW_INSTALL_DIR=str(install),
               KRW_CONFIG_DIR=str(config), KRW_TEST_ARCHIVE=str(bundle),
               KRW_TEST_LOG=str(log), KRW_TEST_VENV_MODE=venv_mode,
               KRW_TEST_PY_WRAPPER=str(fake_python))
    result = subprocess.run(['bash', str(installer)], env=env,
                            capture_output=True, text=True, timeout=12)
    assert result.returncode == 0, result.stderr
    assert 'AGENT_STARTED device=colab-test commands=0' in log.read_text()
    assert (config / 'agent.env').stat().st_mode & 0o077 == 0
    assert (install / 'start.sh').exists()
    # Upgrade without passing the token/device again, retaining opt-in flags.
    config_file = config / 'agent.env'
    existing = config_file.read_text(encoding='utf-8')
    config_file.write_text(existing.replace('KRW_ALLOW_FILE_WRITES=0',
                                            'KRW_ALLOW_FILE_WRITES=1').replace(
        'KRW_ALLOW_STATIC_CHECKS=0', 'KRW_ALLOW_STATIC_CHECKS=1'), encoding='utf-8')
    upgrade_env = dict(env)
    for key in ('KRW_DEVICE_ID', 'KRW_WORKSPACE_ROOT', 'KRW_AGENT_TOKEN',
                'KRW_ALLOW_FILE_WRITES', 'KRW_ALLOW_STATIC_CHECKS'):
        upgrade_env.pop(key, None)
    upgraded = subprocess.run(['bash', str(installer)], env=upgrade_env,
                              capture_output=True, text=True, timeout=12)
    assert upgraded.returncode == 0, upgraded.stderr
    assert 'Reusing existing Agent configuration' in upgraded.stderr
    upgraded_config = config_file.read_text(encoding='utf-8')
    assert 'KRW_DEVICE_ID=colab-test' in upgraded_config
    assert 'KRW_ALLOW_FILE_WRITES=1' in upgraded_config
    assert 'KRW_ALLOW_STATIC_CHECKS=1' in upgraded_config
    assert 'AGENT_STARTED device=colab-test commands=0' in log.read_text()

    if venv_mode == 'broken':
        assert 'using isolated --target dependencies' in result.stderr
        assert '--target' in log.read_text()
        assert str(install / '.packages') in log.read_text()
    else:
        assert 'Created Python virtual environment' in result.stderr
        assert '--target' not in log.read_text()


def test_shell_syntax():
    result = subprocess.run(['bash', '-n', str(ROOT / 'gateway/setup.sh')],
                            capture_output=True, text=True, timeout=4)
    assert result.returncode == 0, result.stderr

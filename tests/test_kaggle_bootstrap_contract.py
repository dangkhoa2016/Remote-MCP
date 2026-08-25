from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_REQ = ROOT / 'requirements-test.txt'
BOOTSTRAP = ROOT / 'kaggle/bootstrap.sh'


def _bootstrap_text() -> str:
    return BOOTSTRAP.read_text(encoding='utf-8')


def test_requirements_test_contains_pytest_asyncio():
    text = TEST_REQ.read_text(encoding='utf-8')
    assert 'pytest-asyncio' in text


def test_bootstrap_prepends_opt_bin_when_present():
    text = _bootstrap_text()
    assert '/opt/bin' in text
    assert 'PATH' in text


def test_bootstrap_prepends_opt_nvidia_bin_when_present():
    text = _bootstrap_text()
    assert '/opt/nvidia/bin' in text
    assert 'PATH' in text


def test_bootstrap_prepends_nvidia_lib64_to_ld_library_path_when_present():
    text = _bootstrap_text()
    assert '/usr/local/nvidia/lib64' in text
    assert 'LD_LIBRARY_PATH' in text


def test_bootstrap_records_torch_before_dependency_work():
    text = _bootstrap_text()
    assert 'TORCH_VERSION_BEFORE' in text
    assert 'TORCH_FILE_BEFORE' in text


def test_bootstrap_verifies_torch_unchanged_after_dependency_work():
    text = _bootstrap_text()
    assert 'TORCH_VERSION_AFTER' in text
    assert 'TORCH_FILE_AFTER' in text
    assert 'test "$TORCH_VERSION_BEFORE" = "$TORCH_VERSION_AFTER"' in text
    assert 'test "$TORCH_FILE_BEFORE" = "$TORCH_FILE_AFTER"' in text


def test_bootstrap_never_runs_pip_install_torch():
    text = _bootstrap_text()
    assert 'pip install torch' not in text
    assert 'pip install "torch' not in text
    assert 'pip install torch=' not in text


def test_bootstrap_installs_requirements_test():
    text = _bootstrap_text()
    assert 'requirements-test.txt' in text
    assert 'pip install -r requirements-test.txt' in text


def test_bootstrap_emits_dependency_versions():
    text = _bootstrap_text()
    for pkg in (
        'torch', 'transformers', 'accelerate', 'bitsandbytes',
        'safetensors', 'fastapi', 'uvicorn', 'httpx', 'numpy',
        'faiss', 'pyarrow', 'pytest', 'pytest-asyncio',
    ):
        assert pkg in text


def test_bootstrap_never_writes_below_kaggle_input():
    text = _bootstrap_text()
    assert '/kaggle/input' in text
    import re
    assert re.search(r'(?:>|tee|cp|mv|mkdir|touch|\bwrite\b).*?/kaggle/input', text) is None


def test_bootstrap_does_not_replace_a_working_torch_stack():
    text = _bootstrap_text()
    assert 'requirements-kaggle.txt' in text
    assert 'satisfies it' in text or 'TORCH_VERSION_BEFORE' in text

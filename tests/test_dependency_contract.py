from pathlib import Path


def test_transformers_range_matches_pyproject_and_requirements():
    req = Path('requirements-kaggle.txt').read_text(encoding='utf-8')
    pyproject = Path('pyproject.toml').read_text(encoding='utf-8')
    assert 'transformers>=5.0.0,<6' in req
    assert 'transformers>=5.0.0,<6' in pyproject


def test_acceptance_records_imported_runtime_dependency_versions():
    text = Path('kaggle/acceptance.sh').read_text(encoding='utf-8')
    assert 'dependency-versions.txt' in text
    for name in ('torch', 'transformers', 'accelerate', 'bitsandbytes', 'safetensors',
                 'fastapi', 'uvicorn', 'httpx', 'numpy', 'faiss', 'pyarrow'):
        assert repr(name) in text or f'"{name}"' in text

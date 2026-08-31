from pathlib import Path
from app import __version__


def test_package_version_matches_first_public_release():
    assert __version__ == '1.0.0'
    assert 'version = "1.0.0"' in Path('pyproject.toml').read_text(encoding='utf-8')

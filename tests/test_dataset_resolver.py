from pathlib import Path
import json
import pytest


def _make_dataset(path: Path, rows: int = 2):
    path.mkdir(parents=True)
    parquet = path / 'wikidata-en-vi-100k.parquet'
    parquet.write_bytes(b'parquet-bytes')
    import hashlib
    digest = hashlib.sha256(parquet.read_bytes()).hexdigest()
    (path / 'dataset-manifest.json').write_text(json.dumps({
        'source': 'wikidata', 'source_license': 'CC0-1.0', 'row_count': rows,
        'canonical_filename': parquet.name, 'canonical_sha256': digest,
    }))
    (path / 'data-quality-report.json').write_text(json.dumps({'accepted_rows': rows, 'rejected_rows': 0}))
    return path


def test_dataset_resolver_prefers_wikidata_named_candidate(tmp_path: Path):
    from app.dataset_resolver import resolve_kaggle_dataset_dir
    root = tmp_path / 'input'
    _make_dataset(root / 'other')
    preferred = _make_dataset(root / 'wikidata-en-vi-semantic-search-100k')
    assert resolve_kaggle_dataset_dir(root, None) == preferred.resolve()


def test_dataset_resolver_rejects_checksum_mismatch(tmp_path: Path):
    from app.dataset_resolver import validate_dataset_dir, DatasetResolutionError
    dataset = _make_dataset(tmp_path / 'input' / 'wikidata-en-vi')
    (dataset / 'wikidata-en-vi-100k.parquet').write_bytes(b'tampered')
    with pytest.raises(DatasetResolutionError, match='checksum'):
        validate_dataset_dir(dataset)

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json


class DatasetResolutionError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_dataset_dir(path: Path) -> dict:
    path = Path(path).resolve()
    manifest_path = path / 'dataset-manifest.json'
    quality_path = path / 'data-quality-report.json'
    if not manifest_path.is_file() or not quality_path.is_file():
        raise DatasetResolutionError(f'missing dataset manifest/quality report: {path}')
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetResolutionError(f'invalid dataset manifest: {path}') from exc
    if manifest.get('source') != 'wikidata' or manifest.get('source_license') != 'CC0-1.0':
        raise DatasetResolutionError('dataset must declare source=wikidata and source_license=CC0-1.0')
    canonical_name = manifest.get('canonical_filename')
    expected_sha = manifest.get('canonical_sha256')
    if not canonical_name or not expected_sha:
        raise DatasetResolutionError('dataset manifest is missing canonical filename/checksum')
    canonical_path = path / canonical_name
    if not canonical_path.is_file():
        raise DatasetResolutionError(f'canonical dataset file is missing: {canonical_path}')
    actual_sha = _sha256_file(canonical_path)
    if actual_sha != expected_sha:
        raise DatasetResolutionError(
            f'canonical dataset checksum mismatch: expected {expected_sha}, got {actual_sha}'
        )
    return manifest


def _candidate_dirs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    candidates: list[Path] = []
    for manifest in root.rglob('dataset-manifest.json'):
        try:
            rel = manifest.relative_to(root)
        except ValueError:
            continue
        if len(rel.parts) > 7:
            continue
        parent = manifest.parent.resolve()
        try:
            validate_dataset_dir(parent)
        except DatasetResolutionError:
            continue
        candidates.append(parent)
    return sorted(set(candidates))


def resolve_kaggle_dataset_dir(root: Path, explicit: str | None) -> Path:
    root = Path(root).resolve()
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not _is_under(path, root):
            raise DatasetResolutionError(f'KAGGLE_DATASET_DIR must resolve under {root}; got {path}')
        validate_dataset_dir(path)
        return path
    candidates = _candidate_dirs(root)
    preferred = [p for p in candidates if 'wikidata-en-vi' in str(p).lower()]
    selected = preferred if preferred else candidates
    if not selected:
        raise DatasetResolutionError(
            'No canonical Wikidata EN/VI Kaggle Dataset input found. Attach the CC0 dataset or set KAGGLE_DATASET_DIR.'
        )
    if len(selected) > 1:
        raise DatasetResolutionError(
            'Multiple canonical dataset directories found; set KAGGLE_DATASET_DIR explicitly:\n  - '
            + '\n  - '.join(str(p) for p in selected)
        )
    return selected[0]

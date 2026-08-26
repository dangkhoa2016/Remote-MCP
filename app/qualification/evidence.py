from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
from pathlib import Path

RUNTIME_ALLOWLIST = frozenset({
    'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_DATASETS_OFFLINE',
    'TOKENIZERS_PARALLELISM', 'KAGGLE_INPUT_ROOT', 'KAGGLE_MODEL_DIR',
    'KAGGLE_DATASET_DIR', 'WORKING_DIR', 'SEARCH_INDEX_DIR', 'WORKER_COUNT',
    'PORT', 'MAX_SEQUENCE_TOKENS', 'MAX_BATCH_ITEMS', 'MAX_BATCH_ESTIMATED_TOKENS',
    'MAX_QUEUE_ESTIMATED_TOKENS', 'BENCH_REQUESTS', 'BENCH_SINGLE_CONCURRENCY',
    'BENCH_DUAL_CONCURRENCY', 'BENCH_ITEMS_PER_REQUEST', 'BENCH_DIMENSIONS',
    'PYTORCH_ALLOC_CONF', 'EXPOSE_MODE',
})


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False,
    ).encode('utf-8')


def sha256_json(value: object) -> str:
    return sha256(_canonical_json_bytes(value)).hexdigest()


def workload_fingerprint(payload: Mapping[str, object]) -> str:
    return sha256_json(dict(payload))


def sanitize_runtime_config(env: Mapping[str, str]) -> dict[str, str]:
    return {key: str(env[key]) for key in sorted(RUNTIME_ALLOWLIST) if key in env}


def scan_secret_bytes(paths: Sequence[Path], secret: str) -> list[Path]:
    if not secret:
        return []
    needle = secret.encode('utf-8')
    matches: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if needle in data:
            matches.append(path)
    return matches


def sha256_file(path: Path) -> str:
    digest = sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def write_manifest_v2(
    root: Path,
    *,
    run_id: str,
    run_kind: str,
    identity: Mapping[str, object],
    runtime_config: Mapping[str, str] | None = None,
    filename: str = 'run-manifest.json',
) -> dict:
    root = Path(root)
    if not run_kind:
        raise ValueError('run_kind must be non-null')
    files: dict[str, dict[str, object]] = {}
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in {filename, 'SHA256SUMS'}:
            continue
        files[relative] = {
            'sha256': sha256_file(path),
            'bytes': path.stat().st_size,
        }
    manifest = {
        'schema_version': 2,
        'run_id': str(run_id),
        'run_kind': str(run_kind),
        **dict(identity),
        'runtime_config': dict(runtime_config or {}),
        'files': files,
    }
    (root / filename).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    return manifest

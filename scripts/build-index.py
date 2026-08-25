#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from app.config import Settings, enforce_offline_environment
from app.dataset_resolver import resolve_kaggle_dataset_dir, validate_dataset_dir
from app.inference.worker import WorkerProcessClient
from app.model_resolver import model_fingerprint, resolve_kaggle_model_dir
from app.scheduler.scheduler import EmbeddingScheduler
from app.search.build import build_search_index


def _load_rows(parquet_path: Path, limit: int | None) -> list[dict]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError('pyarrow is required; install requirements-kaggle.txt') from exc
    table = pq.read_table(parquet_path)
    if limit is not None:
        table = table.slice(0, limit)
    return table.to_pylist()


async def _run(args) -> int:
    enforce_offline_environment()
    settings = Settings.from_env()
    model_dir = resolve_kaggle_model_dir(settings.kaggle_input_root, settings.model_dir)
    fingerprint = model_fingerprint(model_dir)
    dataset_dir = resolve_kaggle_dataset_dir(settings.kaggle_input_root, os.getenv('KAGGLE_DATASET_DIR'))
    manifest = validate_dataset_dir(dataset_dir)
    parquet_path = dataset_dir / manifest['canonical_filename']
    rows = _load_rows(parquet_path, args.limit)
    if not rows:
        raise RuntimeError('canonical dataset contains no rows')

    workers = [WorkerProcessClient(i, model_dir, settings, physical_gpu_id=i) for i in range(settings.worker_count)]
    try:
        for worker in workers:
            worker.start(timeout=args.worker_start_timeout)
            print(f'WORKER_READY={worker.worker_id}:{worker.gpu_name}', flush=True)
        scheduler = EmbeddingScheduler(workers, settings)
        metadata = await build_search_index(
            rows,
            scheduler,
            args.output_dir,
            model_fingerprint=fingerprint,
            dimensions=args.dimensions,
            dataset_sha256=manifest['canonical_sha256'],
            request_batch_items=args.request_batch_items,
        )
        print(f'INDEX_DIR={args.output_dir.resolve()}')
        print(f'INDEX_ROWS={metadata.row_count}')
        print(f'INDEX_DIMENSIONS={metadata.dimensions}')
        print(f'MODEL_FINGERPRINT={metadata.model_fingerprint}')
        return 0
    finally:
        for worker in workers:
            worker.close()


def main() -> int:
    parser = argparse.ArgumentParser(description='Build a FAISS-compatible bilingual index with the attached Kaggle Model')
    parser.add_argument('--output-dir', type=Path, default=Path('/kaggle/working/qwen3-embedding-8b-t4x2/index'))
    parser.add_argument('--limit', type=int, default=None, help='Optional quick-demo corpus limit; omit for the full canonical dataset')
    parser.add_argument('--dimensions', type=int, default=int(os.getenv('EMBEDDING_DIMENSIONS', '4096')))
    parser.add_argument('--request-batch-items', type=int, default=64)
    parser.add_argument('--worker-start-timeout', type=float, default=300.0)
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == '__main__':
    raise SystemExit(main())

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np

from app.search.index import IndexMetadata, VectorIndex


def canonical_search_text(row: dict) -> str:
    parts: list[str] = []
    if row.get('document_en'):
        parts.append(f"English: {row['document_en']}")
    if row.get('document_vi'):
        parts.append(f"Vietnamese: {row['document_vi']}")
    if not parts:
        raise ValueError(f"row {row.get('qid', '<unknown>')} has no canonical document")
    return '\n'.join(parts)


async def build_search_index(
    rows: Iterable[dict],
    scheduler,
    output_dir: Path,
    *,
    model_fingerprint: str,
    dimensions: int,
    dataset_sha256: str,
    request_batch_items: int = 64,
) -> IndexMetadata:
    materialized = list(rows)
    if not materialized:
        raise ValueError('cannot build an empty search index')
    if request_batch_items < 1:
        raise ValueError('request_batch_items must be positive')
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    mmap_path = output_dir / '.embedding-build.memmap'
    matrix = np.memmap(mmap_path, mode='w+', dtype=np.float32, shape=(len(materialized), dimensions))
    persisted_rows: list[dict] = []
    try:
        for start in range(0, len(materialized), request_batch_items):
            chunk = materialized[start:start + request_batch_items]
            texts = [canonical_search_text(row) for row in chunk]
            result = await scheduler.embed(texts, dimensions, False)
            chunk_vectors = np.asarray(result.embeddings, dtype=np.float32)
            expected_shape = (len(chunk), dimensions)
            if chunk_vectors.shape != expected_shape:
                raise RuntimeError(f'embedding shape mismatch: expected {expected_shape}, got {chunk_vectors.shape}')
            matrix[start:start + len(chunk)] = chunk_vectors
            matrix.flush()
            for row, text in zip(chunk, texts, strict=True):
                persisted = dict(row)
                persisted['canonical_document'] = text
                persisted_rows.append(persisted)
        metadata = IndexMetadata(
            model_fingerprint=model_fingerprint,
            dimensions=dimensions,
            row_count=len(materialized),
            dataset_sha256=dataset_sha256,
        )
        VectorIndex.build(np.asarray(matrix), persisted_rows, metadata).save(output_dir)
        return metadata
    finally:
        del matrix
        try:
            mmap_path.unlink()
        except FileNotFoundError:
            pass

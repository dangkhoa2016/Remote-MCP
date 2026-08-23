from pathlib import Path

import numpy as np
import pytest

from app.scheduler.scheduler import ScheduledEmbeddingResult


class FakeScheduler:
    def __init__(self):
        self.calls = []

    async def embed(self, texts, dimensions, is_query):
        self.calls.append((list(texts), dimensions, is_query))
        vectors = []
        for text in texts:
            v = np.zeros(dimensions, dtype=np.float32)
            v[0 if 'Berlin' in text else 1] = 1.0
            vectors.append(v.tolist())
        return ScheduledEmbeddingResult(vectors, token_count=len(texts))


@pytest.mark.asyncio
async def test_build_search_index_uses_document_mode_and_persists_canonical_text(tmp_path: Path):
    from app.search.build import build_search_index
    from app.search.index import VectorIndex, IndexMetadata

    rows = [
        {'qid': 'Q64', 'label_en': 'Berlin', 'label_vi': 'Berlin', 'document_en': 'Berlin. capital of Germany.', 'document_vi': 'Berlin. thủ đô Đức.'},
        {'qid': 'Q90', 'label_en': 'Paris', 'label_vi': 'Paris', 'document_en': 'Paris. capital of France.', 'document_vi': 'Paris. thủ đô Pháp.'},
    ]
    scheduler = FakeScheduler()
    out = tmp_path / 'index'
    meta = await build_search_index(rows, scheduler, out, model_fingerprint='fp', dimensions=32, dataset_sha256='hash', request_batch_items=2)
    assert meta.row_count == 2
    assert scheduler.calls[0][2] is False
    assert 'English:' in scheduler.calls[0][0][0]
    assert 'Vietnamese:' in scheduler.calls[0][0][0]
    loaded = VectorIndex.load(out, expected_metadata=IndexMetadata('fp', 32, 2, 'hash'))
    assert loaded.rows[0]['canonical_document'].startswith('English:')

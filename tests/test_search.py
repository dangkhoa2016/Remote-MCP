from pathlib import Path
import importlib

import numpy as np
import pytest


def _i():
    return importlib.import_module('app.search.index')


def test_vector_index_ranks_cosine_similarity_and_maps_rows(tmp_path: Path):
    i = _i()
    vectors = np.array([[1., 0.], [0., 1.], [0.8, 0.2]], dtype=np.float32)
    rows = [{'qid': 'Q1'}, {'qid': 'Q2'}, {'qid': 'Q3'}]
    meta = i.IndexMetadata('fp1', 2, 3, 'datahash')
    index = i.VectorIndex.build(vectors, rows, meta)
    hits = index.search(np.array([1., 0.], dtype=np.float32), top_k=2)
    assert [h.row['qid'] for h in hits] == ['Q1', 'Q3']
    assert hits[0].score >= hits[1].score


def test_index_save_load_rejects_model_or_dimension_mismatch(tmp_path: Path):
    i = _i()
    vectors = np.eye(2, dtype=np.float32)
    rows = [{'qid': 'Q1'}, {'qid': 'Q2'}]
    meta = i.IndexMetadata('fp1', 2, 2, 'datahash')
    index = i.VectorIndex.build(vectors, rows, meta)
    index.save(tmp_path / 'index')
    loaded = i.VectorIndex.load(tmp_path / 'index', expected_metadata=meta)
    assert loaded.metadata == meta
    with pytest.raises(i.IndexCompatibilityError, match='fingerprint'):
        i.VectorIndex.load(tmp_path / 'index', expected_metadata=i.IndexMetadata('fp2', 2, 2, 'datahash'))
    with pytest.raises(i.IndexCompatibilityError, match='dimensions'):
        i.VectorIndex.load(tmp_path / 'index', expected_metadata=i.IndexMetadata('fp1', 3, 2, 'datahash'))


def test_top_k_is_bounded_by_index_size():
    i = _i()
    index = i.VectorIndex.build(
        np.array([[1., 0.]], dtype=np.float32),
        [{'qid': 'Q1'}],
        i.IndexMetadata('fp', 2, 1, 'hash'),
    )
    hits = index.search(np.array([1., 0.], dtype=np.float32), top_k=100)
    assert len(hits) == 1

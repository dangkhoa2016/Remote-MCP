from __future__ import annotations

from collections.abc import Mapping, Sequence
import numpy as np

MRL_DIMENSIONS = (32, 128, 256, 512, 1024, 2048, 4096)


def _normalize_vector(vector: np.ndarray) -> np.ndarray:
    arr = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(arr))
    if norm == 0.0:
        raise ValueError('zero-norm query vector is not allowed')
    return arr / norm


def _normalize_matrix(matrix: np.ndarray) -> np.ndarray:
    arr = np.asarray(matrix, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError('corpus vectors must be a 2D matrix')
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError('zero-norm corpus vector is not allowed')
    return arr / norms


def rank_vectors(
    query: np.ndarray,
    corpus: np.ndarray,
    ids: Sequence[str],
    top_k: int,
) -> list[tuple[str, float]]:
    if top_k < 1:
        raise ValueError('top_k must be positive')
    matrix = _normalize_matrix(corpus)
    q = _normalize_vector(query)
    if matrix.shape[1] != q.shape[0]:
        raise ValueError('query and corpus dimensions must match')
    if matrix.shape[0] != len(ids):
        raise ValueError('ids and corpus rows must match')
    scores = matrix @ q
    order = sorted(range(len(ids)), key=lambda i: (-float(scores[i]), str(ids[i])))[: min(top_k, len(ids))]
    return [(str(ids[i]), float(scores[i])) for i in order]


def summarize_rank_outcomes(*, expected: Mapping[str, set[str]], rankings: Mapping[str, list[str]]) -> dict:
    ids = list(expected)
    if not ids:
        return {'cases': 0, 'hit_at_1': None, 'hit_at_5': None, 'hit_at_10': None, 'mrr': None}

    def hit_at(k: int) -> float:
        hits = 0
        for case_id in ids:
            if expected[case_id].intersection(rankings.get(case_id, [])[:k]):
                hits += 1
        return hits / len(ids)

    reciprocal = 0.0
    for case_id in ids:
        for rank, item_id in enumerate(rankings.get(case_id, []), 1):
            if item_id in expected[case_id]:
                reciprocal += 1.0 / rank
                break
    return {
        'cases': len(ids),
        'hit_at_1': hit_at(1),
        'hit_at_5': hit_at(5),
        'hit_at_10': hit_at(10),
        'mrr': reciprocal / len(ids),
    }


def topk_overlap(a: Sequence[str], b: Sequence[str], k: int) -> float:
    if k < 1:
        raise ValueError('k must be positive')
    left = set(a[:k])
    right = set(b[:k])
    return len(left.intersection(right)) / k


def code_hit_at_k(rankings: Mapping[str, list[str]], expected: Mapping[str, set[str]], k: int) -> float:
    if not expected:
        return 0.0
    hits = sum(1 for query_id, wanted in expected.items() if wanted.intersection(rankings.get(query_id, [])[:k]))
    return hits / len(expected)

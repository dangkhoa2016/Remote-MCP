from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
import json

import numpy as np


class IndexCompatibilityError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IndexMetadata:
    model_fingerprint: str
    dimensions: int
    row_count: int
    dataset_sha256: str


@dataclass(frozen=True, slots=True)
class SearchHit:
    score: float
    row: dict


def _normalize_rows(vectors: np.ndarray) -> np.ndarray:
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError("vectors must be a 2D matrix")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("zero-norm embedding is not allowed")
    return arr / norms


class VectorIndex:
    def __init__(self, vectors: np.ndarray, rows: list[dict], metadata: IndexMetadata):
        self.vectors = _normalize_rows(vectors)
        self.rows = rows
        self.metadata = metadata
        if len(rows) != self.vectors.shape[0] or metadata.row_count != len(rows):
            raise ValueError("row count does not match vector/index metadata")
        if self.vectors.shape[1] != metadata.dimensions:
            raise ValueError("vector dimensions do not match index metadata")
        self._faiss = None
        try:
            import faiss
            index = faiss.IndexFlatIP(metadata.dimensions)
            index.add(self.vectors)
            self._faiss = index
        except Exception:
            self._faiss = None

    @classmethod
    def build(cls, vectors: np.ndarray, rows: list[dict], metadata: IndexMetadata) -> "VectorIndex":
        return cls(vectors, list(rows), metadata)

    def project(self, dimensions: int) -> "VectorIndex":
        dimensions = int(dimensions)
        if not 32 <= dimensions <= self.metadata.dimensions:
            raise ValueError(
                f"projection dimensions must be between 32 and {self.metadata.dimensions}"
            )
        vectors = _normalize_rows(self.vectors[:, :dimensions])
        metadata = replace(self.metadata, dimensions=dimensions)
        return VectorIndex(vectors, list(self.rows), metadata)

    def search(self, query: np.ndarray, top_k: int) -> list[SearchHit]:
        if top_k < 1:
            raise ValueError("top_k must be positive")
        q = np.asarray(query, dtype=np.float32).reshape(1, -1)
        if q.shape[1] != self.metadata.dimensions:
            raise IndexCompatibilityError("query dimensions do not match index dimensions")
        q = _normalize_rows(q)
        k = min(top_k, len(self.rows))
        if self._faiss is not None:
            scores, indexes = self._faiss.search(q, k)
            pairs = zip(scores[0].tolist(), indexes[0].tolist(), strict=True)
        else:
            scores_all = self.vectors @ q[0]
            order = np.argsort(-scores_all)[:k]
            pairs = ((float(scores_all[idx]), int(idx)) for idx in order)
        return [SearchHit(float(score), self.rows[int(idx)]) for score, idx in pairs if idx >= 0]

    def save(self, path: Path) -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        np.save(path / "vectors.npy", self.vectors)
        (path / "rows.json").write_text(json.dumps(self.rows, ensure_ascii=False), encoding="utf-8")
        (path / "index-metadata.json").write_text(
            json.dumps(asdict(self.metadata), indent=2, sort_keys=True), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: Path, expected_metadata: IndexMetadata) -> "VectorIndex":
        path = Path(path)
        actual = IndexMetadata(**json.loads((path / "index-metadata.json").read_text(encoding="utf-8")))
        if actual.model_fingerprint != expected_metadata.model_fingerprint:
            raise IndexCompatibilityError("model fingerprint mismatch")
        if actual.dimensions != expected_metadata.dimensions:
            raise IndexCompatibilityError("index dimensions mismatch")
        if actual.dataset_sha256 != expected_metadata.dataset_sha256:
            raise IndexCompatibilityError("dataset sha256 mismatch")
        if actual.row_count != expected_metadata.row_count:
            raise IndexCompatibilityError("row count mismatch")
        vectors = np.load(path / "vectors.npy")
        rows = json.loads((path / "rows.json").read_text(encoding="utf-8"))
        return cls(vectors, rows, actual)

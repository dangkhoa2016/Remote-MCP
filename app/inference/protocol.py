from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CudaMemoryStats:
    max_allocated_bytes: int
    max_reserved_bytes: int


@dataclass(frozen=True, slots=True)
class EmbedWork:
    request_id: str
    item_indexes: list[int]
    texts: list[str]
    dimensions: int
    is_query: bool


@dataclass(frozen=True, slots=True)
class EmbedResult:
    request_id: str
    item_indexes: list[int]
    embeddings: list[list[float]]
    token_count: int
    cuda_memory: CudaMemoryStats | None = None


@dataclass(frozen=True, slots=True)
class WorkerReady:
    worker_id: int
    gpu_name: str


@dataclass(frozen=True, slots=True)
class WorkerFailure:
    worker_id: int
    request_id: str | None
    error: str

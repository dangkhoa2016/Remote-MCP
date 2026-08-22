from __future__ import annotations
from dataclasses import dataclass, field
from threading import Lock
from time import perf_counter

from app.inference.protocol import CudaMemoryStats


@dataclass
class Metrics:
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)
    requests_total: int = 0
    requests_failed: int = 0
    rejected_429: int = 0
    worker_batches: dict[int, int] = field(default_factory=dict)
    worker_items: dict[int, int] = field(default_factory=dict)
    queue_cost: dict[int, int] = field(default_factory=dict)
    embedding_latency_sum: float = 0.0
    embedding_latency_count: int = 0
    queue_wait_sum: float = 0.0
    queue_wait_count: int = 0
    worker_failures: dict[int, int] = field(default_factory=dict)
    worker_restarts: dict[int, int] = field(default_factory=dict)
    cuda_max_allocated_bytes: dict[int, int] = field(default_factory=dict)
    cuda_max_reserved_bytes: dict[int, int] = field(default_factory=dict)

    def incr_request(self) -> None:
        with self._lock:
            self.requests_total += 1

    def incr_failed(self) -> None:
        with self._lock:
            self.requests_failed += 1

    def incr_429(self) -> None:
        with self._lock:
            self.rejected_429 += 1

    def set_queue_cost(self, worker_id: int, value: int) -> None:
        with self._lock:
            self.queue_cost[worker_id] = value

    def record_batch(self, worker_id: int, items: int, latency: float, queue_wait: float = 0.0) -> None:
        with self._lock:
            self.worker_batches[worker_id] = self.worker_batches.get(worker_id, 0) + 1
            self.worker_items[worker_id] = self.worker_items.get(worker_id, 0) + items
            self.embedding_latency_sum += latency
            self.embedding_latency_count += 1
            self.queue_wait_sum += queue_wait
            self.queue_wait_count += 1

    def record_worker_failure(self, worker_id: int) -> None:
        with self._lock:
            self.worker_failures[worker_id] = self.worker_failures.get(worker_id, 0) + 1

    def record_cuda_memory(self, worker_id: int, stats: CudaMemoryStats) -> None:
        with self._lock:
            self.cuda_max_allocated_bytes[worker_id] = max(
                self.cuda_max_allocated_bytes.get(worker_id, 0),
                int(stats.max_allocated_bytes),
            )
            self.cuda_max_reserved_bytes[worker_id] = max(
                self.cuda_max_reserved_bytes.get(worker_id, 0),
                int(stats.max_reserved_bytes),
            )

    def snapshot(self) -> dict:
        with self._lock:
            batches = sum(self.worker_batches.values())
            items = sum(self.worker_items.values())
            return {
                "requests_total": self.requests_total,
                "requests_failed": self.requests_failed,
                "rejected_429": self.rejected_429,
                "queue_depth_estimated_tokens": dict(self.queue_cost),
                "batches_per_worker": dict(self.worker_batches),
                "items_per_worker": dict(self.worker_items),
                "average_batch_size": (items / batches) if batches else 0.0,
                "average_embedding_latency_seconds": (
                    self.embedding_latency_sum / self.embedding_latency_count
                    if self.embedding_latency_count
                    else 0.0
                ),
                "average_queue_wait_seconds": (
                    self.queue_wait_sum / self.queue_wait_count
                    if self.queue_wait_count
                    else 0.0
                ),
                "worker_failures": dict(self.worker_failures),
                "worker_restarts": dict(self.worker_restarts),
                "cuda_max_allocated_bytes": dict(self.cuda_max_allocated_bytes),
                "cuda_max_reserved_bytes": dict(self.cuda_max_reserved_bytes),
            }

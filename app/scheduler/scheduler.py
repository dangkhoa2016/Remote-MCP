from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import perf_counter
from uuid import uuid4

from app.config import Settings
from app.inference.protocol import EmbedResult, EmbedWork
from app.metrics import Metrics
from app.scheduler.batching import BatchItem, batch_item_cost, estimate_tokens, split_micro_batches


class QueueFullError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ScheduledEmbeddingResult:
    embeddings: list[list[float]]
    token_count: int


class EmbeddingScheduler:
    def __init__(self, worker_clients, settings: Settings, metrics: Metrics | None = None):
        if not worker_clients:
            raise ValueError("at least one worker is required")
        self.workers = list(worker_clients)
        self.settings = settings
        self.metrics = metrics or Metrics()
        self._queued_costs = [0 for _ in self.workers]
        self._admitted_cost = 0
        self._admission_lock = asyncio.Lock()
        self._worker_locks = [asyncio.Lock() for _ in self.workers]

    async def _admit(self, cost: int) -> None:
        async with self._admission_lock:
            if self._admitted_cost + cost > self.settings.max_queue_estimated_tokens:
                self.metrics.incr_429()
                raise QueueFullError("embedding queue capacity exceeded")
            self._admitted_cost += cost

    async def _release_admission(self, cost: int) -> None:
        async with self._admission_lock:
            self._admitted_cost = max(0, self._admitted_cost - cost)

    async def _reserve_worker(self, cost: int) -> int:
        async with self._admission_lock:
            worker_id = min(range(len(self.workers)), key=lambda i: self._queued_costs[i])
            self._queued_costs[worker_id] += cost
            self.metrics.set_queue_cost(worker_id, self._queued_costs[worker_id])
            return worker_id

    async def _release_worker(self, worker_id: int, cost: int) -> None:
        async with self._admission_lock:
            self._queued_costs[worker_id] = max(0, self._queued_costs[worker_id] - cost)
            self.metrics.set_queue_cost(worker_id, self._queued_costs[worker_id])

    async def embed(self, texts: list[str], dimensions: int, is_query: bool) -> ScheduledEmbeddingResult:
        self.metrics.incr_request()
        items = [BatchItem(i, text, estimate_tokens(text)) for i, text in enumerate(texts)]
        total_cost = sum(item.estimated_tokens for item in items)
        await self._admit(total_cost)

        batches = split_micro_batches(
            items,
            max_items=self.settings.max_batch_items,
            max_estimated_tokens=self.settings.max_batch_estimated_tokens,
        )
        request_id = uuid4().hex
        output: list[list[float] | None] = [None] * len(texts)

        async def run_batch(batch: list[BatchItem]) -> EmbedResult:
            cost = batch_item_cost(batch)
            worker_id = await self._reserve_worker(cost)
            work = EmbedWork(
                request_id=request_id,
                item_indexes=[item.index for item in batch],
                texts=[item.text for item in batch],
                dimensions=dimensions,
                is_query=is_query,
            )
            queued_at = perf_counter()
            try:
                async with self._worker_locks[worker_id]:
                    queue_wait = perf_counter() - queued_at
                    started = perf_counter()
                    try:
                        result = await self.workers[worker_id].submit(work)
                    except Exception:
                        self.metrics.record_worker_failure(worker_id)
                        raise
                    if result.cuda_memory is not None:
                        self.metrics.record_cuda_memory(worker_id, result.cuda_memory)
                    self.metrics.record_batch(
                        worker_id,
                        len(batch),
                        perf_counter() - started,
                        queue_wait=queue_wait,
                    )
                    return result
            finally:
                await self._release_worker(worker_id, cost)

        try:
            try:
                results = await asyncio.gather(*(run_batch(batch) for batch in batches))
            except Exception:
                self.metrics.incr_failed()
                raise

            token_count = 0
            for result in results:
                token_count += result.token_count
                for index, vector in zip(result.item_indexes, result.embeddings, strict=True):
                    output[index] = vector
            if any(vector is None for vector in output):
                self.metrics.incr_failed()
                raise RuntimeError("worker result did not cover every input item")
            return ScheduledEmbeddingResult(
                embeddings=[vector for vector in output if vector is not None],
                token_count=token_count,
            )
        finally:
            await self._release_admission(total_cost)

    def workers_ready(self) -> bool:
        return all(worker.is_alive() and worker.is_ready() for worker in self.workers)

import asyncio
import importlib

import pytest

from app.config import Settings
from app.inference.protocol import EmbedResult


class FakeWorker:
    def __init__(self, worker_id: int, delay: float = 0.0):
        self.worker_id = worker_id
        self.delay = delay
        self.calls = []
        self.alive = True
        self.ready = True

    async def submit(self, work):
        self.calls.append(work)
        if self.delay:
            await asyncio.sleep(self.delay)
        vectors = [[float(self.worker_id), float(i)] for i in work.item_indexes]
        return EmbedResult(work.request_id, work.item_indexes, vectors, token_count=len(work.texts))

    def is_ready(self):
        return self.ready and self.alive

    def is_alive(self):
        return self.alive


def _s():
    return importlib.import_module('app.scheduler.scheduler')


@pytest.mark.asyncio
async def test_scheduler_uses_both_workers_for_multiple_batches():
    s = _s()
    workers = [FakeWorker(0, 0.01), FakeWorker(1, 0.01)]
    settings = Settings(max_batch_items=2, max_batch_estimated_tokens=100, max_queue_estimated_tokens=1000)
    scheduler = s.EmbeddingScheduler(workers, settings)
    result = await scheduler.embed(['a', 'b', 'c', 'd'], 32, False)
    assert len(workers[0].calls) == 1
    assert len(workers[1].calls) == 1
    assert result.embeddings == [[0.0, 0.0], [0.0, 1.0], [1.0, 2.0], [1.0, 3.0]]


@pytest.mark.asyncio
async def test_scheduler_preserves_original_order_across_workers():
    s = _s()
    workers = [FakeWorker(0, 0.02), FakeWorker(1, 0.0)]
    settings = Settings(max_batch_items=1, max_batch_estimated_tokens=100, max_queue_estimated_tokens=1000)
    scheduler = s.EmbeddingScheduler(workers, settings)
    result = await scheduler.embed(['a', 'b'], 32, False)
    assert [vector[1] for vector in result.embeddings] == [0.0, 1.0]


@pytest.mark.asyncio
async def test_scheduler_rejects_when_admission_cost_exceeds_capacity():
    s = _s()
    workers = [FakeWorker(0), FakeWorker(1)]
    settings = Settings(max_batch_items=2, max_batch_estimated_tokens=100, max_queue_estimated_tokens=2)
    scheduler = s.EmbeddingScheduler(workers, settings)
    with pytest.raises(s.QueueFullError):
        await scheduler.embed(['this is much longer than two estimated tokens'], 32, False)

@pytest.mark.asyncio
async def test_scheduler_admission_is_atomic_across_concurrent_requests():
    s = _s()

    class PausingScheduler(s.EmbeddingScheduler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.reserve_calls = 0
            self.first_reserve_entered = asyncio.Event()
            self.release_reservations = asyncio.Event()

        async def _reserve_worker(self, cost: int) -> int:
            self.reserve_calls += 1
            self.first_reserve_entered.set()
            await self.release_reservations.wait()
            return await super()._reserve_worker(cost)

    workers = [FakeWorker(0), FakeWorker(1)]
    settings = Settings(
        max_batch_items=2,
        max_batch_estimated_tokens=100,
        max_queue_estimated_tokens=2,
    )
    scheduler = PausingScheduler(workers, settings)

    first = asyncio.create_task(scheduler.embed(['abcd', 'efgh'], 32, False))
    await scheduler.first_reserve_entered.wait()

    second = asyncio.create_task(scheduler.embed(['ijkl', 'mnop'], 32, False))
    await asyncio.sleep(0.02)

    try:
        assert second.done(), 'second request should be rejected before worker reservation'
        with pytest.raises(s.QueueFullError):
            await second
    finally:
        scheduler.release_reservations.set()
        await first

@pytest.mark.asyncio
async def test_scheduler_records_worker_failures_in_metrics():
    s = _s()

    class FailingWorker(FakeWorker):
        async def submit(self, work):
            raise RuntimeError('gpu worker failed')

    scheduler = s.EmbeddingScheduler(
        [FailingWorker(0)],
        Settings(max_batch_items=2, max_batch_estimated_tokens=100, max_queue_estimated_tokens=100),
    )

    with pytest.raises(RuntimeError, match='gpu worker failed'):
        await scheduler.embed(['hello'], 32, False)

    assert scheduler.metrics.snapshot()['worker_failures'] == {0: 1}


def test_t4_runtime_defaults_encode_live_oom_hardening(monkeypatch):
    monkeypatch.delenv('MAX_BATCH_ESTIMATED_TOKENS', raising=False)
    monkeypatch.delenv('PYTORCH_ALLOC_CONF', raising=False)
    settings = Settings.from_env()
    assert settings.max_batch_estimated_tokens == 512
    assert __import__('os').environ['PYTORCH_ALLOC_CONF'] == 'expandable_segments:True'


@pytest.mark.asyncio
async def test_scheduler_records_cuda_allocator_stats_from_worker():
    s = _s()
    from app.inference.protocol import CudaMemoryStats

    class TelemetryWorker(FakeWorker):
        async def submit(self, work):
            vectors = [[0.0, float(i)] for i in work.item_indexes]
            return EmbedResult(
                work.request_id,
                work.item_indexes,
                vectors,
                token_count=len(work.texts),
                cuda_memory=CudaMemoryStats(111, 222),
            )

    scheduler = s.EmbeddingScheduler(
        [TelemetryWorker(0)],
        Settings(max_batch_items=2, max_batch_estimated_tokens=100, max_queue_estimated_tokens=100),
    )
    await scheduler.embed(['hello'], 32, False)
    snap = scheduler.metrics.snapshot()
    assert snap['cuda_max_allocated_bytes'] == {0: 111}
    assert snap['cuda_max_reserved_bytes'] == {0: 222}


@pytest.mark.asyncio
async def test_workers_ready_turns_false_after_worker_death():
    s = _s()
    workers = [FakeWorker(0), FakeWorker(1)]
    scheduler = s.EmbeddingScheduler(workers, Settings())
    assert scheduler.workers_ready() is True
    workers[1].alive = False
    assert scheduler.workers_ready() is False



@pytest.mark.asyncio
async def test_queue_burst_rejects_one_request_then_recovers_accounting():
    s = _s()

    class GateWorker(FakeWorker):
        def __init__(self, worker_id):
            super().__init__(worker_id)
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.pause_once = True

        async def submit(self, work):
            self.calls.append(work)
            if self.pause_once:
                self.pause_once = False
                self.entered.set()
                await self.release.wait()
            vectors = [[float(self.worker_id), float(i)] for i in work.item_indexes]
            return EmbedResult(work.request_id, work.item_indexes, vectors, token_count=len(work.texts))

    worker = GateWorker(0)
    scheduler = s.EmbeddingScheduler(
        [worker],
        Settings(max_batch_items=1, max_batch_estimated_tokens=10, max_queue_estimated_tokens=1),
    )
    first = asyncio.create_task(scheduler.embed(['abcd'], 32, False))
    await worker.entered.wait()
    assert scheduler._admitted_cost == 1

    with pytest.raises(s.QueueFullError):
        await scheduler.embed(['efgh'], 32, False)

    worker.release.set()
    completed = await first
    assert completed.embeddings
    assert scheduler._admitted_cost == 0

    later = await scheduler.embed(['ijkl'], 32, False)
    assert later.embeddings
    assert scheduler._admitted_cost == 0

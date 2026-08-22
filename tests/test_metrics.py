from app.metrics import Metrics


def test_metrics_exposes_queue_wait_and_worker_failure_counters():
    metrics = Metrics()
    metrics.record_batch(worker_id=0, items=4, latency=0.8, queue_wait=0.2)
    metrics.record_worker_failure(worker_id=1)

    snapshot = metrics.snapshot()

    assert snapshot['average_queue_wait_seconds'] == 0.2
    assert snapshot['worker_failures'] == {1: 1}
    assert snapshot['worker_restarts'] == {}


def test_metrics_keeps_per_worker_cuda_peaks():
    from app.inference.protocol import CudaMemoryStats
    metrics = Metrics()
    metrics.record_cuda_memory(0, CudaMemoryStats(100, 200))
    metrics.record_cuda_memory(0, CudaMemoryStats(150, 180))
    metrics.record_cuda_memory(1, CudaMemoryStats(90, 220))
    snap = metrics.snapshot()
    assert snap['cuda_max_allocated_bytes'] == {0: 150, 1: 90}
    assert snap['cuda_max_reserved_bytes'] == {0: 200, 1: 220}

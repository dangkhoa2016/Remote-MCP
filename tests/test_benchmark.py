
def test_benchmark_summary_reports_items_per_second_and_percentiles():
    from benchmark.benchmark import summarize
    result = summarize([0.1, 0.2, 0.3, 0.4], elapsed=1.0, total_requests=4, total_items=8, concurrency=2, label='dual')
    assert result['throughput_items_per_second'] == 8.0
    assert result['requests_per_second'] == 4.0
    assert result['latency_ms']['p50'] == 250.0
    assert result['worker_mode'] == 'dual'


def test_benchmark_summary_includes_reproducible_workload_identity():
    from benchmark.benchmark import summarize
    result = summarize(
        [0.1, 0.2], elapsed=1.0, total_requests=2, total_items=4,
        concurrency=2, label='dual',
        workload={'items_per_request': 2, 'dimensions': 1024, 'sample_text_sha256': 'abc'},
        errors=0,
    )
    assert result['errors'] == 0
    assert result['workload']['dimensions'] == 1024
    assert len(result['workload_fingerprint']) == 64

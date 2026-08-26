def test_default_matrix_is_curated_and_covers_required_axes():
    from benchmark.matrix import default_matrix
    cases = default_matrix()
    assert 10 <= len(cases) <= 15
    assert {c.worker_count for c in cases} == {1, 2}
    assert {c.dimensions for c in cases} == {1024, 4096}
    assert {1, 4, 8, 16}.issubset({c.items_per_request for c in cases})
    assert {1, 2, 4, 8}.issubset({c.concurrency for c in cases})


def test_summary_excludes_error_cases_from_best_stable():
    from benchmark.matrix import summarize_matrix
    results = [
        {'case_id': 'a', 'worker_count': 1, 'concurrency': 2, 'items_per_request': 8, 'dimensions': 1024, 'requests': 16, 'errors': 0, 'throughput_items_per_second': 25.0, 'latency_ms': {'p95': 500}, 'workload_fingerprint': 'x'},
        {'case_id': 'b', 'worker_count': 1, 'concurrency': 4, 'items_per_request': 16, 'dimensions': 1024, 'requests': 16, 'errors': 1, 'throughput_items_per_second': 99.0, 'latency_ms': {'p95': 900}, 'workload_fingerprint': 'y'},
    ]
    out = summarize_matrix(results)
    assert out['best_stable_single']['case_id'] == 'a'


def test_matched_scaling_uses_per_worker_concurrency_and_same_workload_shape():
    from benchmark.matrix import summarize_matrix
    results = [
        {'case_id': 's', 'worker_count': 1, 'concurrency': 2, 'items_per_request': 8, 'dimensions': 1024, 'requests': 16, 'errors': 0, 'throughput_items_per_second': 25.0, 'latency_ms': {'p95': 500}, 'workload_fingerprint': 'single-fp'},
        {'case_id': 'd', 'worker_count': 2, 'concurrency': 4, 'items_per_request': 8, 'dimensions': 1024, 'requests': 16, 'errors': 0, 'throughput_items_per_second': 49.0, 'latency_ms': {'p95': 520}, 'workload_fingerprint': 'dual-fp'},
    ]
    out = summarize_matrix(results)
    assert out['matched_scaling'][0]['single_case_id'] == 's'
    assert out['matched_scaling'][0]['dual_case_id'] == 'd'
    assert out['matched_scaling'][0]['throughput_ratio'] == 1.96


def test_flattening_requires_under_five_percent_gain_and_higher_p95():
    from benchmark.matrix import summarize_matrix
    results = [
        {'case_id': 'low', 'worker_count': 2, 'concurrency': 4, 'items_per_request': 8, 'dimensions': 1024, 'requests': 16, 'errors': 0, 'throughput_items_per_second': 50.0, 'latency_ms': {'p95': 500}, 'workload_fingerprint': 'a'},
        {'case_id': 'high', 'worker_count': 2, 'concurrency': 8, 'items_per_request': 8, 'dimensions': 1024, 'requests': 24, 'errors': 0, 'throughput_items_per_second': 51.0, 'latency_ms': {'p95': 900}, 'workload_fingerprint': 'b'},
    ]
    out = summarize_matrix(results)
    assert out['flattening'][0]['lower_case_id'] == 'low'
    assert out['flattening'][0]['higher_case_id'] == 'high'

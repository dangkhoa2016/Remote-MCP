def test_workload_fingerprint_is_stable_across_mapping_order():
    from app.qualification.evidence import workload_fingerprint
    a = workload_fingerprint({'requests': 16, 'concurrency': 4, 'dimensions': 1024})
    b = workload_fingerprint({'dimensions': 1024, 'concurrency': 4, 'requests': 16})
    assert a == b


def test_runtime_config_is_allowlist_only():
    from app.qualification.evidence import sanitize_runtime_config
    out = sanitize_runtime_config({'WORKER_COUNT': '2', 'API_KEY': 'secret', 'HF_TOKEN': 'x'})
    assert out['WORKER_COUNT'] == '2'
    assert 'API_KEY' not in out
    assert 'HF_TOKEN' not in out


def test_secret_scanner_reports_only_files_containing_secret(tmp_path):
    from app.qualification.evidence import scan_secret_bytes
    good = tmp_path / 'good.txt'; good.write_text('safe')
    bad = tmp_path / 'bad.txt'; bad.write_text('Bearer s3cr3t')
    assert scan_secret_bytes([good, bad], 's3cr3t') == [bad]


def test_sha256_json_is_unicode_stable_and_canonical():
    from app.qualification.evidence import sha256_json
    assert sha256_json({'b': 'xin chào', 'a': 1}) == sha256_json({'a': 1, 'b': 'xin chào'})
    assert len(sha256_json({'a': 1})) == 64

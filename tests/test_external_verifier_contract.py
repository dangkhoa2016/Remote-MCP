import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_verifier():
    path = ROOT / 'scripts' / 'verify-external-demo.py'
    spec = importlib.util.spec_from_file_location('verify_external_demo', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verify_report_never_stores_raw_tunnel_url_or_key():
    verifier = _load_verifier()
    url = 'https://abc-xyz123.trycloudflare.com'
    key = 'sk-ephemeral-topsecret123'
    report = verifier.build_verify_report(
        url=url,
        checks=verifier.EXPECTED_MATRIX,
        timestamp='2026-08-29T00:00:00Z',
        verifier={'hostname': 'verifier', 'platform': 'linux', 'python': '3.12', 'source': 'test'},
    )
    text = repr(report)
    assert url not in text
    assert key not in text
    assert 'Authorization' not in text
    assert report['tunnel_url_sha256'] == verifier._sha256(url)
    assert report['matrix_status'] == 'PASS'
    assert report['schema_version'] == 1
    assert report['provider'] == 'cloudflare-quick'


def test_verify_report_marks_failed_matrix_truthfully():
    verifier = _load_verifier()
    bad_checks = dict(verifier.EXPECTED_MATRIX)
    bad_checks['ready_valid_auth'] = 401
    report = verifier.build_verify_report(
        url='https://abc.trycloudflare.com', checks=bad_checks,
        timestamp='2026-08-29T00:00:00Z',
        verifier={'hostname': 'x', 'platform': 'linux', 'python': '3.12', 'source': 'test'},
    )
    assert report['matrix_status'] == 'FAIL'


def test_teardown_report_stores_only_sanitized_fields():
    verifier = _load_verifier()
    url = 'https://abc-xyz123.trycloudflare.com'
    report = verifier.build_teardown_report(
        url=url, stale_url_reachable=False, last_http_status=None, retries=10,
        timestamp='2026-08-29T00:00:00Z',
        verifier={'hostname': 'x', 'platform': 'linux', 'python': '3.12', 'source': 'test'},
    )
    text = repr(report)
    assert url not in text
    assert report['tunnel_url_sha256'] == verifier._sha256(url)
    assert report['teardown']['status'] == 'PASS'


def test_teardown_report_flags_live_stale_url():
    verifier = _load_verifier()
    report = verifier.build_teardown_report(
        url='https://abc.trycloudflare.com', stale_url_reachable=True,
        last_http_status=200, retries=10, timestamp='2026-08-29T00:00:00Z',
        verifier={'hostname': 'x', 'platform': 'linux', 'python': '3.12', 'source': 'test'},
    )
    assert report['teardown']['status'] == 'FAIL'

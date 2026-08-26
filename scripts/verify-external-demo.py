#!/usr/bin/env python3
"""External Cloudflare Quick Tunnel verifier.

Run this on a SEPARATE machine (never only the Kaggle host) while the
authenticated Quick Tunnel is active. Proves remote reachability, bearer auth,
and functional embedding/search, then (after the operator stops the tunnel)
proves the stale URL no longer serves a live /health.

Secrets are taken ONLY from environment variables and are never written to the
retained JSON; the JSON stores only tunnel_url_sha256, provider, the HTTP status
codes, teardown status, timestamps, and a verifier environment summary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path

import httpx

QWEN_TUNNEL_URL = 'QWEN_TUNNEL_URL'
QWEN_API_KEY = 'QWEN_API_KEY'

EXPECTED_MATRIX = {
    'health_no_auth': 200,
    'ready_no_auth': 401,
    'ready_wrong_auth': 401,
    'ready_valid_auth': 200,
    'embedding_valid_auth': 200,
    'search_valid_auth': 200,
}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _env_url() -> str:
    url = os.environ.get(QWEN_TUNNEL_URL, '').rstrip('/')
    if not url:
        raise SystemExit(f'{QWEN_TUNNEL_URL} must be set')
    return url


def _env_key() -> str:
    key = os.environ.get(QWEN_API_KEY, '')
    if not key:
        raise SystemExit(f'{QWEN_API_KEY} must be set')
    return key


def verifier_summary() -> dict:
    return {
        'hostname': platform.node() or 'unknown',
        'platform': platform.platform() or 'unknown',
        'python': platform.python_version() or 'unknown',
        'source': os.environ.get('QWEN_VERIFIER_SOURCE', 'external-machine'),
    }


def build_verify_report(*, url: str, checks: dict, timestamp: str, verifier: dict | None = None) -> dict:
    """Assemble the retained verifier JSON. Only the URL hash is ever stored."""
    return {
        'schema_version': 1,
        'provider': 'cloudflare-quick',
        'tunnel_url_sha256': _sha256(url),
        'checks': dict(checks),
        'matrix_status': 'PASS' if dict(checks) == EXPECTED_MATRIX else 'FAIL',
        'verifier': verifier or verifier_summary(),
        'timestamp_utc': timestamp,
    }


def build_teardown_report(*, url: str, stale_url_reachable: bool, last_http_status: int | None,
                          retries: int, timestamp: str, verifier: dict | None = None) -> dict:
    return {
        'schema_version': 1,
        'provider': 'cloudflare-quick',
        'tunnel_url_sha256': _sha256(url),
        'teardown': {
            'status': 'PASS' if not stale_url_reachable else 'FAIL',
            'stale_url_reachable': stale_url_reachable,
            'last_http_status': last_http_status,
            'retries': retries,
        },
        'verifier': verifier or verifier_summary(),
        'timestamp_utc': timestamp,
    }


def _utc_now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def cmd_verify(out: Path, timeout: float) -> int:
    url, key = _env_url(), _env_key()
    checks: dict[str, int] = {}
    with httpx.Client(timeout=timeout) as client:
        checks['health_no_auth'] = client.get(url + '/health').status_code
        checks['ready_no_auth'] = client.get(url + '/ready').status_code
        checks['ready_wrong_auth'] = client.get(
            url + '/ready', headers={'Authorization': 'Bearer definitely-wrong'}).status_code
        checks['ready_valid_auth'] = client.get(
            url + '/ready', headers={'Authorization': f'Bearer {key}'}).status_code
        embedding = client.post(
            url + '/v1/embeddings', headers={'Authorization': f'Bearer {key}'},
            json={'input': ['semantic search qualification'], 'dimensions': 128})
        checks['embedding_valid_auth'] = embedding.status_code
        search = client.post(
            url + '/v1/search', headers={'Authorization': f'Bearer {key}'},
            json={'query': 'Hanoi', 'top_k': 3, 'language': 'en'})
        checks['search_valid_auth'] = search.status_code
    report = build_verify_report(url=url, checks=checks, timestamp=_utc_now())
    _write(out, report)
    ok = report['matrix_status'] == 'PASS'
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if ok else 1


def cmd_teardown(out: Path, retries: int, interval: float, timeout: float) -> int:
    url = _env_url()
    stale_reachable = True
    last_status: int | None = None
    for _ in range(retries):
        try:
            response = httpx.get(url + '/health', timeout=timeout)
            last_status = response.status_code
            stale_reachable = response.status_code == 200
        except Exception:
            stale_reachable = False
            last_status = None
        if not stale_reachable:
            break
        time.sleep(interval)
    report = build_teardown_report(
        url=url, stale_url_reachable=stale_reachable, last_http_status=last_status,
        retries=retries, timestamp=_utc_now())
    _write(out, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not stale_reachable else 1


def _write(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='External Quick Tunnel verifier (run on a separate machine)')
    sub = parser.add_subparsers(dest='command', required=True)
    v = sub.add_parser('verify', help='run the remote auth/embedding/search matrix')
    v.add_argument('--out', type=Path, required=True)
    v.add_argument('--timeout', type=float, default=120.0)
    t = sub.add_parser('teardown', help='verify the stale URL no longer serves /health')
    t.add_argument('--out', type=Path, required=True)
    t.add_argument('--retries', type=int, default=10)
    t.add_argument('--interval', type=float, default=2.0)
    t.add_argument('--timeout', type=float, default=5.0)
    args = parser.parse_args(argv)
    if args.command == 'verify':
        return cmd_verify(args.out, args.timeout)
    return cmd_teardown(args.out, args.retries, args.interval, args.timeout)


if __name__ == '__main__':
    raise SystemExit(main())

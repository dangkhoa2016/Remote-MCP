#!/usr/bin/env python3
"""Secret-aware release artifact scanner.

Inspects archive members (names and text content) inside .zip and .tar.gz,
not just the outer filename, and fails if it finds secret-bearing or cache
members. It prints only offending member names -- never the discovered
secret/token -- and returns a non-zero exit code on any finding.

Scope: secret *files* and *cache members* are detected by member name in every
archive. Actual leaked secret *values* (a real Bearer token or a raw Quick
Tunnel hostname in data) are detected in content of non-source data/log files.
Source code and documentation legitimately reuse these strings as identifiers
(e.g. config key names, test fixtures, format strings), so they are not treated
as leaks; a committed secret FILE is still caught by the member-name check.
"""
from __future__ import annotations

import re
import sys
import tarfile
import zipfile
from pathlib import Path

SECRET_NAME_MARKERS = (
    'api-key',
    'api_key',
    'trycloudflare.com',
    '/secrets/',
    '\\secrets\\',
)

CACHE_NAME_MARKERS = (
    '.pytest_cache',
    '__pycache__',
    '.pyc',
)

# Members with these extensions are treated as source code / documentation and
# are exempt from the content value-scan (they legitimately reference the
# domain, auth scheme, and config key names). They are still subject to the
# member-name checks above.
SOURCE_CONTENT_EXTS = frozenset({
    '.py', '.sh', '.md', '.example', '.ipynb', '.toml', '.cfg', '.yaml', '.yml',
})

BEARER_TOKEN_RE = re.compile(r'Authorization:\s*Bearer\s+[A-Za-z0-9\-._~+/]{8,}')
RAW_TUNNEL_RE = re.compile(r'https?://[a-z0-9][a-z0-9-]{5,}\.trycloudflare\.com\b')


def _iter_members(path: Path):
    """Yield (member_name, bytes_content) for files inside the archive."""
    if path.name.endswith('.zip'):
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                yield info.filename, zf.read(info)
    elif path.name.endswith('.tar.gz') or path.name.endswith('.tgz'):
        with tarfile.open(path, 'r:gz') as tf:
            for member in tf.getmembers():
                if member.isfile():
                    blob = tf.extractfile(member).read() if tf.extractfile(member) else b''
                    yield member.name, blob
                else:
                    yield member.name, b''
    else:
        try:
            yield path.name, path.read_bytes()
        except OSError:
            yield path.name, b''


def _is_cache_member(member: str) -> bool:
    return any(marker in member for marker in CACHE_NAME_MARKERS)


def _is_source_member(member: str) -> bool:
    return Path(member).suffix.lower() in SOURCE_CONTENT_EXTS


def scan_artifact(path: str | Path) -> list[dict]:
    """Return offending members as {member, kind, reason}. Never the raw secret."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    findings: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for name, content in _iter_members(path):
        for marker in SECRET_NAME_MARKERS:
            if marker in name:
                key = (name, marker)
                if key not in seen:
                    seen.add(key)
                    findings.append({'member': name, 'kind': 'secret', 'reason': marker})
        if _is_cache_member(name):
            key = (name, 'cache')
            if key not in seen:
                seen.add(key)
                findings.append({'member': name, 'kind': 'cache', 'reason': 'cache member'})
        if not _is_source_member(name):
            text = content.decode('utf-8', errors='replace')
            if BEARER_TOKEN_RE.search(text):
                key = (name, 'Authorization: Bearer')
                if key not in seen:
                    seen.add(key)
                    findings.append({'member': name, 'kind': 'secret', 'reason': 'Authorization: Bearer'})
            if RAW_TUNNEL_RE.search(text):
                key = (name, 'trycloudflare.com')
                if key not in seen:
                    seen.add(key)
                    findings.append({'member': name, 'kind': 'secret', 'reason': 'trycloudflare.com'})
    return findings


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print('usage: python scripts/scan-release-artifact.py <artifact> [<artifact> ...]', file=sys.stderr)
        return 2
    rc = 0
    for raw in argv:
        target = Path(raw)
        try:
            findings = scan_artifact(target)
        except FileNotFoundError:
            print(f'ERROR: artifact not found: {raw}', file=sys.stderr)
            rc = 2
            continue
        if findings:
            print(f'FAIL {raw}')
            for finding in findings:
                print(f"  {finding['kind']}: {finding['member']}")
            rc = 1
        else:
            print(f'PASS {raw}')
    return rc


if __name__ == '__main__':
    raise SystemExit(main())

"""Public, credential-free bootstrap downloads for the read-only KRW Agent.

Only explicitly enumerated source files are distributed. Never accept paths
from the request or include OAuth state or runtime secrets in the archive.
"""
from __future__ import annotations
import gzip
import hashlib
import io
import os
from functools import lru_cache
from pathlib import Path
import re
import tarfile
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

router = APIRouter(include_in_schema=False)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENT_FILES = (
    'agent/__init__.py',
    'agent/agent.py',
    'agent/worker.py',
    'agent/git_readonly.py',
    'agent/git_write.py',
    'agent/workspace_routes.py',
    'agent/task_runner.py',
    'agent/long_tasks.py',
    'agent/workspace_edit.py',
    'agent/workspace_manage.py',
    'gateway/agent-requirements.txt',
)
SCRIPT_MARKER_SHA = '__KRW_AGENT_BUNDLE_SHA256__'
SCRIPT_MARKER_URL = '__KRW_PUBLIC_ORIGIN__'


@lru_cache(maxsize=1)
def build_agent_bundle() -> tuple[bytes, str]:
    """Create a deterministic gzip tarball from a fixed source allowlist."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w', format=tarfile.USTAR_FORMAT) as tf:
        for source_name in AGENT_FILES:
            data = (PROJECT_ROOT / source_name).read_bytes()
            archive_name = 'agent-requirements.txt' if source_name.startswith('gateway/') else source_name
            item = tarfile.TarInfo(archive_name)
            item.size = len(data)
            item.mtime = 0
            item.uid = item.gid = 0
            item.uname = item.gname = ''
            item.mode = 0o644
            tf.addfile(item, io.BytesIO(data))
    compressed = gzip.compress(out.getvalue(), compresslevel=9, mtime=0)
    return compressed, hashlib.sha256(compressed).hexdigest()


def configured_public_origin() -> str:
    configured = os.environ.get('KRW_MCP_PUBLIC_URL', '')
    parsed = urlsplit(configured)
    # Never reflect an arbitrary Host header into executable shell script.
    if (parsed.scheme != 'https' or parsed.username or parsed.password
            or not re.fullmatch(r'[a-z0-9.-]+(?::[0-9]{2,5})?', parsed.netloc)):
        raise HTTPException(status_code=503, detail='Public HTTPS URL unavailable')
    return f'https://{parsed.netloc}'


@router.get('/setup.sh')
def agent_setup_script() -> Response:
    _, sha = build_agent_bundle()
    template = (PROJECT_ROOT / 'gateway/setup.sh').read_text(encoding='utf-8')
    if template.count(SCRIPT_MARKER_SHA) != 1 or template.count(SCRIPT_MARKER_URL) != 1:
        raise HTTPException(status_code=503, detail='Bootstrap template unavailable')
    script = template.replace(SCRIPT_MARKER_SHA, sha).replace(SCRIPT_MARKER_URL, configured_public_origin())
    return Response(script, media_type='text/x-shellscript; charset=utf-8',
                    headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@router.get('/agent-bundle.tar.gz')
def agent_bundle() -> Response:
    archive, digest = build_agent_bundle()
    return Response(archive, media_type='application/gzip',
                    headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                             'ETag': f'"sha256-{digest}"'})

from __future__ import annotations

import re

QUICK_TUNNEL_RE = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com\b')


def extract_quick_tunnel_url(text: str) -> str | None:
    match = QUICK_TUNNEL_RE.search(text or '')
    return match.group(0) if match else None

#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def main() -> int:
    errors: list[str] = []
    for path in ROOT.rglob("*.md"):
        if ".git" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for raw in LINK.findall(text):
            target = raw.split("#", 1)[0].strip()
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (path.parent / target).resolve()
            try:
                resolved.relative_to(ROOT.resolve())
            except ValueError:
                errors.append(f"{path.relative_to(ROOT)} -> outside repository: {target}")
                continue
            if not resolved.exists():
                errors.append(f"{path.relative_to(ROOT)} -> missing: {target}")
    if errors:
        print("\n".join(f"[FAIL] {e}" for e in errors))
        return 1
    print("[PASS] DOCS_LINKS_VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())

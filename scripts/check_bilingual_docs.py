#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {ROOT / "LICENSE"}
ROOT_DOCS = [ROOT / "README.md", ROOT / "RELEASE_NOTES.md"]
PAIR_DIRS = [ROOT / "docs", ROOT / "dataset", ROOT / ".github"]
SKIP_DIR_NAMES = {"ISSUE_TEMPLATE", "workflows"}


def counterpart(path: Path) -> Path | None:
    if path.name.endswith(".vi.md"):
        return path.with_name(path.name.removesuffix(".vi.md") + ".md")
    if path.suffix == ".md":
        return path.with_name(path.stem + ".vi.md")
    return None


def public_markdown() -> list[Path]:
    result = list(ROOT_DOCS)
    for base in PAIR_DIRS:
        if not base.exists():
            continue
        for path in base.rglob("*.md"):
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            result.append(path)
    return sorted(set(result))


def main() -> int:
    errors: list[str] = []
    for path in public_markdown():
        if path in EXCLUDED:
            continue
        peer = counterpart(path)
        if peer is None or not peer.exists():
            errors.append(f"missing bilingual counterpart: {path.relative_to(ROOT)}")
            continue
        text = path.read_text(encoding="utf-8")
        if "Language / Ngôn ngữ" not in text:
            errors.append(f"missing language switch: {path.relative_to(ROOT)}")
    if errors:
        print("\n".join(f"[FAIL] {e}" for e in errors))
        return 1
    print("[PASS] BILINGUAL_DOCUMENTATION_PAIRING_VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())

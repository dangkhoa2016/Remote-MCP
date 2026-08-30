#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_OWNER = "Đăng Khoa <i.am@dangkhoa.dev>"


def main() -> int:
    errors: list[str] = []

    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    if not license_text.startswith("MIT License"):
        errors.append("LICENSE is not MIT")
    if EXPECTED_OWNER not in license_text:
        errors.append("LICENSE owner/email mismatch")

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if 'license = "MIT"' not in pyproject:
        errors.append("pyproject license is not MIT")
    if 'authors = [{name = "Đăng Khoa", email = "i.am@dangkhoa.dev"}]' not in pyproject:
        errors.append("pyproject author metadata mismatch")

    required = [
        ".github/CODEOWNERS",
        ".github/CODE_OF_CONDUCT.md",
        ".github/CONTRIBUTING.md",
        ".github/SECURITY.md",
        ".github/SUPPORT.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/dependabot.yml",
        ".github/workflows/ci.yml",
        "README.vi.md",
        "RELEASE_NOTES.vi.md",
    ]
    for rel in required:
        if not (ROOT / rel).exists():
            errors.append(f"missing required public file: {rel}")

    if (ROOT / "docs/superpowers").exists():
        errors.append("forbidden public path remains: docs/superpowers")
    tracked = subprocess.check_output(["git", "-C", str(ROOT), "ls-files"], text=True).splitlines()
    if any("/__pycache__/" in f"/{rel}/" or rel.endswith(".pyc") or rel.startswith(".pytest_cache/") for rel in tracked):
        errors.append("tracked cache artifacts remain in repository")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for marker in ("Language / Ngôn ngữ", "actions/workflows/ci.yml/badge.svg", "License-MIT", "Kaggle-T4"):
        if marker not in readme:
            errors.append(f"README header missing marker: {marker}")

    if errors:
        print("\n".join(f"[FAIL] {e}" for e in errors))
        return 1
    print("[PASS] PUBLICATION_POLICY_VALID")
    return 0


if __name__ == "__main__":
    sys.exit(main())

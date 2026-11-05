# Contributing to Remote-MCP

🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](https://github.com/dangkhoa2016/Remote-MCP/blob/main/CONTRIBUTING.vi.md)

Thank you for helping improve Remote-MCP. Changes should be reviewable, narrowly scoped, and safe for a system with authenticated remote workspace access.

## Before proposing a change

1. Read the [English README](README.md) or [Vietnamese README](README.vi.md), and check existing issues.
2. For a defect, include a minimal, sanitized reproduction, expected behavior, actual behavior, and the source version.
3. For a new capability or behavior change, describe the rationale, permission implications, and compatibility risks.
4. Run the automated test suite and relevant syntax checks on a supported Python version.

## Local verification

    python -m pip install -r requirements-dev.txt
    python -m compileall -q agent gateway tests
    bash -n gateway/setup.sh
    python -m pytest -q

The CI workflow tests Python 3.10 and 3.13. Keep test fixtures free of passwords, device tokens, database state, or live cloud credentials.

## Review and release conventions

Use descriptive commit messages that explain the functional change; avoid generic messages such as "fix". Documentation is maintained in English and Vietnamese, with the same feature and safety claims in both. Changes affecting Agent permissions, OAuth, CLI execution, or persistent enrollment require explicit safety review. Do not rewrite or publish Git history without the repository owner's approval.

Security reports must follow [SECURITY.md](SECURITY.md), not public issues.

**Maintainer:** Đăng Khoa <i.am@dangkhoa.dev>.

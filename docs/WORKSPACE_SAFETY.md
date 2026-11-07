# Workspace safety and static checks

🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/WORKSPACE_SAFETY.vi.md)

Remote-MCP 1.0.0 scopes file operations to directories authorized by the Agent owner.

- `file_sha256(device_id, path)` computes a SHA-256 digest of an allowed regular file.
- `write_file(device_id, path, content, expected_sha256=null)` writes UTF-8 text up to 1 MiB, with conflict detection through optional hash preconditions. Existing files may be updated with explicit `overwrite=true`.
- `check_syntax(device_id, path)` parses Python, JSON or TOML without executing project code.

File writes require `KRW_WRITE_ENABLED=1` on the Gateway and `KRW_ALLOW_FILE_WRITES=1` on the Agent. Static checks require `KRW_STATIC_CHECKS_ENABLED=1` and `KRW_ALLOW_STATIC_CHECKS=1` respectively.

Paths must be relative to an authorized workspace. Symlink traversal, sensitive names and unsafe file operations are blocked. Hash preconditions help prevent accidental overwrites but cannot guarantee transactional compare-and-swap against external processes.

**Security:** syntax checks do not execute project code. The separately permissioned test and CLI tools can execute code and are *not* an OS-level sandbox. Use only trusted workspaces.

See [file operations](FILE_OPERATIONS.md), [controlled tasks](CONTROLLED_TASKS.md), and [README](../README.md).

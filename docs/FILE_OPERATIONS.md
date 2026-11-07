# Workspace file operations

🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/FILE_OPERATIONS.vi.md)

The authorized Agent exposes scoped file and directory tools in Remote-MCP 1.0.0.

| Tool | Purpose |
| --- | --- |
| `read_file` | Read UTF-8 text with bounded output |
| `file_sha256` | Hash allowed regular files |
| `write_file` | Create or explicitly overwrite text |
| `edit_file` | Replace an exact text span with conflict checks |
| `search_files` | Search filenames and text inside an authorized workspace |
| `create_directory` | Create a directory, optionally with parents |
| `move_file` | Move a regular UTF-8 text file without silently overwriting |
| `delete_file` | Delete a permitted regular file with optional hash verification |
| `check_syntax` | Parse Python, JSON or TOML without execution |

Current limits: `write_file` up to 1 MiB; `read_file` up to 256 KiB per call; syntax checks up to 1 MiB; `search_files` up to 100 matches over 2,000 files and eight directory levels. Ordinary dotfiles and extensionless source files are supported, except protected names and Git metadata.

Writes require permission on **both** Gateway (`KRW_WRITE_ENABLED=1`) and Agent (`KRW_ALLOW_FILE_WRITES=1`). A fresh Agent installer may enable its default permission settings, but the Gateway opt-in remains independent. Explicit Agent overrides are respected.

File operations use workspace-relative paths, refuse symlink traversal and avoid unintended overwrites. A concurrent filesystem change can still cause a partial move or delete; always inspect operation results.

See [workspace safety](WORKSPACE_SAFETY.md), [Git operations](WORKSPACE_GIT_OPERATIONS.md) and [README](../README.md).

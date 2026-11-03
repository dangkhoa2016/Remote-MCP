# Phase 5 — Flexible Workspace File Tools (v0.6.0)

Phase 5 adds five tools without enabling remote shell execution or Git writes.

| Tool | Purpose |
|---|---|
| `edit_file` | Replace an exact text span; optionally require a SHA-256 match |
| `search_files` | Search filenames and text across nested workspace folders |
| `create_directory` | Create a directory, with optional missing parents |
| `move_file` | Move one UTF-8 text file; never silently overwrite destination |
| `delete_file` | Delete one regular text file; optional SHA-256 check |

The previous `write_file`, `read_file`, `file_sha256` and `check_syntax` remain available.

## Limits and behavior

- `write_file`: up to 1 MiB of UTF-8 text per call (previously 16 KiB). For an existing file, supply `overwrite=true` to update without manually obtaining a hash, or provide `expected_sha256` for conflict detection.
- `read_file`: up to 256 KiB returned per call (default still 8 KiB).
- Existing-file hash: up to 2 MiB. Syntax checking: up to 1 MiB.
- `search_files`: at most 100 results, 2,000 scanned files and 8 directory levels per call.
- Ordinary dotfiles (such as `.gitignore`) and extensionless text files (such as `Gemfile`) are supported. Secret-like names and `.git` stay unavailable.
- `edit_file` defaults to exactly one match. When editing, it internally checks the file's SHA-256 to avoid an unnoticed overwrite; callers usually need not supply it.
- `move_file` copies a source to a new destination and then deletes the source. If deletion fails, it attempts to remove the new copy; report any partial result to the user.
- Do not use these tools for binary files. Do not assume an operation succeeds until its result is verified.
- Operations remain scoped to the authorized device workspace; traversal and symlink escapes are blocked.

## Enabling and upgrading

On Render, set `KRW_WRITE_ENABLED=1` to enable write/move/delete actions.
On each Agent, set `KRW_ALLOW_FILE_WRITES=1`. Existing Phase 4-C write flags can be reused.
`search_files` is read-only and requires no write permission.
After deploying the Gateway, stop the existing Agent and rerun the verified installer. It reuses your existing owner-owned local Agent configuration (device ID, token, workspace, and file-write/static-check flags); no re-entry is needed. Then refresh ChatGPT tool discovery. Do not run commands from an unreviewed installer.

## Deployment gate

Open the Phase 5 pull request and require both Python 3.10 and 3.13 regression jobs to PASS before merging. Then verify on an authorized test workspace before using real project files.

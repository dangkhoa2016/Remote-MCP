# Phase 4-C — limited workspace write and static checks

**Status:** Feature branch only; opt-in required on both Render and Agent. Do not enable until all tests pass.

New MCP tools:

- `file_sha256(device_id, path)`: read SHA-256 of an allowed regular file (max 256 KiB).
- `write_file(device_id, path, content, expected_sha256=null)`: create one allowed UTF-8 text file (max 16 KiB), or update one existing file when `expected_sha256` equals its current SHA-256. No delete, append, chmod or directory creation.
- `check_syntax(device_id, path)`: parse Python, JSON or TOML; **does not execute project code**.

Both Render and Agent deny edits by default. Opt-in requires `KRW_WRITE_ENABLED=1` on Render AND `KRW_ALLOW_FILE_WRITES=1` on Agent. Static checks separately require `KRW_STATIC_CHECKS_ENABLED=1` on Render AND `KRW_ALLOW_STATIC_CHECKS=1` on Agent. Update the private Agent config at `~/.config/krw-agent/agent.env`, then restart Agent. Bootstrap always initializes these flags as zero. Gateway defaults to zero.

Path safety: relative only, existing non-symlink parents, allowlisted extensions, no hidden/secret names, no hard-linked updates, descriptor-relative `O_NOFOLLOW` with atomic replacement and best-effort hash precondition. The read-only SHA-256 tool does not disclose source text. Never expose an entire home directory or `/content` as workspace.

IMPORTANT: hash preconditions prevent most accidental overwrites, but cannot guarantee transactional compare-and-swap against simultaneous processes outside the Agent. Do not edit the same file concurrently from other processes.

`execute_command` remains hard-disabled; this phase deliberately does not offer `pytest`, arbitrary commands, Git writes, or runtime test execution. Python tests can execute arbitrary code and are **not sandboxed** merely by command allowlisting. Use the remote syntax checker for non-executing validation until an isolated test runner is designed.

Deployment verification: run `python3 -m pytest -q` on the feature branch and verify `python3 -m compileall -q agent gateway` plus `bash -n gateway/setup.sh`. Merge only after passing. On Render keep `KRW_COMMANDS_ENABLED=0`.

# Khoa Remote Workspace — MCP Gateway for authorized workspaces

A private OAuth-protected MCP Gateway hosted on Render, with outbound-only device Agents. The Gateway and OAuth frontend use public HTTPS; the MCP backend and Agent Relay remain bound to localhost inside the Render container.

**Development release:** Phase 6.1 (v0.7.1) improves safe Git branch switching with nonconflicting untracked files and enforces disjoint named workspace roots. A Gateway deploy and Agent update are required before these changes are live; verify with `health_check`.

## Connect an Agent (Linux / Google Colab)

Download and review the installer before running it:

```bash
curl -fsSLo setup.sh https://remote-mcp-ka1p.onrender.com/setup.sh
bash -n setup.sh
less setup.sh
bash setup.sh
```

For a trusted server, the equivalent one-liner is:

```bash
wget -qO- https://remote-mcp-ka1p.onrender.com/setup.sh | bash
```

You must provide a registered device ID/token and an existing dedicated workspace directory. Never use `/content`, `$HOME`, or a directory containing secrets as the workspace. The token is stored outside the workspace at `~/.config/krw-agent/agent.env` (mode 0600). Restart later using `~/.local/share/krw-agent/start.sh`. Agent source archives are SHA-256 verified before installation.

## Available capabilities

- Read device information, list permitted workspace directories, and read UTF-8 source files.
- Read-only Git status, per-file diff and commit log on a real in-workspace Git repository.
- Phase 4-C: `file_sha256`, `write_file` (up to 1 MiB), and non-executing `check_syntax` for Python, JSON and TOML.
- Phase 5: `edit_file`, `search_files`, `create_directory`, `move_file` and `delete_file`. Read up to 256 KiB per call; normal dotfiles and extensionless UTF-8 source files are supported.
- Phase 6: `list_workspaces` and optional `workspace_id` on existing file/Git actions, `move_directory`, `delete_directory`, `git_branches`, `git_stage`, `git_unstage`, `git_commit`, `git_branch_create`, `git_branch_switch`, and `git_push`.
- Phase 6.1: `git_branch_switch` preserves safe untracked files but refuses tracked/staged changes and untracked collisions; named workspace roots must not overlap or alias each other.
- `execute_command` stays disabled. Git write and Git push are separately opt-in, disabled by default; arbitrary shell and force push are not exposed.

File and directory writes require *both* Render and Agent flags (`KRW_WRITE_ENABLED=1` and `KRW_ALLOW_FILE_WRITES=1`). Git writes have separate flags (`KRW_GIT_WRITES_ENABLED=1`, `KRW_ALLOW_GIT_WRITES=1`), while push requires additional opt-in and an Agent-side token. Read [Phase 6](docs/PHASE6_EN.md) for setup and permission details.

## Deployment & verification

The existing Docker deployment uses public port `8765` for OAuth and MCP; loopback Relay `8766` and MCP backend `8767`. OAuth SQLite persists at `/data/krw/oauth.sqlite`. Credentials belong only in runtime environment settings or private Agent configuration; never commit credentials or SQLite.

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
python3 -m compileall -q agent gateway
bash -n gateway/setup.sh
```

Further details: [Deployment guide](DEPLOY_EN.md), [Agent bootstrap](docs/AGENT_BOOTSTRAP_EN.md), [Phase 4-C](docs/PHASE4C_EN.md), [Phase 5](docs/PHASE5_EN.md), [Phase 6](docs/PHASE6_EN.md). The original Northflank deployment guide is kept for historical context; the current service runs on Render.

# Khoa Remote Workspace — MCP Gateway for authorized workspaces

A private OAuth-protected MCP Gateway hosted on Render, with outbound-only device Agents. The Gateway and OAuth frontend use public HTTPS; the MCP backend and Agent Relay remain bound to localhost inside the Render container.

**Development release:** Phase 5 (v0.6.0) adds workspace search, targeted edits and file management, with higher text read/write limits. This branch is not live until the Render Gateway and device Agent are updated. Verify the deployed version with `health_check`.

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
- `execute_command` stays disabled. Git is still read-only; shell execution and Git writes are outside this release.

Workspace writes require *both* Render and Agent opt-in flags (`KRW_WRITE_ENABLED=1` and `KRW_ALLOW_FILE_WRITES=1`). Search is read-only. See [Phase 5](docs/PHASE5_EN.md) for the new tools and [Phase 4-C](docs/PHASE4C_EN.md) for the existing SHA-256 mechanism.

## Deployment & verification

The existing Docker deployment uses public port `8765` for OAuth and MCP; loopback Relay `8766` and MCP backend `8767`. OAuth SQLite persists at `/data/krw/oauth.sqlite`. Credentials belong only in runtime environment settings or private Agent configuration; never commit credentials or SQLite.

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
python3 -m compileall -q agent gateway
bash -n gateway/setup.sh
```

Further details: [Deployment guide](DEPLOY_EN.md), [Agent bootstrap](docs/AGENT_BOOTSTRAP_EN.md), [Phase 4-C](docs/PHASE4C_EN.md), [Phase 5](docs/PHASE5_EN.md). The original Northflank deployment guide is kept for historical context; the current service runs on Render.

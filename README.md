# Khoa Remote Workspace — MCP Gateway for authorized workspaces

A private OAuth-protected MCP Gateway hosted on Render, with outbound-only device Agents. The Gateway and OAuth frontend use public HTTPS; the MCP backend and Agent Relay remain bound to localhost inside the Render container.

**Production:** Phase 4-B (v0.4.0), read-only access. **Proposed:** Phase 4-C (v0.5.0), opt-in text edits and *non-executing* syntax checks; do not enable until the PR regression suite passes.

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
- Phase 4-C proposal: bounded `file_sha256`, `write_file` and `check_syntax` for Python, JSON and TOML.
- `execute_command` remains disabled; the gateway does **not** expose arbitrary shell, `pytest`, deletion, Git writes or execution of project code.

Phase 4-C requires *both* Render and Agent opt-in flags. See [Phase 4-C security details](docs/PHASE4C_EN.md) before enabling. Writes are off by default.

## Deployment & verification

The existing Docker deployment uses public port `8765` for OAuth and MCP; loopback Relay `8766` and MCP backend `8767`. OAuth SQLite persists at `/data/krw/oauth.sqlite`. Credentials belong only in runtime environment settings or private Agent configuration; never commit credentials or SQLite.

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q
python3 -m compileall -q agent gateway
bash -n gateway/setup.sh
```

Further details: [Deployment guide](DEPLOY_EN.md), [Agent bootstrap](docs/AGENT_BOOTSTRAP_EN.md), [Phase 4-C](docs/PHASE4C_EN.md). The original Northflank deployment guide is kept for historical context; the current service runs on Render.

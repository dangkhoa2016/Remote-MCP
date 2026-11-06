# Remote-MCP — Deployment on Render

🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](https://github.com/dangkhoa2016/Remote-MCP/blob/main/DEPLOY.vi.md)

Remote-MCP runs an OAuth-protected Gateway on Render and outbound-only Agent connections. The former Northflank/Codespaces installation procedure is retired and must not be applied to the current repository.

## Deployment architecture

- Deploy the root `Dockerfile` from branch `main`. Public HTTPS reaches the Gateway frontend on container port 8765.
- The Agent Relay on port 8766 and MCP backend on port 8767 must remain bound to loopback; do not expose these ports.
- Keep OAuth login credentials, signing keys, Agent credentials and Relay tokens in protected runtime configuration, never in Git.
- Configure your actual public host and ChatGPT OAuth callback accurately. Use your own Gateway HTTPS origin. `https://gateway.example.com` is only a placeholder. Set `KRW_MCP_PUBLIC_URL` to your real HTTPS URL ending in `/mcp`.

## Storage and device enrollment

The OAuth and device-enrollment SQLite databases must live on storage that survives container replacement for persistent sessions and device approvals. A writable `/data/krw` directory is not proof of a mounted persistent disk; check `enrollment_separate_mount_detected` and verify state after a fresh deployment. Render free compute may not support disk attachments.

To connect an Agent, review the served `/setup.sh` installer, run it on a trusted machine, then approve its one-time terminal code on the `/devices` page of your Gateway. Preserve the Agent's Device ID and credentials across restarts, outside the authorized workspace.

## Validation

Run `python3 -m pip install -r requirements-dev.txt` and `python3 -m pytest -q`. Check `/health`, OAuth discovery, authenticated MCP access and device reconnect. Confirm that anonymous requests cannot reach protected tools.

See [README](README.md), [Agent bootstrap](docs/AGENT_BOOTSTRAP.md) and [release readiness](docs/RELEASE_READINESS.md).

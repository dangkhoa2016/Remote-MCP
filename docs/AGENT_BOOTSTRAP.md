# Remote-MCP — Agent bootstrap on Linux / Google Colab

🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/AGENT_BOOTSTRAP.vi.md)

The Gateway serves `/setup.sh` and `/agent-bundle.tar.gz`. Each deployment has its **own** HTTPS hostname. This repository deliberately does not publish the maintainer's live Gateway origin.

## Installation

Replace `https://gateway.example.com` with the HTTPS origin of **your own Gateway**. The shown domain is an example only, not a running service.

```bash
export REMOTE_MCP_GATEWAY_URL="https://gateway.example.com"
curl -fsSLo setup.sh "$REMOTE_MCP_GATEWAY_URL/setup.sh"
bash -n setup.sh
less setup.sh
bash setup.sh
```

Inspect the downloaded script before execution. Do not pipe unreviewed content into a shell.

## Device enrollment and reconnect

When enrollment is enabled, a new Agent generates a Device ID and credential; approve the one-time terminal code using the `/devices` page of **your Gateway**. The Agent must have an authorized, dedicated workspace. Existing credentials are reused when present.

Private Agent credentials live at `~/.config/krw-agent/agent.env` (mode `0600`) **outside** the exposed workspace. Agent source and Python environment are under `~/.local/share/krw-agent`. Restart using `~/.local/share/krw-agent/start.sh`.

The installer SHA-256 checks the allowlisted Agent bundle. Colab shutdown/reset can disconnect the device and may erase its identity. Do not publish tokens, pairing codes or credentials in URLs, Git, notebooks or workspace files.

See [device enrollment](DEVICE_ENROLLMENT.md), [deployment](../DEPLOY.md) and [README](../README.md).

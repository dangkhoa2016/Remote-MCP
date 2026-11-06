# Remote-MCP — Authentication and device access

🌐 Language / Ngôn ngữ: **English** | [Tiếng Việt](https://github.com/dangkhoa2016/Remote-MCP/blob/main/docs/README.vi.md)

Remote-MCP is an OAuth-protected MCP Gateway for authorized workspaces. Start with [README](../README.md) and the current [Render deployment guide](../DEPLOY.md). Older Cloudflare Tunnel and Codespaces migration commands are no longer valid installation instructions.

## Authentication

ChatGPT uses OAuth authorization code with PKCE; the owner signs in using configured local username and password. The public frontend handles `/authorize`, `/token` and `/mcp`. Relay and backend ports are loopback-only. Login and device administration share the same responsive UI. Username whitespace is removed on submission and by the server; passwords are not transformed.

## Device enrollment

Install an authorized Agent on a trusted machine using the Gateway's `/setup.sh`, then open the `/devices` page on your Gateway and approve the one-time pairing code shown in its terminal. Each device has independent credentials that must be kept outside the authorized workspace.

Do not commit credentials or SQLite state. Validate device reconnect, permissions and OAuth boundaries. See [Agent bootstrap](AGENT_BOOTSTRAP.md) and [release readiness](RELEASE_READINESS.md).

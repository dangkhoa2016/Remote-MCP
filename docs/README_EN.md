# Khoa Remote Workspace Phase 3.1 — Self-hosted username/password

This update removes Auth0 and adds a one-owner login page on the same Cloudflare Tunnel endpoint. ChatGPT's custom MCP UI does **not** directly pass HTTP Basic credentials. Instead, ChatGPT uses OAuth authorization-code + PKCE with a pre-registered client ID/secret; the person signs in with only a local username and password.

## Existing Phase 2 deployment

Keep your existing `.env.dev`, Relay `:8766` and Device Agent. Stop only the old MCP process before applying the ZIP into the project root:

```bash
cd /workspaces/khoa-remote-workspace-phase2
cp gateway/server.py /tmp/krw-server-before-local-login.py
python3 -m zipfile -e /path/to/khoa-remote-workspace-phase3-local-login.zip .
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

The ZIP excludes credentials, `.env.dev` and OAuth state.

## Setup

1. In [ChatGPT Plugins](https://chatgpt.com/plugins), choose **Add custom MCP server** and authentication **OAuth**. Find the exact callback/redirect URI that ChatGPT displays for this connection. Prefer static OAuth Client ID and Client Secret rather than DCR/CIMD. Do not guess the callback URI.
2. In Codespaces, run:

```bash
.venv/bin/python scripts/setup_local_login.py \
  --mcp-url 'https://outline-worm-orange-violation.trycloudflare.com/mcp' \
  --redirect-uri 'EXACT_CHATGPT_CALLBACK_URI' \
  --username 'krwadmin'
```

3. Supply a new 16+ character password through the hidden prompt. The script creates scrypt hashes and random OAuth secrets in `.env.dev`, preserving the existing Relay/Agent tokens.
4. Read `KRW_OAUTH_CLIENT_ID` and `KRW_OAUTH_CLIENT_SECRET` **locally** from `.env.dev` and enter them in ChatGPT's static OAuth credential fields. The authorization endpoint is `https://HOST/authorize`; the token endpoint is `https://HOST/token`; scope `krw:read`. Do not paste credentials into chats.
5. Run `./scripts/run_mcp.sh`. This starts the self-hosted login/OAuth frontend on loopback `:8765` and the MCP SDK backend on loopback `:8767`. Keep the existing Cloudflare Tunnel pointing at **`:8765` only**.
6. Verify GET `https://HOST/.well-known/oauth-authorization-server` returns metadata and POST `https://HOST/mcp` without a bearer token returns **401** (not 200). Connect the plugin and sign in with your username/password.
7. Verify `health_check` first. After real authentication tests, enable **read-only** device tools using `KRW_MCP_TOOLS_ENABLED=1` and restart only MCP. Commands remain hard-disabled in this release.

If Quick Tunnel changes hostname, stop MCP and run `python scripts/update_cloudflare_host.py --mcp-url 'https://NEW_HOST/mcp'` to change URL, invalidate stored grants, restart, update plugin and sign in again. A named Cloudflare Tunnel is recommended for stable URLs.

## Security limitations

This minimal identity server is not production ready: no independent security audit, MFA, or resilient distributed rate limiting. It supports one configured ChatGPT client, exact callback matching, a single read scope, scrypt passwords, 15-minute signed access tokens, PKCE S256 and one-time authorization codes with refresh rotation. It does not provide an arbitrary shell. Keep the workspace root restricted to non-sensitive test files and do not publish `.env.dev`/`.krw-local-state/`.

**Verification status (2026-11-02):** LIVE PASS for ChatGPT custom MCP OAuth, `health_check`, `list_capabilities`, `list_devices`, `get_device_info`, `list_directory` and `read_file` on Codespaces. Remote command execution remains hard-disabled; these checks do not establish production security.

**Phase 4-A safety note:** `agent_quick_tunnel.sh` and `run_ingress.sh` are quarantined because their legacy `:8767` target conflicts with the private MCP backend. Only tunnel the MCP frontend `127.0.0.1:8765`. Full CSRF/OAuth hardening and multi-network ingress require a separate audited change.

# Deploy Khoa Remote Workspace to Northflank

2026-11-02 — **development deployment**, not a production security certification. This kit preserves the Phase 3.1 local-login OAuth flow and Phase 4-A hardening.

1. Extract this kit to `/tmp/krw-northflank-kit` on Codespaces. Prepare an **isolated copy**:

   ```bash
   python3 /tmp/krw-northflank-kit/prepare_deploy_tree.py \
      --source /workspaces/khoa-remote-workspace-phase2 \
      --dest /workspaces/krw-northflank-release-20261102
   cd /workspaces/krw-northflank-release-20261102
   /workspaces/khoa-remote-workspace-phase2/.venv/bin/python -m pytest -q
   ```

   The tool refuses unfamiliar baselines and never modifies the live source. Review `git status --short` and never commit `.env.dev`, SQLite, or secrets.

2. Create a new **private** GitHub repo `khoa-remote-workspace`; commit and push the prepared tree. Connect the GitHub repo to Northflank.
3. Create a Northflank Project (Asia Southeast region if available), then one **Combined Service** using root `Dockerfile`, one instance and resources adequate for three Python processes (start with ~1 GiB and adjust for OOM).
4. Configure only **port 8765 / HTTP / Public**. Northflank terminates HTTPS. Do not expose 8766/8767.
5. Attach a persistent **Single Read/Write** volume at **`/data/krw`**. Docker runs as uid/gid `10001:10001`. If volume permission errors arise, fix ownership on the mount.
6. Attach a verified custom domain such as `mcp.dangkhoa.dev` to the public port. Follow the TXT/CNAME records Northflank displays; don't guess them.
7. Set these **runtime variables** (not Docker build args):

   ```env
   KRW_OAUTH_ENABLED=1
   KRW_MCP_TOOLS_ENABLED=1
   KRW_COMMANDS_ENABLED=0
   KRW_RELAY_URL=http://127.0.0.1:8766
   KRW_AUTH_DB_PATH=/data/krw/oauth.sqlite
   KRW_MCP_PUBLIC_URL=https://mcp.dangkhoa.dev/mcp
   KRW_MCP_PUBLIC_HOST=mcp.dangkhoa.dev
   ```

   Copy **existing** values for `KRW_LOGIN_USERNAME`, `KRW_LOGIN_PASSWORD_HASH`, `KRW_LOGIN_SALT`, `KRW_OAUTH_CLIENT_ID`, `KRW_OAUTH_CLIENT_SECRET`, `KRW_OAUTH_SIGNING_KEY`, `KRW_OAUTH_REDIRECT_URI`, `KRW_CONTROL_TOKEN`, `KRW_DEVICE_TOKENS_JSON` into Northflank Runtime Secrets privately. The registered ChatGPT OAuth callback must be exact. Do not put `KRW_AGENT_TOKEN` or `KRW_WORKSPACE_ROOT` in the server; they belong on the agent.
8. Configure a **TCP health check on port 8765** (avoids Host-header mismatch before custom domain is ready). Verify public `/.well-known/oauth-authorization-server` returns 200, `/health` returns 200, anonymous POST `/mcp` returns 401, and `/v1/control/devices` returns 404. Check `python scripts/check_mcp_discovery.py` via the Northflank container console.
9. On Codespaces, stop the **old Agent**. Start the same Agent with its original local secrets and an **outbound** HTTPS URL to the Northflank domain (without `/mcp`):

   ```bash
   cd /workspaces/khoa-remote-workspace-phase2
   set -a; source .env.dev; set +a
   KRW_COMMANDS_ENABLED=0 KRW_RELAY_URL='https://mcp.dangkhoa.dev' \
     .venv/bin/python -m agent.agent
   ```

   Check the Northflank-side `python scripts/check_devices.py` reports `local-dev` online. To roll back, stop the new Agent and run `./scripts/run_agent.sh` on Codespaces.
10. Update the ChatGPT custom MCP URL to `https://mcp.dangkhoa.dev/mcp` (or create a separate test plugin if the URL can't be changed). Reconnect through local-login OAuth and verify `health_check`, `list_devices`, `read_file` end-to-end before shutting off the old Cloudflare tunnel.

**Cautions:** This is still a dev setup. SQLite WAL requires real volume compatibility testing; Single R/W prevents replicas > 1 and will terminate the existing pod before replacement. Test restart persistence and a consistent SQLite backup. Do not enable remote commands or file write. OAuth `Origin: null` and general security hardening remain separate pending work.

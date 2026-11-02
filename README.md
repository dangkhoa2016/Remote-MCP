# Khoa Remote Workspace — Northflank deployment

This deploys the **existing Phase 4-A verified code** to one Northflank Combined Service without changing the original Codespaces workspace. It preserves the local username/password OAuth design and SQLite. It does **not** enable arbitrary commands or file writing.

- One public HTTPS port: `8765` with OAuth, MCP and a restricted agent ingress (`register`, `poll`, `result`).
- Private, localhost-only MCP backend `8767` and Relay `8766`.
- SQLite path `/data/krw/oauth.sqlite` on a single R/W persistent volume.
- Runtime-only secrets; never commit `.env.dev`, tokens, keys, DB or backups.

See `DEPLOY_EN.md` for detailed instructions. This kit does not modify live source: `prepare_deploy_tree.py` creates a fresh deploy directory. The prepared directory must pass tests before deploying to Northflank. Old source files remain untouched.

## Quick prepare (on Codespaces)

```bash
python3 /tmp/krw-northflank-kit/prepare_deploy_tree.py \
  --source /workspaces/khoa-remote-workspace-phase2 \
  --dest /workspaces/krw-northflank-release-20261102
cd /workspaces/krw-northflank-release-20261102
/workspaces/khoa-remote-workspace-phase2/.venv/bin/python -m pytest -q
```

Follow deployment instructions, configure secrets in Northflank, mount the volume, and connect the device agent after verification.

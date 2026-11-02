#!/usr/bin/env bash
set -euo pipefail
cd /app

# Abort if required secrets or persistence are missing; don't print credentials.
python - <<'PY'
import os,sys
from pathlib import Path
needed = ('KRW_OAUTH_ENABLED','KRW_MCP_TOOLS_ENABLED','KRW_COMMANDS_ENABLED',
 'KRW_MCP_PUBLIC_URL','KRW_LOGIN_USERNAME','KRW_LOGIN_SALT',
 'KRW_LOGIN_PASSWORD_HASH','KRW_OAUTH_CLIENT_ID','KRW_OAUTH_CLIENT_SECRET',
 'KRW_OAUTH_SIGNING_KEY','KRW_OAUTH_REDIRECT_URI',
 'KRW_CONTROL_TOKEN','KRW_DEVICE_TOKENS_JSON','KRW_AUTH_DB_PATH')
missing = [x for x in needed if not os.getenv(x)]
if missing: sys.exit('Missing required runtime env variable(s): '+', '.join(missing))
if os.getenv('KRW_COMMANDS_ENABLED') != '0': sys.exit('Commands must remain OFF')
if os.getenv('KRW_OAUTH_ENABLED') != '1': sys.exit('OAuth must remain ON')
if os.getenv('KRW_MCP_TOOLS_ENABLED') != '1': sys.exit('Device reads must remain ON')
if os.getenv('KRW_AUTH_DB_PATH') != '/data/krw/oauth.sqlite':sys.exit('Set KRW_AUTH_DB_PATH=/data/krw/oauth.sqlite')
if os.getenv('KRW_RELAY_URL','http://127.0.0.1:8766').rstrip('/') != 'http://127.0.0.1:8766':
    sys.exit('The Northflank gateway must relay only over localhost')
if not Path('/data/krw').is_dir() or not os.access('/data/krw',os.W_OK):
    sys.exit('Persistent volume /data/krw is not mounted/writable')
PY

python -m uvicorn gateway.relay:app --host 127.0.0.1 --port 8766 &
RELAY_PID=$!
python -m gateway.server &
MCP_PID=$!
python -m uvicorn gateway.local_auth:app --host 0.0.0.0 --port 8765 &
FRONTEND_PID=$!
cleanup() {
  trap - EXIT TERM INT
  kill "$FRONTEND_PID" "$MCP_PID" "$RELAY_PID" 2>/dev/null || true
  wait "$FRONTEND_PID" "$MCP_PID" "$RELAY_PID" 2>/dev/null || true
}
trap cleanup EXIT TERM INT
wait -n "$FRONTEND_PID" "$MCP_PID" "$RELAY_PID"
echo 'KRW subprocess exited; terminating all and exiting non-zero' >&2
exit 1

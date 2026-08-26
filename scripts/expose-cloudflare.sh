#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
WORKING_DIR="${WORKING_DIR:-/kaggle/working/qwen3-embedding-8b-t4x2}"
STATE_DIR="${CLOUDFLARE_STATE_DIR:-$WORKING_DIR/cloudflare}"
PID_FILE="$STATE_DIR/cloudflared.pid"
LOG_FILE="$STATE_DIR/cloudflared.log"
URL_FILE="$STATE_DIR/tunnel-url.txt"
STATUS_FILE="$STATE_DIR/status.json"
AUTH_CURL_CONFIG="$STATE_DIR/auth-curl.conf"
LOCAL_URL="${LOCAL_URL:-http://127.0.0.1:${PORT:-8000}}"
API_KEY_FILE="${API_KEY_FILE:-$WORKING_DIR/secrets/api-key}"

mkdir -p "$STATE_DIR"

read_api_key() {
  if [[ -n "${API_KEY:-}" ]]; then
    printf '%s' "$API_KEY"
    return 0
  fi
  if [[ -r "$API_KEY_FILE" ]]; then
    tr -d '\r\n' < "$API_KEY_FILE"
    return 0
  fi
  return 1
}

http_code() {
  local out="$1"; shift
  curl -sS -o "$out" -w '%{http_code}' "$@"
}

write_status() {
  local state="$1" pid="${2:-}" url="${3:-}" timestamp
  timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  python - "$STATUS_FILE" "$state" "$pid" "$url" "$timestamp" <<'PY'
import json, sys
path, state, pid, url, ts = sys.argv[1:]
out = {'state': state, 'updated_at_utc': ts}
if pid:
    out['pid'] = int(pid)
if url:
    out['url'] = url
if state == 'running':
    out['started_at_utc'] = ts
elif state == 'stopped':
    out['stopped_at_utc'] = ts
open(path, 'w', encoding='utf-8').write(json.dumps(out, indent=2, sort_keys=True) + '\n')
PY
}

start_tunnel() {
  [[ "${EXPOSE_MODE:-off}" == "cloudflare-quick" ]] || { echo "ERROR: EXPOSE_MODE=cloudflare-quick is required" >&2; exit 2; }
  command -v cloudflared >/dev/null 2>&1 || { echo "ERROR: cloudflared executable not found" >&2; exit 2; }
  local key
  key="$(read_api_key)" || { echo "ERROR: API_KEY or readable API_KEY_FILE is required" >&2; exit 2; }
  [[ -n "$key" ]] || { echo "ERROR: empty API key" >&2; exit 2; }
  umask 077
  printf 'header = "Authorization: Bearer %s"\n' "$key" > "$AUTH_CURL_CONFIG"
  chmod 600 "$AUTH_CURL_CONFIG" 2>/dev/null || true

  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "ERROR: cloudflared is already running" >&2
    exit 2
  fi

  local tmp="$STATE_DIR/probe.json" code
  code="$(http_code "$tmp" "$LOCAL_URL/health")"
  [[ "$code" == "200" ]] || { echo "ERROR: local /health expected 200, got $code" >&2; exit 3; }
  code="$(http_code "$tmp" "$LOCAL_URL/ready")"
  [[ "$code" == "401" ]] || { echo "ERROR: local /ready without auth expected 401, got $code" >&2; exit 3; }
  code="$(http_code "$tmp" --config "$AUTH_CURL_CONFIG" "$LOCAL_URL/ready")"
  [[ "$code" == "200" ]] || { echo "ERROR: local authenticated /ready expected 200, got $code" >&2; exit 3; }

  : > "$LOG_FILE"
  cloudflared tunnel --url "$LOCAL_URL" --no-autoupdate > "$LOG_FILE" 2>&1 &
  local pid=$!
  printf '%s\n' "$pid" > "$PID_FILE"

  local url=""
  for _ in $(seq 1 60); do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "ERROR: cloudflared exited before publishing a Quick Tunnel URL" >&2
      rm -f "$PID_FILE"
      exit 4
    fi
    url="$(python - "$LOG_FILE" <<'PY'
from pathlib import Path
import sys
from app.qualification.cloudflare import extract_quick_tunnel_url
p = Path(sys.argv[1])
print(extract_quick_tunnel_url(p.read_text(encoding='utf-8', errors='replace')) or '')
PY
)"
    [[ -n "$url" ]] && break
    sleep 1
  done
  [[ -n "$url" ]] || { kill "$pid" 2>/dev/null || true; rm -f "$PID_FILE"; echo "ERROR: no Quick Tunnel URL detected" >&2; exit 4; }
  printf '%s\n' "$url" > "$URL_FILE"

  code="$(http_code "$tmp" "$url/health")"
  [[ "$code" == "200" ]] || { echo "ERROR: remote /health expected 200, got $code" >&2; exit 5; }
  code="$(http_code "$tmp" "$url/ready")"
  [[ "$code" == "401" ]] || { echo "ERROR: remote /ready without auth expected 401, got $code" >&2; exit 5; }
  code="$(http_code "$tmp" --config "$AUTH_CURL_CONFIG" "$url/ready")"
  [[ "$code" == "200" ]] || { echo "ERROR: remote authenticated /ready expected 200, got $code" >&2; exit 5; }
  rm -f "$tmp" "$AUTH_CURL_CONFIG"
  write_status running "$pid" "$url"
  printf 'CLOUDFLARE_TUNNEL=RUNNING\nTUNNEL_URL=%s\n' "$url"
}

status_tunnel() {
  if [[ -f "$STATUS_FILE" ]]; then
    cat "$STATUS_FILE"
  else
    printf '{"state":"absent"}\n'
  fi
}

stop_tunnel() {
  local pid=""
  [[ -f "$PID_FILE" ]] && pid="$(cat "$PID_FILE")"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 10); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
  fi
  write_status stopped "" ""
  rm -f "$PID_FILE" "$URL_FILE" "$AUTH_CURL_CONFIG"
  echo "CLOUDFLARE_TUNNEL=STOPPED"
}

case "${1:-}" in
  start) start_tunnel ;;
  status) status_tunnel ;;
  stop) stop_tunnel ;;
  *) echo "usage: $0 start|status|stop" >&2; exit 2 ;;
esac

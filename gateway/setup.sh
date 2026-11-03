#!/usr/bin/env bash
# Khoa Remote Workspace: Colab/Linux read-only Agent installer from HTTPS Render.
set -euo pipefail
umask 077
BASE_URL='__KRW_PUBLIC_ORIGIN__'
EXPECTED_SHA256='__KRW_AGENT_BUNDLE_SHA256__'
INSTALL_DIR="${KRW_INSTALL_DIR:-$HOME/.local/share/krw-agent}"
CONFIG_DIR="${KRW_CONFIG_DIR:-$HOME/.config/krw-agent}"

fail() { printf 'KRW setup ERROR: %s\n' "$*" >&2; exit 1; }
info() { printf '[KRW] %s\n' "$*" >&2; }
prompt() {
  local __name="$1" __message="$2" __answer=''
  [[ -r /dev/tty ]] || fail 'No terminal: set KRW_DEVICE_ID, KRW_WORKSPACE_ROOT and KRW_AGENT_TOKEN as environment variables.'
  IFS= read -r -p "$__message" __answer </dev/tty || fail 'Input cancelled'
  printf -v "$__name" '%s' "$__answer"
}

[[ "$BASE_URL" == https://* && "$BASE_URL" != *'__KRW_'* ]] || fail 'Bootstrap URL not configured'
[[ "$EXPECTED_SHA256" =~ ^[a-f0-9]{64}$ ]] || fail 'Invalid archive digest'
command -v python3 >/dev/null || fail 'Python 3 is required'
command -v tar >/dev/null || fail 'tar is required'
command -v sha256sum >/dev/null || fail 'sha256sum is required'
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"' \
  || fail 'Python 3.10 or newer is required'

DEVICE_ID="${KRW_DEVICE_ID:-}"
if [[ -z "$DEVICE_ID" ]]; then
  prompt DEVICE_ID 'Device ID [local-dev]: '
  DEVICE_ID="${DEVICE_ID:-local-dev}"
fi
[[ "$DEVICE_ID" =~ ^[a-z0-9][a-z0-9._-]{0,63}$ ]] || fail 'Invalid device ID'

WORKSPACE="${KRW_WORKSPACE_ROOT:-}"
if [[ -z "$WORKSPACE" ]]; then
  prompt WORKSPACE 'Workspace absolute path (e.g. /content/my-project): '
fi
[[ "$WORKSPACE" = /* && -d "$WORKSPACE" ]] || fail 'Workspace must be an existing absolute directory'
WORKSPACE="$(cd -- "$WORKSPACE" && pwd -P)"
[[ "$WORKSPACE" != '/' && "$WORKSPACE" != '/content' && "$WORKSPACE" != "$HOME" ]] \
  || fail 'Choose a dedicated workspace directory, not a broad filesystem root'

TOKEN="${KRW_AGENT_TOKEN:-}"
if [[ -z "$TOKEN" ]]; then
  [[ -r /dev/tty ]] || fail 'Missing KRW_AGENT_TOKEN and no interactive terminal'
  printf 'Device token (input hidden): ' >/dev/tty
  IFS= read -r -s TOKEN </dev/tty || fail 'Token input cancelled'
  printf '\n' >/dev/tty
fi
[[ ${#TOKEN} -ge 32 ]] || fail 'KRW_AGENT_TOKEN must have at least 32 characters'

# Keep credentials outside the remotely readable workspace.
mkdir -p -- "$INSTALL_DIR" "$CONFIG_DIR"
INSTALL_DIR="$(cd -- "$INSTALL_DIR" && pwd -P)"
CONFIG_DIR="$(cd -- "$CONFIG_DIR" && pwd -P)"
case "$INSTALL_DIR/" in "$WORKSPACE/"*) fail 'Installation directory must be outside the workspace';; esac
case "$CONFIG_DIR/" in "$WORKSPACE/"*) fail 'Credentials directory must be outside the workspace';; esac
case "$WORKSPACE/" in "$INSTALL_DIR/"*) fail 'Workspace must not contain agent installation';; esac
case "$WORKSPACE/" in "$CONFIG_DIR/"*) fail 'Workspace must not contain credentials';; esac

TEMP_DIR="$(mktemp -d)"
trap 'rm -rf -- "$TEMP_DIR"' EXIT
ARCHIVE="$TEMP_DIR/agent-bundle.tar.gz"
info "Fetching read-only Agent from $BASE_URL"
if command -v curl >/dev/null; then
  curl -fsSL --retry 2 --connect-timeout 15 --max-time 90 "$BASE_URL/agent-bundle.tar.gz" -o "$ARCHIVE"
elif command -v wget >/dev/null; then
  wget -qO "$ARCHIVE" "$BASE_URL/agent-bundle.tar.gz"
else
  fail 'curl or wget is required'
fi
printf '%s  %s\n' "$EXPECTED_SHA256" "$ARCHIVE" | sha256sum -c - >/dev/null \
  || fail 'Agent bundle checksum mismatch; nothing has been installed'

while IFS= read -r item; do
  case "$item" in
    agent/__init__.py|agent/agent.py|agent/worker.py|agent/git_readonly.py|agent-requirements.txt) ;;
    *) fail 'Unexpected file in Agent bundle' ;;
  esac
done < <(tar -tzf "$ARCHIVE")
tar -xzf "$ARCHIVE" -C "$INSTALL_DIR" --no-same-owner

if [[ ! -x "$INSTALL_DIR/.venv/bin/python" ]]; then
  python3 -m venv "$INSTALL_DIR/.venv" || fail 'Python venv is unavailable (install python3-venv)'
fi
"$INSTALL_DIR/.venv/bin/python" -m pip install --disable-pip-version-check -q -r "$INSTALL_DIR/agent-requirements.txt"

CONFIG_FILE="$CONFIG_DIR/agent.env"
{
  printf 'KRW_DEVICE_ID=%q\n' "$DEVICE_ID"
  printf 'KRW_AGENT_TOKEN=%q\n' "$TOKEN"
  printf 'KRW_WORKSPACE_ROOT=%q\n' "$WORKSPACE"
  printf 'KRW_RELAY_URL=%q\n' "$BASE_URL"
  printf 'KRW_COMMANDS_ENABLED=0\n'
  printf 'KRW_ALLOW_TEST_COMMANDS=0\n'
} >"$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"
unset TOKEN KRW_AGENT_TOKEN

printf '#!/usr/bin/env bash\nCONFIG_FILE=%q\n' "$CONFIG_FILE" > "$INSTALL_DIR/start.sh"
cat >> "$INSTALL_DIR/start.sh" <<'RUNNER'
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
[[ -f "$CONFIG_FILE" ]] || { echo 'KRW agent configuration missing' >&2; exit 1; }
set -a
source "$CONFIG_FILE"
set +a
export KRW_COMMANDS_ENABLED=0 KRW_ALLOW_TEST_COMMANDS=0
cd "$SCRIPT_DIR"
exec "$SCRIPT_DIR/.venv/bin/python" -m agent.agent
RUNNER
chmod 700 "$INSTALL_DIR/start.sh"
info "Ready: device=$DEVICE_ID workspace=$WORKSPACE"
info "Rerun later with: $INSTALL_DIR/start.sh"
info 'Starting Agent (Ctrl+C stops it)'
rm -rf -- "$TEMP_DIR"
trap - EXIT
exec "$INSTALL_DIR/start.sh"

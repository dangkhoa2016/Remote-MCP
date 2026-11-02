"""Authenticated MCP resource server behind the local login frontend.

Only the frontend :8765 should be exposed through Cloudflare. This backend
binds loopback :8767 and rejects use without a configured password OAuth flow.
"""
from __future__ import annotations
import json
import os
import urllib.error
import urllib.request
from typing import Any

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.transport_security import TransportSecuritySettings
from gateway.local_security import LocalConfig, LocalTokenVerifier

CONFIG = LocalConfig.from_env()
if os.getenv("KRW_OAUTH_ENABLED", "0") != "1":
    raise RuntimeError("KRW_OAUTH_ENABLED=1 is required for local login MCP")
MCP_TOOLS_ENABLED = os.getenv("KRW_MCP_TOOLS_ENABLED", "0") == "1"
RELAY_URL = os.getenv("KRW_RELAY_URL", "http://127.0.0.1:8766").rstrip("/")
CONTROL_TOKEN = os.getenv("KRW_CONTROL_TOKEN", "")

mcp = MCPServer(
    "Khoa Remote Workspace (Local Login)",
    token_verifier=LocalTokenVerifier(CONFIG), auth=CONFIG.sdk_settings(),
)


def call_relay(path: str, payload: dict | None = None) -> dict[str, Any]:
    if not MCP_TOOLS_ENABLED or len(CONTROL_TOKEN) < 32:
        return {"error": "Device tools locked. Authenticate and enable read tools first."}
    if not (RELAY_URL.startswith("http://127.0.0.1:") or RELAY_URL.startswith("http://localhost:")):
        return {"error": "Relay must run on loopback."}
    req = urllib.request.Request(
        RELAY_URL + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"X-Control-Token": CONTROL_TOKEN, "Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=27) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read().decode()).get("detail", "Request denied")
        except (ValueError, UnicodeDecodeError):
            message = "Request denied"
        return {"error": str(message)[:200], "http_status": exc.code}
    except (OSError, ValueError) as exc:
        return {"error": "Relay unavailable: " + type(exc).__name__}


def dispatch(device_id: str, operation: str, args: dict) -> dict[str, Any]:
    if not isinstance(device_id, str) or not 1 <= len(device_id) <= 64:
        return {"error": "Invalid device_id"}
    return call_relay("/v1/control/dispatch", {"device_id": device_id, "operation": operation, "arguments": args})


@mcp.tool()
def health_check() -> dict[str, str]:
    """Verify the MCP server is reachable after authenticating, without accessing devices."""
    return {"service": "khoa-remote-workspace", "version": "0.4.0", "status": "ok",
            "mode": "local-login-read" if MCP_TOOLS_ENABLED else "locked"}


@mcp.tool()
def list_capabilities() -> dict[str, Any]:
    """Inspect what remote capabilities are enabled, without revealing secrets."""
    if not MCP_TOOLS_ENABLED:
        return {"mode": "locked", "device_agent_connected": False, "filesystem_access": False,
                "command_execution": False, "available_tools": ["health_check", "list_capabilities"]}
    result = call_relay("/v1/control/capabilities")
    result["command_execution"] = False  # hard-disabled in this release
    return result


@mcp.tool()
def list_devices() -> dict[str, Any]:
    """List authorized online device agents, after username/password login."""
    return call_relay("/v1/control/devices")


@mcp.tool()
def get_device_info(device_id: str) -> dict[str, Any]:
    """Inspect OS/hostname/CPU on an authorized device, after login."""
    return dispatch(device_id, "get_device_info", {})


@mcp.tool()
def list_directory(device_id: str, path: str = ".") -> dict[str, Any]:
    """List files strictly beneath an authorized device workspace root."""
    return dispatch(device_id, "list_directory", {"path": path})


@mcp.tool()
def read_file(device_id: str, path: str, max_bytes: int = 8192) -> dict[str, Any]:
    """Read UTF-8 nonhidden files beneath an explicitly allowed workspace root."""
    return dispatch(device_id, "read_file", {"path": path, "max_bytes": max_bytes})


@mcp.tool()
def git_status(device_id: str) -> dict[str, Any]:
    """Read a sanitized Git status summary from an authorized workspace."""
    return dispatch(device_id, "git_status", {})


@mcp.tool()
def git_diff(device_id: str, path: str, staged: bool = False) -> dict[str, Any]:
    """Read a bounded diff for one allowed source file; never invoke a shell."""
    return dispatch(device_id, "git_diff", {"path": path, "staged": staged})


@mcp.tool()
def git_log(device_id: str, count: int = 10) -> dict[str, Any]:
    """Read up to 20 Git commit metadata records (never checkout/reset)."""
    return dispatch(device_id, "git_log", {"count": count})


@mcp.tool()
def execute_command(device_id: str, command_id: str) -> dict[str, Any]:
    """Command execution is unavailable in this release, including for authenticated users."""
    return {"error": "Remote command execution disabled in local-login build"}


if __name__ == "__main__":
    # The loopback-only MCP server is contacted by the local frontend. The
    # frontend checks the public hostname; don't expose this port through Cloudflare.
    mcp.run(
        transport="streamable-http", host="127.0.0.1", port=8767,
        stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
        ),
    )

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
    return {"service": "khoa-remote-workspace", "version": "0.9.0", "status": "ok",
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
def list_directory(device_id: str, path: str = ".", workspace_id: str = "default") -> dict[str, Any]:
    """List files strictly beneath an authorized device workspace root."""
    return dispatch(device_id, "list_directory", {"workspace_id": workspace_id, "path": path})


@mcp.tool()
def read_file(device_id: str, path: str, max_bytes: int = 8192, workspace_id: str = "default") -> dict[str, Any]:
    """Read UTF-8 source files within the workspace (up to 256 KiB per request)."""
    return dispatch(device_id, "read_file", {"workspace_id": workspace_id, "path": path, "max_bytes": max_bytes})


@mcp.tool()
def git_status(device_id: str, workspace_id: str = "default") -> dict[str, Any]:
    """Read a sanitized Git status summary from an authorized workspace."""
    return dispatch(device_id, "git_status", {"workspace_id": workspace_id, })


@mcp.tool()
def git_diff(device_id: str, path: str, staged: bool = False, workspace_id: str = "default") -> dict[str, Any]:
    """Read a bounded diff for one allowed source file; never invoke a shell."""
    return dispatch(device_id, "git_diff", {"workspace_id": workspace_id, "path": path, "staged": staged})


@mcp.tool()
def git_log(device_id: str, count: int = 10, workspace_id: str = "default") -> dict[str, Any]:
    """Read up to 20 Git commit metadata records (never checkout/reset)."""
    return dispatch(device_id, "git_log", {"workspace_id": workspace_id, "count": count})


@mcp.tool()
def file_sha256(device_id: str, path: str, workspace_id: str = "default") -> dict[str, Any]:
    """Read SHA-256 of one allowed source file before an optimistic update."""
    return dispatch(device_id, "file_sha256", {"workspace_id": workspace_id, "path": path})


@mcp.tool()
def write_file(device_id: str, path: str, content: str, expected_sha256: str | None = None,
               overwrite: bool = False, workspace_id: str = "default") -> dict[str, Any]:
    """Create or overwrite UTF-8 text (1 MiB max). Updates require SHA-256 or overwrite=true.

    Render must set KRW_WRITE_ENABLED=1 and Agent KRW_ALLOW_FILE_WRITES=1.
    No file deletion, arbitrary shell, Git writes or bulk operations.
    """
    if os.getenv("KRW_WRITE_ENABLED", "0") != "1":
        return {"error": "Workspace writes disabled on gateway"}
    return dispatch(device_id, "write_file",
                    {"workspace_id": workspace_id, "path": path, "content": content, "expected_sha256": expected_sha256,
                     "overwrite": overwrite})


@mcp.tool()
def edit_file(device_id: str, path: str, old_string: str, new_string: str,
              expected_replacements: int = 1, expected_sha256: str | None = None, workspace_id: str = "default") -> dict[str, Any]:
    """Replace an exact text span inside a workspace file; SHA-256 is optional."""
    if os.getenv("KRW_WRITE_ENABLED", "0") != "1":
        return {"error": "Workspace writes disabled on gateway"}
    return dispatch(device_id, "edit_file",
                    {"workspace_id": workspace_id, "path": path, "old_string": old_string, "new_string": new_string,
                     "expected_replacements": expected_replacements, "expected_sha256": expected_sha256})


@mcp.tool()
def search_files(device_id: str, query: str, path: str = ".", mode: str = "both",
                 max_results: int = 50, case_sensitive: bool = False, workspace_id: str = "default") -> dict[str, Any]:
    """Search workspace filenames and UTF-8 source content without running shell."""
    return dispatch(device_id, "search_files",
                    {"workspace_id": workspace_id, "query": query, "path": path, "mode": mode,
                     "max_results": max_results, "case_sensitive": case_sensitive})


@mcp.tool()
def create_directory(device_id: str, path: str, parents: bool = True, workspace_id: str = "default") -> dict[str, Any]:
    """Create one or more nested workspace directories."""
    if os.getenv("KRW_WRITE_ENABLED", "0") != "1":
        return {"error": "Workspace writes disabled on gateway"}
    return dispatch(device_id, "create_directory", {"workspace_id": workspace_id, "path": path, "parents": parents})


@mcp.tool()
def move_file(device_id: str, source: str, destination: str,
              expected_sha256: str | None = None, workspace_id: str = "default") -> dict[str, Any]:
    """Move an editable text file to a new path without overwriting a destination."""
    if os.getenv("KRW_WRITE_ENABLED", "0") != "1":
        return {"error": "Workspace writes disabled on gateway"}
    return dispatch(device_id, "move_file",
                    {"workspace_id": workspace_id, "source": source, "destination": destination,
                     "expected_sha256": expected_sha256})


@mcp.tool()
def delete_file(device_id: str, path: str, expected_sha256: str | None = None, workspace_id: str = "default") -> dict[str, Any]:
    """Delete one workspace source file; optional SHA-256 guards against stale edits."""
    if os.getenv("KRW_WRITE_ENABLED", "0") != "1":
        return {"error": "Workspace writes disabled on gateway"}
    return dispatch(device_id, "delete_file",
                    {"workspace_id": workspace_id, "path": path, "expected_sha256": expected_sha256})


@mcp.tool()
def check_syntax(device_id: str, path: str, workspace_id: str = "default") -> dict[str, Any]:
    """Validate Python/JSON/TOML syntax without executing project code."""
    if os.getenv("KRW_STATIC_CHECKS_ENABLED", "0") != "1":
        return {"error": "Static checks disabled on gateway"}
    return dispatch(device_id, "check_syntax", {"workspace_id": workspace_id, "path": path})


@mcp.tool()
def list_workspaces(device_id: str) -> dict[str, Any]:
    """List the named workspace roots explicitly allowed on this device."""
    return dispatch(device_id, "list_workspaces", {})


@mcp.tool()
def move_directory(device_id: str, source: str, destination: str,
                   workspace_id: str = "default") -> dict[str, Any]:
    """Move a directory within one authorized workspace, without overwriting."""
    if os.getenv("KRW_WRITE_ENABLED", "0") != "1":
        return {"error": "Workspace writes disabled on gateway"}
    return dispatch(device_id, "move_directory",
                    {"workspace_id": workspace_id, "source": source, "destination": destination})


@mcp.tool()
def delete_directory(device_id: str, path: str, recursive: bool = False,
                     max_entries: int = 1000, workspace_id: str = "default") -> dict[str, Any]:
    """Remove an empty directory; recursive=true removes up to max_entries after preflight."""
    if os.getenv("KRW_WRITE_ENABLED", "0") != "1":
        return {"error": "Workspace writes disabled on gateway"}
    return dispatch(device_id, "delete_directory",
                    {"workspace_id": workspace_id, "path": path, "recursive": recursive,
                     "max_entries": max_entries})


@mcp.tool()
def git_branches(device_id: str, workspace_id: str = "default") -> dict[str, Any]:
    """List local branches and identify the currently checked-out branch."""
    return dispatch(device_id, "git_branches", {"workspace_id": workspace_id})


@mcp.tool()
def git_unstage(device_id: str, path: str, workspace_id: str = "default") -> dict[str, Any]:
    """Remove one path from Git staging without discarding working tree changes."""
    if os.getenv("KRW_GIT_WRITES_ENABLED", "0") != "1":
        return {"error": "Git writes disabled on gateway"}
    return dispatch(device_id, "git_unstage", {"workspace_id": workspace_id, "path": path})


@mcp.tool()
def git_stage(device_id: str, path: str, workspace_id: str = "default") -> dict[str, Any]:
    """Stage one authorized file path in a Git repository."""
    if os.getenv("KRW_GIT_WRITES_ENABLED", "0") != "1":
        return {"error": "Git writes disabled on gateway"}
    return dispatch(device_id, "git_stage", {"workspace_id": workspace_id, "path": path})


@mcp.tool()
def git_commit(device_id: str, message: str, author_name: str, author_email: str,
               workspace_id: str = "default") -> dict[str, Any]:
    """Commit staged authorized files with explicit author identity; hooks disabled."""
    if os.getenv("KRW_GIT_WRITES_ENABLED", "0") != "1":
        return {"error": "Git writes disabled on gateway"}
    return dispatch(device_id, "git_commit",
                    {"workspace_id": workspace_id, "message": message,
                     "author_name": author_name, "author_email": author_email})


@mcp.tool()
def git_branch_create(device_id: str, branch: str,
                      workspace_id: str = "default") -> dict[str, Any]:
    """Create a local branch from HEAD without switching workspaces."""
    if os.getenv("KRW_GIT_WRITES_ENABLED", "0") != "1":
        return {"error": "Git writes disabled on gateway"}
    return dispatch(device_id, "git_branch_create",
                    {"workspace_id": workspace_id, "branch": branch})


@mcp.tool()
def git_branch_switch(device_id: str, branch: str,
                      workspace_id: str = "default") -> dict[str, Any]:
    """Switch a clean local repository to an existing branch."""
    if os.getenv("KRW_GIT_WRITES_ENABLED", "0") != "1":
        return {"error": "Git writes disabled on gateway"}
    return dispatch(device_id, "git_branch_switch",
                    {"workspace_id": workspace_id, "branch": branch})


@mcp.tool()
def git_push(device_id: str, branch: str, workspace_id: str = "default") -> dict[str, Any]:
    """Push current branch to HTTPS GitHub origin, when separately enabled and authenticated."""
    if os.getenv("KRW_GIT_WRITES_ENABLED", "0") != "1":
        return {"error": "Git writes disabled on gateway"}
    if os.getenv("KRW_GIT_PUSH_ENABLED", "0") != "1":
        return {"error": "Git push disabled on gateway"}
    return dispatch(device_id, "git_push",
                    {"workspace_id": workspace_id, "branch": branch})


@mcp.tool()
def list_tasks(device_id: str, workspace_id: str = "default") -> dict[str, Any]:
    """List fixed, named tasks and Agent opt-in status for an authorized workspace."""
    return dispatch(device_id, "list_tasks", {"workspace_id": workspace_id})


@mcp.tool()
def run_task(device_id: str, task_id: str, target: str = "",
             workspace_id: str = "default") -> dict[str, Any]:
    """Run a fixed allowlisted task, never an arbitrary command or shell string.

    Tasks: git_status, git_log, pytest, rspec, rails_test. Test tasks run
    project code and require separate explicit opt-in at Gateway and Agent.
    Results are bounded and subject to a 15-second process-group timeout.
    """
    if os.getenv("KRW_TASKS_ENABLED", "0") != "1":
        return {"error": "Controlled tasks disabled on gateway"}
    if task_id in {"pytest", "rspec", "rails_test"} and os.getenv("KRW_TEST_TASKS_ENABLED", "0") != "1":
        return {"error": "Test tasks disabled on gateway"}
    return dispatch(device_id, "run_task",
                    {"workspace_id": workspace_id, "task_id": task_id, "target": target})


@mcp.tool()
def start_long_task(device_id: str, task_id: str, target: str = "",
                    workspace_id: str = "default") -> dict[str, Any]:
    """Queue a bounded long-running pytest/RSpec/Rails test in an authorized workspace.

    Returns a job ID immediately. No arbitrary shell or flags. Execution of
    trusted project code is NOT sandboxed; separate opt-in is required.
    """
    if os.getenv("KRW_LONG_TASKS_ENABLED", "0") != "1":
        return {"error": "Long-running tasks disabled on gateway"}
    return dispatch(device_id, "start_long_task",
                    {"workspace_id": workspace_id, "task_id": task_id, "target": target})


@mcp.tool()
def get_long_task(device_id: str, job_id: str, workspace_id: str = "default") -> dict[str, Any]:
    """Read the status of a previously queued long test task in one workspace."""
    if os.getenv("KRW_LONG_TASKS_ENABLED", "0") != "1":
        return {"error": "Long-running tasks disabled on gateway"}
    return dispatch(device_id, "get_long_task", {"workspace_id": workspace_id, "job_id": job_id})


@mcp.tool()
def read_long_task_log(device_id: str, job_id: str, offset: int = 0,
                       max_bytes: int = 4096, workspace_id: str = "default") -> dict[str, Any]:
    """Read a bounded log chunk; pass next_offset to fetch subsequent output."""
    if os.getenv("KRW_LONG_TASKS_ENABLED", "0") != "1":
        return {"error": "Long-running tasks disabled on gateway"}
    return dispatch(device_id, "read_long_task_log",
                    {"workspace_id": workspace_id, "job_id": job_id,
                     "offset": offset, "max_bytes": max_bytes})


@mcp.tool()
def cancel_long_task(device_id: str, job_id: str, workspace_id: str = "default") -> dict[str, Any]:
    """Request cancellation of one queued/running long task; no arbitrary process kill."""
    if os.getenv("KRW_LONG_TASKS_ENABLED", "0") != "1":
        return {"error": "Long-running tasks disabled on gateway"}
    return dispatch(device_id, "cancel_long_task",
                    {"workspace_id": workspace_id, "job_id": job_id})


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

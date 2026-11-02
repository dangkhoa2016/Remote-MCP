"""Sandboxed workspace operations. Never execute an arbitrary shell string."""
from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 32_768
MAX_DIRECTORY_ENTRIES = 150
DENIED_NAMES = {".env", "id_rsa", "id_ed25519", "credentials", "credentials.json", "token", "token.txt"}
DENIED_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


class WorkspaceError(Exception):
    pass


class Worker:
    def __init__(self, root: Path, commands_enabled: bool = False, tests_enabled: bool = False):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Workspace root must be a directory")
        self.commands_enabled = commands_enabled
        self.tests_enabled = tests_enabled

    def path(self, requested: str) -> Path:
        if not isinstance(requested, str) or len(requested) > 400 or "\x00" in requested:
            raise WorkspaceError("Invalid path")
        if Path(requested).is_absolute():
            raise WorkspaceError("Only relative paths are permitted")
        parts = Path(requested).parts
        if any(part in ("..", "") or part.startswith(".") or part.lower() in DENIED_NAMES
               or Path(part).suffix.lower() in DENIED_SUFFIXES for part in parts):
            raise WorkspaceError("Path is restricted")
        # Reject every symlink in the requested path, including links pointing
        # back inside the workspace to hidden files. This check is also backed
        # by descriptor-relative O_NOFOLLOW opens during reads/listings.
        current = self.root
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise WorkspaceError("Symlink paths are restricted")
        candidate = current.resolve(strict=False)
        if not candidate.is_relative_to(self.root):
            raise WorkspaceError("Path escapes workspace root")
        # A symlink race could change the resolved target. Never accept a
        # canonical path into a hidden or disallowed component either.
        canonical_parts = candidate.relative_to(self.root).parts
        if any(p.startswith(".") or p.lower() in DENIED_NAMES
               or Path(p).suffix.lower() in DENIED_SUFFIXES for p in canonical_parts):
            raise WorkspaceError("Path is restricted")
        return candidate

    def _open_nofollow(self, relative: str, *, directory: bool) -> int:
        """Traverse from workspace root with no symlinks at any level (Linux/POSIX).

        Resolve-time checks alone are vulnerable to symlink swaps. We instead
        hold each directory descriptor open and use O_NOFOLLOW for every hop.
        If the platform lacks required flags, fail closed.
        """
        if (os.name != "posix" or not hasattr(os, "O_NOFOLLOW")
                or not hasattr(os, "O_DIRECTORY") or os.open not in os.supports_dir_fd):
            raise WorkspaceError("Safe descriptor-based access unavailable")
        root_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            fd = os.open(self.root, root_flags)
        except OSError as exc:
            raise WorkspaceError("Workspace directory unavailable") from exc
        try:
            pieces = Path(relative).parts
            if not pieces and not directory:
                raise WorkspaceError("Not a regular file")
            for i, piece in enumerate(pieces):
                last = i == len(pieces) - 1
                flags = os.O_RDONLY | os.O_NOFOLLOW
                if not last or directory:
                    flags |= os.O_DIRECTORY
                else:
                    flags |= getattr(os, "O_NONBLOCK", 0)
                next_fd = os.open(piece, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            return fd
        except OSError as exc:
            os.close(fd)
            raise WorkspaceError("Path is restricted or unavailable") from exc
        except BaseException:
            os.close(fd)
            raise

    def get_device_info(self, _: dict[str, Any]) -> dict[str, Any]:
        total_memory = None
        try:
            if hasattr(os, "sysconf"):
                total_memory = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, KeyError):
            pass
        disk = shutil.disk_usage(self.root)
        return {"hostname": platform.node()[:128], "platform": platform.platform()[:128],
                "python": platform.python_version(), "cpu_count": os.cpu_count(),
                "memory_total_bytes": total_memory, "workspace_disk_total_bytes": disk.total,
                "workspace_disk_free_bytes": disk.free, "workspace": self.root.name}

    def list_directory(self, args: dict[str, Any]) -> dict[str, Any]:
        rel = str(args.get("path", "."))
        path = self.path(rel)
        if not path.is_dir():
            raise WorkspaceError("Not a directory")
        fd = self._open_nofollow(rel, directory=True)
        try:
            with os.scandir(fd) as iterator:
                entries = sorted(iterator, key=lambda p: p.name.lower())
            items = []
            for entry in entries:
                if len(items) >= MAX_DIRECTORY_ENTRIES:
                    break
                if entry.is_symlink():
                    continue
                try:
                    self.path(str(Path(rel) / entry.name))
                except WorkspaceError:
                    continue
                items.append({"name": entry.name,
                              "type": "directory" if entry.is_dir(follow_symlinks=False) else "file"})
        finally:
            os.close(fd)
        return {"path": str(path.relative_to(self.root)), "entries": items, "limit": MAX_DIRECTORY_ENTRIES}

    def read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        rel = str(args.get("path", ""))
        path = self.path(rel)
        if not path.is_file() or path.is_symlink():
            raise WorkspaceError("Not a regular file")
        max_bytes = args.get("max_bytes", 8192)
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_FILE_BYTES:
            raise WorkspaceError("max_bytes outside permitted range")
        # Descriptor-relative traversal blocks symlink swaps at *every* level.
        fd = self._open_nofollow(rel, directory=False)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise WorkspaceError("Not a regular file")
            data = os.read(fd, max_bytes + 1)
        finally:
            os.close(fd)
        try:
            text = data[:max_bytes].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceError("File is not UTF-8 text") from exc
        return {"path": rel, "content": text, "truncated": len(data) > max_bytes, "bytes_read": len(data[:max_bytes])}

    def execute_command(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self.commands_enabled:
            raise WorkspaceError("Command execution disabled on agent")
        command_id = args.get("command_id")
        commands = {"python_version": [sys.executable, "--version"]}
        git = shutil.which("git")
        if git:
            commands["git_status"] = [git, "-c", "core.fsmonitor=false", "status", "--short"]
        if self.tests_enabled:
            commands["pytest"] = [sys.executable, "-m", "pytest", "-q", "--disable-warnings"]
        if command_id not in commands:
            raise WorkspaceError("Command not in allowlist")
        env = {"PATH": os.getenv("PATH", "/usr/bin:/bin"), "PYTHONIOENCODING": "utf-8",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_OPTIONAL_LOCKS": "0"}
        try:
            result = subprocess.run(commands[command_id], cwd=self.root, env=env, capture_output=True,
                                    text=True, timeout=12, check=False, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as exc:
            raise WorkspaceError("Command timed out") from exc
        return {"command_id": command_id, "exit_code": result.returncode,
                "stdout": result.stdout[:12_000], "stderr": result.stderr[:4_000]}

    def dispatch(self, operation: str, args: dict[str, Any]) -> dict[str, Any]:
        operations = {"get_device_info": self.get_device_info, "list_directory": self.list_directory,
                      "read_file": self.read_file, "execute_command": self.execute_command}
        if operation not in operations:
            raise WorkspaceError("Unsupported operation")
        return operations[operation](args)

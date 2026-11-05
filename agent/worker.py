"""Sandboxed workspace operations. Never execute an arbitrary shell string."""
from __future__ import annotations

import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any
from agent.git_readonly import GitReadOnly, GitReadOnlyError
from agent.git_write import GitWrite
from agent.workspace_edit import WorkspaceEditor, WorkspaceEditError
from agent.workspace_manage import WorkspaceManager
from agent.task_runner import TaskRunner, TaskError
from agent.long_tasks import LongTaskManager

MAX_FILE_BYTES = 262_144
MAX_DIRECTORY_ENTRIES = 150
DENIED_NAMES = {".env", ".git", ".ssh", "id_rsa", "id_ed25519", "credentials", "credentials.json", "token", "token.txt"}
DENIED_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
# Reject names commonly used for secrets even when not dot-prefixed,
# e.g. env.dev.txt, service-token.json, credentials.backup.
# A filename denylist is defense in depth; secret files must be kept
# outside the authorized workspace root regardless of their names.
_SECRET_MARKER = re.compile(
    r"(?:^|[._-])(?:env|secrets?|credentials?|tokens?|passwords?|passwd|"
    r"api[_-]?key|private[_-]?key|apikey)(?:$|[._-])",
    re.IGNORECASE,
)


def _denied_component(name: str) -> bool:
    lowered = name.casefold()
    return (lowered in DENIED_NAMES
            or Path(lowered).suffix in DENIED_SUFFIXES
            or bool(_SECRET_MARKER.search(lowered)))


class WorkspaceError(Exception):
    pass


class Worker:
    def __init__(self, root: Path, commands_enabled: bool = False, tests_enabled: bool = False,
                 write_enabled: bool = False, checks_enabled: bool = False,
                 git_write_enabled: bool = False, git_push_enabled: bool = False,
                 tasks_enabled: bool = False, test_tasks_enabled: bool = False,
                 long_tasks_enabled: bool = False,
                 long_task_manager: LongTaskManager | None = None):
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Workspace root must be a directory")
        self.commands_enabled = commands_enabled
        self.tests_enabled = tests_enabled
        if (write_enabled or tasks_enabled) and self.root in {Path("/"), Path("/content"), Path.home().resolve()}:
            raise ValueError("Workspace root too broad for enabled writes or tasks")
        self.write_enabled = write_enabled
        self.checks_enabled = checks_enabled
        self.git_write_enabled = git_write_enabled
        self.git_push_enabled = git_push_enabled
        self.tasks_enabled = tasks_enabled
        self.test_tasks_enabled = test_tasks_enabled
        self.long_tasks_enabled = long_tasks_enabled
        self.long_task_manager = long_task_manager if long_task_manager is not None else LongTaskManager()

    def path(self, requested: str) -> Path:
        if not isinstance(requested, str) or len(requested) > 400 or "\x00" in requested:
            raise WorkspaceError("Invalid path")
        if Path(requested).is_absolute():
            raise WorkspaceError("Only relative paths are permitted")
        parts = Path(requested).parts
        if any(part in ("..", "") or _denied_component(part) for part in parts):
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
        if any(_denied_component(p) for p in canonical_parts):
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
        limited = data[:max_bytes]
        try:
            text = limited.decode("utf-8")
        except UnicodeDecodeError as exc:
            # Only tolerate a *valid* UTF-8 character cut off at the byte cap.
            # Malformed UTF-8 or binary data must still fail closed.
            if (len(data) <= max_bytes or exc.reason != "unexpected end of data"
                    or exc.end != len(limited)):
                raise WorkspaceError("File is not UTF-8 text") from exc
            limited = limited[:exc.start]
            try:
                text = limited.decode("utf-8")
            except UnicodeDecodeError as nested:
                raise WorkspaceError("File is not UTF-8 text") from nested
        return {"path": rel, "content": text, "truncated": len(data) > max_bytes,
                "bytes_read": len(limited)}

    def git_status(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return GitReadOnly(self.root, self.path).status()
        except GitReadOnlyError as exc:
            raise WorkspaceError(str(exc)) from exc

    def git_branches(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return GitReadOnly(self.root, self.path).branches()
        except GitReadOnlyError as exc:
            raise WorkspaceError(str(exc)) from exc

    def git_diff(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return GitReadOnly(self.root, self.path).diff(
                args.get("path", ""), args.get("staged", False))
        except GitReadOnlyError as exc:
            raise WorkspaceError(str(exc)) from exc

    def git_log(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return GitReadOnly(self.root, self.path).log(args.get("count", 10))
        except GitReadOnlyError as exc:
            raise WorkspaceError(str(exc)) from exc

    def file_sha256(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return WorkspaceEditor(self.root, self.path).file_sha256(args.get("path"))
        except WorkspaceEditError as exc:
            raise WorkspaceError(str(exc)) from exc

    def write_file(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self.write_enabled:
            raise WorkspaceError("Workspace writes disabled on agent")
        try:
            return WorkspaceEditor(self.root, self.path).write_file(
                args.get("path"), args.get("content"), args.get("expected_sha256"),
                args.get("overwrite", False))
        except WorkspaceEditError as exc:
            raise WorkspaceError(str(exc)) from exc

    def edit_file(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self.write_enabled:
            raise WorkspaceError("Workspace writes disabled on agent")
        try:
            return WorkspaceManager(self.root, self.path).edit_file(
                args.get("path"), args.get("old_string"), args.get("new_string"),
                args.get("expected_replacements", 1), args.get("expected_sha256"))
        except WorkspaceEditError as exc:
            raise WorkspaceError(str(exc)) from exc

    def search_files(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return WorkspaceManager(self.root, self.path).search_files(
                args.get("query"), args.get("path", "."), args.get("mode", "both"),
                args.get("max_results", 50), args.get("case_sensitive", False))
        except WorkspaceEditError as exc:
            raise WorkspaceError(str(exc)) from exc

    def create_directory(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self.write_enabled:
            raise WorkspaceError("Workspace writes disabled on agent")
        try:
            return WorkspaceManager(self.root, self.path).create_directory(
                args.get("path"), args.get("parents", True))
        except WorkspaceEditError as exc:
            raise WorkspaceError(str(exc)) from exc

    def move_file(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self.write_enabled:
            raise WorkspaceError("Workspace writes disabled on agent")
        try:
            return WorkspaceManager(self.root, self.path).move_file(
                args.get("source"), args.get("destination"), args.get("expected_sha256"))
        except WorkspaceEditError as exc:
            raise WorkspaceError(str(exc)) from exc

    def delete_file(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self.write_enabled:
            raise WorkspaceError("Workspace writes disabled on agent")
        try:
            return WorkspaceManager(self.root, self.path).delete_file(
                args.get("path"), args.get("expected_sha256"))
        except WorkspaceEditError as exc:
            raise WorkspaceError(str(exc)) from exc

    def move_directory(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self.write_enabled:
            raise WorkspaceError("Workspace writes disabled on agent")
        try:
            return WorkspaceManager(self.root, self.path).move_directory(
                args.get("source"), args.get("destination"))
        except WorkspaceEditError as exc:
            raise WorkspaceError(str(exc)) from exc

    def delete_directory(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self.write_enabled:
            raise WorkspaceError("Workspace writes disabled on agent")
        try:
            return WorkspaceManager(self.root, self.path).delete_directory(
                args.get("path"), args.get("recursive", False),
                args.get("max_entries", 1000))
        except WorkspaceEditError as exc:
            raise WorkspaceError(str(exc)) from exc

    def _git_write(self) -> GitWrite:
        if not self.git_write_enabled:
            raise WorkspaceError("Git write operations disabled on agent")
        try:
            return GitWrite(self.root, self.path)
        except GitReadOnlyError as exc:
            raise WorkspaceError(str(exc)) from exc

    def git_stage(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._git_write().stage(args.get("path"))
        except GitReadOnlyError as exc:
            raise WorkspaceError(str(exc)) from exc

    def git_unstage(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._git_write().unstage(args.get("path"))
        except GitReadOnlyError as exc:
            raise WorkspaceError(str(exc)) from exc

    def git_commit(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._git_write().commit(
                args.get("message"), args.get("author_name"), args.get("author_email"))
        except GitReadOnlyError as exc:
            raise WorkspaceError(str(exc)) from exc

    def git_branch_create(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._git_write().branch_create(args.get("branch"))
        except GitReadOnlyError as exc:
            raise WorkspaceError(str(exc)) from exc

    def git_branch_switch(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._git_write().branch_switch(args.get("branch"))
        except GitReadOnlyError as exc:
            raise WorkspaceError(str(exc)) from exc

    def git_push(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self.git_push_enabled:
            raise WorkspaceError("Git push disabled on agent")
        try:
            return self._git_write().push(
                args.get("branch"), os.getenv("KRW_GIT_PUSH_TOKEN", ""))
        except GitReadOnlyError as exc:
            raise WorkspaceError(str(exc)) from exc

    def check_syntax(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self.checks_enabled:
            raise WorkspaceError("Static checks disabled on agent")
        try:
            return WorkspaceEditor(self.root, self.path).check_syntax(args.get("path"))
        except WorkspaceEditError as exc:
            raise WorkspaceError(str(exc)) from exc

    def _task_runner(self) -> TaskRunner:
        return TaskRunner(self.root, self.path, tasks_enabled=self.tasks_enabled,
                          test_tasks_enabled=self.test_tasks_enabled)

    def list_tasks(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._task_runner().list_tasks()

    def run_task(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._task_runner().run_task(args.get("task_id"), args.get("target", ""))
        except TaskError as exc:
            raise WorkspaceError(str(exc)) from exc

    def _ensure_long_tasks(self) -> None:
        if not (self.tasks_enabled and self.test_tasks_enabled and self.long_tasks_enabled):
            raise WorkspaceError("Long-running tasks disabled on Agent")

    def start_long_task(self, args: dict[str, Any]) -> dict[str, Any]:
        self._ensure_long_tasks()
        try:
            return self.long_task_manager.start(
                self._task_runner(),
                workspace_id=args.get("workspace_id", "default"),
                task_id=args.get("task_id"), target=args.get("target", ""),
            )
        except TaskError as exc:
            raise WorkspaceError(str(exc)) from exc

    def get_long_task(self, args: dict[str, Any]) -> dict[str, Any]:
        self._ensure_long_tasks()
        try:
            return self.long_task_manager.status(
                args.get("job_id"), workspace_id=args.get("workspace_id", "default"))
        except TaskError as exc:
            raise WorkspaceError(str(exc)) from exc

    def read_long_task_log(self, args: dict[str, Any]) -> dict[str, Any]:
        self._ensure_long_tasks()
        try:
            return self.long_task_manager.log(
                args.get("job_id"), workspace_id=args.get("workspace_id", "default"),
                offset=args.get("offset", 0), max_bytes=args.get("max_bytes", 4096))
        except TaskError as exc:
            raise WorkspaceError(str(exc)) from exc

    def cancel_long_task(self, args: dict[str, Any]) -> dict[str, Any]:
        self._ensure_long_tasks()
        try:
            return self.long_task_manager.cancel(
                args.get("job_id"), workspace_id=args.get("workspace_id", "default"))
        except TaskError as exc:
            raise WorkspaceError(str(exc)) from exc

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
                      "read_file": self.read_file, "git_status": self.git_status, "git_branches": self.git_branches, "git_diff": self.git_diff, "git_log": self.git_log,
                      "file_sha256": self.file_sha256, "write_file": self.write_file,
                      "edit_file": self.edit_file, "search_files": self.search_files,
                      "create_directory": self.create_directory, "move_file": self.move_file,
                      "delete_file": self.delete_file, "move_directory": self.move_directory,
                      "delete_directory": self.delete_directory,
                      "git_stage": self.git_stage, "git_unstage": self.git_unstage, "git_commit": self.git_commit,
                      "git_branch_create": self.git_branch_create,
                      "git_branch_switch": self.git_branch_switch, "git_push": self.git_push,
                      "check_syntax": self.check_syntax,
                      "execute_command": self.execute_command, "list_tasks": self.list_tasks,
                      "run_task": self.run_task,
                      "start_long_task": self.start_long_task,
                      "get_long_task": self.get_long_task,
                      "read_long_task_log": self.read_long_task_log,
                      "cancel_long_task": self.cancel_long_task}
        if operation not in operations:
            raise WorkspaceError("Unsupported operation")
        return operations[operation](args)

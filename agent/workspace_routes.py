"""Select only explicitly configured workspace roots per device request."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from agent.worker import Worker, WorkspaceError
from agent.long_tasks import LongTaskManager

_WORKSPACE_ID = re.compile(r"[a-z][a-z0-9_-]{0,39}\Z")
MAX_WORKSPACES = 12


class WorkspaceRouter:
    def __init__(self, default_root: Path, extra_roots: dict[str, str] | None = None,
                 *, commands_enabled: bool = False, tests_enabled: bool = False,
                 write_enabled: bool = False, checks_enabled: bool = False,
                 git_write_enabled: bool = False, git_push_enabled: bool = False,
                 tasks_enabled: bool = False, test_tasks_enabled: bool = False,
                 long_tasks_enabled: bool = False):
        if extra_roots is None:
            extra_roots = {}
        if not isinstance(extra_roots, dict) or len(extra_roots) > MAX_WORKSPACES - 1:
            raise ValueError("Invalid KRW_WORKSPACES_JSON mapping")
        roots = {"default": default_root}
        for workspace_id, raw_path in extra_roots.items():
            if (not isinstance(workspace_id, str) or
                    not _WORKSPACE_ID.fullmatch(workspace_id) or
                    workspace_id == "default" or
                    not isinstance(raw_path, str) or not Path(raw_path).is_absolute()):
                raise ValueError("Invalid workspace ID or absolute path")
            roots[workspace_id] = Path(raw_path)
        self.long_task_manager = LongTaskManager()
        self.workers: dict[str, Worker] = {}
        for workspace_id, path in roots.items():
            worker = Worker(
                path, commands_enabled=commands_enabled, tests_enabled=tests_enabled,
                write_enabled=write_enabled, checks_enabled=checks_enabled,
                git_write_enabled=git_write_enabled, git_push_enabled=git_push_enabled,
                tasks_enabled=tasks_enabled, test_tasks_enabled=test_tasks_enabled,
                long_tasks_enabled=long_tasks_enabled,
                long_task_manager=self.long_task_manager,
            )
            # Prevent aliases and nested roots from creating an implicit path
            # between two otherwise independently authorized workspaces.
            if any(
                worker.root == existing.root
                or worker.root.is_relative_to(existing.root)
                or existing.root.is_relative_to(worker.root)
                for existing in self.workers.values()
            ):
                raise ValueError("Workspace roots must be disjoint")
            self.workers[workspace_id] = worker

    @classmethod
    def from_env(cls, root: Path) -> "WorkspaceRouter":
        try:
            extra = json.loads(os.getenv("KRW_WORKSPACES_JSON", "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("KRW_WORKSPACES_JSON must be a JSON object") from exc
        return cls(
            root, extra,
            commands_enabled=os.getenv("KRW_COMMANDS_ENABLED", "0") == "1",
            tests_enabled=os.getenv("KRW_ALLOW_TEST_COMMANDS", "0") == "1",
            write_enabled=os.getenv("KRW_ALLOW_FILE_WRITES", "0") == "1",
            checks_enabled=os.getenv("KRW_ALLOW_STATIC_CHECKS", "0") == "1",
            git_write_enabled=os.getenv("KRW_ALLOW_GIT_WRITES", "0") == "1",
            git_push_enabled=os.getenv("KRW_ALLOW_GIT_PUSH", "0") == "1",
            tasks_enabled=os.getenv("KRW_ALLOW_TASKS", "0") == "1",
            test_tasks_enabled=os.getenv("KRW_ALLOW_TEST_TASKS", "0") == "1",
            long_tasks_enabled=os.getenv("KRW_ALLOW_LONG_TASKS", "0") == "1",
        )

    def list_workspaces(self) -> dict[str, Any]:
        return {"workspaces": [
            {"id": key, "name": worker.root.name, "path": str(worker.root),
             "default": key == "default"}
            for key, worker in self.workers.items()
        ]}

    def shutdown(self) -> None:
        self.long_task_manager.shutdown()

    def dispatch(self, operation: str, args: dict[str, Any]) -> dict[str, Any]:
        if operation == "list_workspaces":
            return self.list_workspaces()
        if not isinstance(args, dict):
            raise WorkspaceError("Invalid arguments")
        requested = args.get("workspace_id", "default")
        if type(requested) is not str or requested not in self.workers:
            raise WorkspaceError("Workspace ID not configured on this device")
        return self.workers[requested].dispatch(operation, args)

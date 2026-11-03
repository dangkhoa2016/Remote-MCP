"""Phase 6.1 regression coverage for safe switching and disjoint workspaces."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from agent.git_readonly import GitReadOnlyError
from agent.worker import Worker, WorkspaceError
from agent.workspace_routes import WorkspaceRouter


def git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


def commit(path: Path, message: str) -> None:
    git(path, "-c", "user.name=KRW Tests", "-c", "user.email=tests@example.invalid",
        "commit", "--no-gpg-sign", "-m", message)


def initialized_repo(path: Path) -> tuple[Worker, str]:
    git(path, "init", "-q")
    git(path, "-c", "user.name=KRW Tests", "-c", "user.email=tests@example.invalid",
        "commit", "--allow-empty", "--no-gpg-sign", "-m", "bootstrap")
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=path, text=True).strip()
    return Worker(path, git_write_enabled=True), branch


@pytest.mark.skipif(shutil.which("git") is None, reason="Git required")
def test_branch_switch_preserves_nonconflicting_untracked_files(tmp_path: Path) -> None:
    worker, original = initialized_repo(tmp_path)
    worker.git_branch_create({"branch": "safe-feature"})
    (tmp_path / "scratch.md").write_text("private untracked work\n", encoding="utf-8")

    assert worker.git_branch_switch({"branch": "safe-feature"})["switched"]
    assert worker.git_branches({})["current"] == "safe-feature"
    assert (tmp_path / "scratch.md").read_text() == "private untracked work\n"

    assert worker.git_branch_switch({"branch": original})["switched"]
    assert worker.git_branches({})["current"] == original
    assert (tmp_path / "scratch.md").read_text() == "private untracked work\n"
    assert any(r["path"] == "scratch.md" and r["state"] == "??"
               for r in worker.git_status({})["entries"])


@pytest.mark.skipif(shutil.which("git") is None, reason="Git required")
def test_branch_switch_rejects_untracked_collision_without_data_loss(tmp_path: Path) -> None:
    worker, original = initialized_repo(tmp_path)
    worker.git_branch_create({"branch": "with-conflict-file"})
    worker.git_branch_switch({"branch": "with-conflict-file"})
    (tmp_path / "collision.md").write_text("tracked target\n", encoding="utf-8")
    worker.git_stage({"path": "collision.md"})
    worker.git_commit({"message": "test: target tracks collision file",
                       "author_name": "KRW Tests", "author_email": "tests@example.invalid"})
    worker.git_branch_switch({"branch": original})

    (tmp_path / "collision.md").write_text("user's untracked edits\n", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="Git operation failed"):
        worker.git_branch_switch({"branch": "with-conflict-file"})
    assert worker.git_branches({})["current"] == original
    assert (tmp_path / "collision.md").read_text() == "user's untracked edits\n"


@pytest.mark.skipif(shutil.which("git") is None, reason="Git required")
def test_branch_switch_rejects_staged_and_tracked_modifications(tmp_path: Path) -> None:
    worker, original = initialized_repo(tmp_path)
    (tmp_path / "tracked.md").write_text("baseline\n", encoding="utf-8")
    worker.git_stage({"path": "tracked.md"})
    worker.git_commit({"message": "test: add tracked file",
                       "author_name": "KRW Tests", "author_email": "tests@example.invalid"})
    worker.git_branch_create({"branch": "clean-target"})
    (tmp_path / "tracked.md").write_text("local changes\n", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="Tracked or staged changes"):
        worker.git_branch_switch({"branch": "clean-target"})
    worker.git_stage({"path": "tracked.md"})
    with pytest.raises(WorkspaceError, match="Tracked or staged changes"):
        worker.git_branch_switch({"branch": "clean-target"})
    assert worker.git_branches({})["current"] == original
    assert (tmp_path / "tracked.md").read_text() == "local changes\n"


def test_two_distinct_roots_isolate_search_write_edit_and_delete(tmp_path: Path) -> None:
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    router = WorkspaceRouter(one, {"secondary": str(two)}, write_enabled=True)
    assert {row["id"] for row in router.list_workspaces()["workspaces"]} == {"default", "secondary"}

    router.dispatch("write_file", {"path": "shared.md", "content": "ONLY_WORKSPACE_ONE\n"})
    router.dispatch("write_file", {
        "workspace_id": "secondary", "path": "shared.md", "content": "ONLY_WORKSPACE_TWO\n"
    })
    assert router.dispatch("read_file", {"path": "shared.md"})["content"] == "ONLY_WORKSPACE_ONE\n"
    assert router.dispatch("read_file", {
        "workspace_id": "secondary", "path": "shared.md"
    })["content"] == "ONLY_WORKSPACE_TWO\n"

    assert router.dispatch("search_files", {"query": "ONLY_WORKSPACE_TWO"})["matches"] == []
    assert len(router.dispatch("search_files", {
        "workspace_id": "secondary", "query": "ONLY_WORKSPACE_TWO"
    })["matches"]) == 1

    router.dispatch("edit_file", {
        "workspace_id": "secondary", "path": "shared.md",
        "old_string": "ONLY_WORKSPACE_TWO", "new_string": "SECONDARY_EDITED",
    })
    router.dispatch("delete_file", {"workspace_id": "secondary", "path": "shared.md"})
    assert not (two / "shared.md").exists()
    assert (one / "shared.md").read_text() == "ONLY_WORKSPACE_ONE\n"

    with pytest.raises(WorkspaceError, match="restricted"):
        router.dispatch("read_file", {"workspace_id": "secondary", "path": "../one/shared.md"})
    with pytest.raises(WorkspaceError, match="not configured"):
        router.dispatch("read_file", {"workspace_id": "not-authorized", "path": "shared.md"})


def test_overlapping_or_aliased_workspaces_are_rejected(tmp_path: Path) -> None:
    one = tmp_path / "one"
    one.mkdir()
    (one / "inside").mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(one, target_is_directory=True)
    for extra_root in (one, one / "inside", tmp_path, alias):
        with pytest.raises(ValueError, match="Workspace roots must be disjoint"):
            WorkspaceRouter(one, {"secondary": str(extra_root)}, write_enabled=True)

"""Phase 6 integration: named workspaces, directory lifecycle, Git writes."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from agent.worker import Worker, WorkspaceError
from agent.workspace_routes import WorkspaceRouter
from gateway.relay import Dispatch, State


def test_named_workspaces_preserve_default_and_isolate_files(tmp_path):
    a = tmp_path / "app"
    b = tmp_path / "docs"
    a.mkdir()
    b.mkdir()
    router = WorkspaceRouter(a, {"docs": str(b)}, write_enabled=True)
    listed = router.dispatch("list_workspaces", {})
    assert [w["id"] for w in listed["workspaces"]] == ["default", "docs"]
    router.dispatch("write_file", {"path": "note.md", "content": "main"})
    router.dispatch("write_file", {"workspace_id": "docs", "path": "note.md", "content": "other"})
    assert (a / "note.md").read_text() == "main"
    assert (b / "note.md").read_text() == "other"
    assert router.dispatch("read_file", {"workspace_id": "docs", "path": "note.md"})["content"] == "other"
    assert router.dispatch("read_file", {"path": "note.md"})["content"] == "main"
    with pytest.raises(WorkspaceError, match="not configured"):
        router.dispatch("read_file", {"workspace_id": "../../private", "path": "note.md"})


def test_invalid_workspace_configuration(tmp_path):
    a = tmp_path / "main"
    a.mkdir()
    for invalid in ({"default": str(a)}, {"UPPER": str(a)}, {"other": "relative/path"}):
        with pytest.raises(ValueError):
            WorkspaceRouter(a, invalid)
    with pytest.raises(ValueError):
        WorkspaceRouter(a, "not-a-dict")


def test_optional_multi_root_from_env(tmp_path, monkeypatch):
    a = tmp_path / "main"
    b = tmp_path / "secondary"
    a.mkdir()
    b.mkdir()
    monkeypatch.setenv("KRW_WORKSPACES_JSON", '{"secondary":"' + str(b) + '"}')
    r = WorkspaceRouter.from_env(a)
    assert len(r.list_workspaces()["workspaces"]) == 2
    assert r.dispatch("list_directory", {"workspace_id": "secondary", "path": "."})["entries"] == []


def test_move_and_delete_directory_lifecycle(tmp_path):
    w = Worker(tmp_path, write_enabled=True)
    w.create_directory({"path": "source/nested"})
    w.write_file({"path": "source/nested/note.md", "content": "hello"})
    moved = w.move_directory({"source": "source", "destination": "renamed"})
    assert moved["moved"] and not (tmp_path / "source").exists()
    assert (tmp_path / "renamed/nested/note.md").read_text() == "hello"
    with pytest.raises(WorkspaceError, match="not empty"):
        w.delete_directory({"path": "renamed"})
    deleted = w.delete_directory({"path": "renamed", "recursive": True})
    assert deleted["entries_deleted"] == 2
    assert not (tmp_path / "renamed").exists()
    w.create_directory({"path": "empty"})
    assert w.delete_directory({"path": "empty"})["deleted"]


def test_directory_move_rejects_existing_and_nested_target(tmp_path):
    w = Worker(tmp_path, write_enabled=True)
    w.create_directory({"path": "one"})
    w.create_directory({"path": "two"})
    with pytest.raises(WorkspaceError, match="exists"):
        w.move_directory({"source": "one", "destination": "two"})
    with pytest.raises(WorkspaceError, match="into itself"):
        w.move_directory({"source": "one", "destination": "one/nested"})
    assert (tmp_path / "one").exists()


def test_recursive_delete_rejects_symlinks_and_git(tmp_path):
    w = Worker(tmp_path, write_enabled=True)
    w.create_directory({"path": "unsafe"})
    (tmp_path / "unsafe" / "alias").symlink_to(tmp_path / "missing")
    with pytest.raises(WorkspaceError):
        w.delete_directory({"path": "unsafe", "recursive": True})
    assert (tmp_path / "unsafe" / "alias").is_symlink()
    (tmp_path / "gitfolder" / ".git").mkdir(parents=True)
    with pytest.raises(WorkspaceError, match="restricted"):
        w.delete_directory({"path": "gitfolder", "recursive": True})


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.mark.skipif(shutil.which("git") is None, reason="git missing")
def test_git_stage_commit_and_branch_switch(tmp_path):
    _git(tmp_path, "init", "-q")
    w = Worker(tmp_path, git_write_enabled=True)
    (tmp_path / "note.md").write_text("hello", encoding="utf-8")
    assert w.git_stage({"path": "note.md"})["staged"]
    # Keep the working file while removing it from the index.
    _git(tmp_path, "commit", "--allow-empty", "-q", "-m", "bootstrap", "--author", "Tester <test@example.org>")
    assert w.git_unstage({"path": "note.md"})["unstaged"]
    assert (tmp_path / "note.md").read_text() == "hello"
    assert w.git_stage({"path": "note.md"})["staged"]
    commit = w.git_commit({"message": "test: add note",
                           "author_name": "Remote Workspace",
                           "author_email": "remote@example.test"})
    assert len(commit["sha"]) == 40
    assert "note.md" in [e["path"] for e in w.git_status({})["entries"]] or w.git_status({})["entries"] == []
    assert w.git_branch_create({"branch": "feature-test"})["created"]
    assert "feature-test" in w.git_branches({})["branches"]
    assert w.git_branch_switch({"branch": "feature-test"})["switched"]
    assert w.git_branch_create({"branch": "another-feature"})["created"]
    with pytest.raises(WorkspaceError):
        w.git_branch_create({"branch": "--upload-pack=sh"})


@pytest.mark.skipif(shutil.which("git") is None, reason="git missing")
def test_git_write_permissions_are_independent(tmp_path):
    _git(tmp_path, "init", "-q")
    w = Worker(tmp_path, write_enabled=True)
    (tmp_path / "note.md").write_text("hi", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="disabled"):
        w.git_stage({"path": "note.md"})
    allowed = Worker(tmp_path, git_write_enabled=True)
    with pytest.raises(WorkspaceError, match="disabled"):
        allowed.git_push({"branch": "main"})
    with pytest.raises(WorkspaceError):
        allowed.git_commit({"message": "no staged files",
                            "author_name": "Tester", "author_email": "test@example.org"})


@pytest.mark.asyncio
async def test_git_write_flags_on_relay():
    state = State({"local-dev": "a"*48}, "b"*48)
    for name in ("git_stage", "git_commit", "git_branch_create", "git_branch_switch", "git_push"):
        with pytest.raises(HTTPException) as err:
            await state.submit(Dispatch(device_id="local-dev", operation=name))
        assert err.value.status_code == 403
    state = State({"local-dev": "a"*48}, "b"*48,
                  git_writes_enabled=True, git_push_enabled=False)
    with pytest.raises(HTTPException) as err:
        await state.submit(Dispatch(device_id="local-dev", operation="git_push"))
    assert err.value.status_code == 403

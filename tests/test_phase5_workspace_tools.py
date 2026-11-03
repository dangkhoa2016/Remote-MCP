"""Phase 5 integration tests for workspace management and upgraded limits."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi import HTTPException

from agent.worker import Worker, WorkspaceError
from gateway.relay import Dispatch, State


def sha(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_directory_edit_search_move_delete_roundtrip(tmp_path: Path):
    worker = Worker(tmp_path, write_enabled=True, checks_enabled=True)
    directory = worker.dispatch("create_directory", {"path": "nested/docs"})
    assert directory["created"] == ["nested", "nested/docs"]
    assert worker.create_directory({"path": "nested/docs"})["already_exists"]

    first = worker.write_file({"path": "nested/docs/note.md", "content": "hello world\n"})
    assert first["action"] == "created"
    edited = worker.edit_file({
        "path": "nested/docs/note.md", "old_string": "world", "new_string": "Khoa"
    })
    assert edited["replacements"] == 1
    assert worker.read_file({"path": "nested/docs/note.md"})["content"] == "hello Khoa\n"

    found = worker.search_files({"path": "nested", "query": "Khoa", "mode": "content"})
    assert [(r["path"], r["line"]) for r in found["matches"]] == [
        ("nested/docs/note.md", 1)
    ]
    names = worker.search_files({"query": "note.md", "mode": "name"})
    assert names["matches"][0]["path"] == "nested/docs/note.md"

    moved = worker.move_file({
        "source": "nested/docs/note.md", "destination": "nested/docs/renamed.md"
    })
    assert moved["moved"] is True
    assert not (tmp_path / "nested/docs/note.md").exists()
    assert worker.read_file({"path": "nested/docs/renamed.md"})["content"] == "hello Khoa\n"
    assert worker.delete_file({"path": "nested/docs/renamed.md"})["deleted"] is True
    assert not (tmp_path / "nested/docs/renamed.md").exists()


def test_optional_hash_and_exact_replacement_guards(tmp_path: Path):
    worker = Worker(tmp_path, write_enabled=True)
    worker.write_file({"path": "note.txt", "content": "same same"})
    with pytest.raises(WorkspaceError, match="Expected 1 matches, found 2"):
        worker.edit_file({"path": "note.txt", "old_string": "same", "new_string": "other"})
    with pytest.raises(WorkspaceError, match="mismatch"):
        worker.delete_file({"path": "note.txt", "expected_sha256": "0" * 64})
    with pytest.raises(WorkspaceError, match="mismatch"):
        worker.move_file({"source": "note.txt", "destination": "moved.txt",
                          "expected_sha256": "0" * 64})
    assert (tmp_path / "note.txt").read_text() == "same same"
    updated = worker.edit_file({
        "path": "note.txt", "old_string": "same", "new_string": "other",
        "expected_replacements": 2, "expected_sha256": sha("same same")
    })
    assert updated["sha256"] == sha("other other")
    assert worker.delete_file({"path": "note.txt", "expected_sha256": sha("other other")})["deleted"]


def test_move_refuses_existing_target(tmp_path: Path):
    worker = Worker(tmp_path, write_enabled=True)
    worker.write_file({"path": "a.md", "content": "source"})
    worker.write_file({"path": "b.md", "content": "destination"})
    with pytest.raises(WorkspaceError, match="exists"):
        worker.move_file({"source": "a.md", "destination": "b.md"})
    assert (tmp_path / "a.md").read_text() == "source"
    assert (tmp_path / "b.md").read_text() == "destination"


def test_disabled_writes_still_allow_search(tmp_path: Path):
    (tmp_path / "guide.md").write_text("hello\n", encoding="utf-8")
    worker = Worker(tmp_path)
    assert worker.search_files({"query": "hello"})["matches"]
    for name, args in (
        ("edit_file", {"path": "guide.md", "old_string": "hello", "new_string": "hi"}),
        ("create_directory", {"path": "new"}),
        ("move_file", {"source": "guide.md", "destination": "other.md"}),
        ("delete_file", {"path": "guide.md"}),
    ):
        with pytest.raises(WorkspaceError, match="disabled"):
            worker.dispatch(name, args)


def test_nested_symlink_and_traversal_are_not_accessible(tmp_path: Path):
    worker = Worker(tmp_path, write_enabled=True)
    (tmp_path / "safe").mkdir()
    outside = tmp_path.parent / "krw-phase5-outside.txt"
    outside.write_text("untouched", encoding="utf-8")
    (tmp_path / "safe" / "alias.txt").symlink_to(outside)
    for action, args in (
        ("edit_file", {"path": "safe/alias.txt", "old_string": "x", "new_string": "y"}),
        ("delete_file", {"path": "safe/alias.txt"}),
        ("move_file", {"source": "safe/alias.txt", "destination": "new.txt"}),
        ("create_directory", {"path": "../escape"}),
        ("search_files", {"path": "../", "query": "untouched"}),
    ):
        with pytest.raises(WorkspaceError):
            worker.dispatch(action, args)
    assert outside.read_text() == "untouched"


def test_larger_text_files_are_supported(tmp_path: Path):
    worker = Worker(tmp_path, write_enabled=True)
    text = "x" * 150_000
    result = worker.write_file({"path": "large.txt", "content": text})
    assert result["bytes_written"] == 150_000
    read = worker.read_file({"path": "large.txt", "max_bytes": 200_000})
    assert read["content"] == text and not read["truncated"]
    assert worker.file_sha256({"path": "large.txt"})["sha256"] == sha(text)


@pytest.mark.asyncio
async def test_relay_gates_new_write_operations():
    state = State({"local-dev": "a" * 48}, "b" * 48, writes_enabled=False)
    for operation in ("edit_file", "create_directory", "move_file", "delete_file"):
        with pytest.raises(HTTPException) as exc:
            await state.submit(Dispatch(device_id="local-dev", operation=operation, arguments={}))
        assert exc.value.status_code == 403

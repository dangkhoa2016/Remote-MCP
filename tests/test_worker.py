import pytest
from pathlib import Path

from agent.worker import Worker, WorkspaceError


def test_read_and_list(tmp_path):
    (tmp_path / "hello.txt").write_text("xin chào", encoding="utf-8")
    (tmp_path / ".env").write_text("secret=do-not-read")
    worker = Worker(tmp_path)
    entries = worker.list_directory({"path": "."})["entries"]
    assert "hello.txt" in [entry["name"] for entry in entries]
    assert ".env" not in [entry["name"] for entry in entries]
    assert worker.read_file({"path": "hello.txt", "max_bytes": 100})["content"] == "xin chào"


def test_block_traversal_secrets_symlinks(tmp_path):
    (tmp_path / "ok.txt").write_text("good")
    (tmp_path / "outside.txt").symlink_to("/etc/hosts")
    worker = Worker(tmp_path)
    for path in ["../etc/passwd", "/etc/passwd", ".env", "foo/.ssh/id_rsa", "outside.txt", "private.pem"]:
        with pytest.raises(WorkspaceError):
            worker.read_file({"path": path})


def test_commands_restricted(tmp_path):
    worker = Worker(tmp_path)
    with pytest.raises(WorkspaceError, match="disabled"):
        worker.execute_command({"command_id": "python_version"})
    enabled = Worker(tmp_path, commands_enabled=True)
    with pytest.raises(WorkspaceError, match="allowlist"):
        enabled.execute_command({"command_id": "rm -rf /"})
    output = enabled.execute_command({"command_id": "python_version"})
    assert output["exit_code"] == 0
    assert output["stdout"] or output["stderr"]


def test_file_size_limit(tmp_path):
    (tmp_path / "large.txt").write_text("z" * 40000)
    worker = Worker(tmp_path)
    result = worker.read_file({"path": "large.txt", "max_bytes": 8000})
    assert len(result["content"]) == 8000 and result["truncated"]
    with pytest.raises(WorkspaceError):
        worker.read_file({"path": "large.txt", "max_bytes": 262145})

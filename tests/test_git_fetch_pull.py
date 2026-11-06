"""Git fetch/pull integration without networking, with exact command safety checks."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from agent.git_readonly import GitReadOnlyError
from agent.git_write import GitWrite
from agent.worker import Worker, WorkspaceError
from gateway.relay import State, Dispatch


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, text=True,
                            capture_output=True, check=True)
    return result.stdout.strip()


@pytest.fixture()
def origin(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("git unavailable")
    bare = tmp_path / "remote.git"
    bare.mkdir()
    git(bare, "init", "-q", "--bare")
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    git(seed, "config", "user.email", "ci@example.test")
    git(seed, "config", "user.name", "CI")
    (seed / "README.md").write_text("release one\n")
    git(seed, "add", "README.md")
    git(seed, "commit", "-q", "-m", "release-one")
    git(seed, "remote", "add", "origin", str(bare))
    git(seed, "push", "-q", "-u", "origin", "main")

    # Local transport is allowed only in test to avoid external network calls.
    # Production _network_git permits ONLY credential-free HTTPS GitHub.
    def local_transport(self, args, *, timeout=18):
        self._invoke(["-c", "protocol.file.allow=always", *args], timeout=timeout)
    monkeypatch.setattr(GitWrite, "_network_git", local_transport)
    return bare, seed


def new_workspace(tmp_path, remote):
    repo = tmp_path / ("device-" + str(len(list(tmp_path.glob("device-*")))))
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "remote", "add", "origin", str(remote))
    return repo


def test_fetch_then_first_pull_unborn_repository(origin, tmp_path):
    bare, seed = origin
    repo = new_workspace(tmp_path, bare)
    w = Worker(repo, git_write_enabled=True)
    assert w.git_fetch({})["working_tree_changed"] is False
    assert not (repo / "README.md").exists()
    assert git(repo, "rev-parse", "refs/remotes/origin/main") == git(seed, "rev-parse", "HEAD")
    answer = w.git_pull({"branch": "main"})
    assert answer["initial_checkout"] is True
    assert answer["fast_forward_only"] is True
    assert git(repo, "branch", "--show-current") == "main"
    assert (repo / "README.md").read_text() == "release one\n"
    assert w.git_pull({"branch": "main"})["initial_checkout"] is False


def test_pull_fast_forward_and_rejects_dirty_and_divergence(origin, tmp_path):
    bare, seed = origin
    repo = new_workspace(tmp_path, bare)
    w = Worker(repo, git_write_enabled=True)
    w.git_pull({})
    # A new remote commit is fast-forwardable.
    (seed / "README.md").write_text("release two\n")
    git(seed, "commit", "-a", "-q", "-m", "release-two")
    git(seed, "push", "-q", "origin", "main")
    w.git_fetch({})
    assert (repo / "README.md").read_text() == "release one\n"
    answer = w.git_pull({})
    assert answer["initial_checkout"] is False
    assert git(repo, "rev-parse", "HEAD") == git(seed, "rev-parse", "HEAD")
    assert (repo / "README.md").read_text() == "release two\n"

    # Never overwrite uncommitted edits or even unexpected untracked files.
    (repo / "README.md").write_text("dirty\n")
    with pytest.raises(WorkspaceError, match="clean working tree"):
        w.git_pull({})
    assert (repo / "README.md").read_text() == "dirty\n"
    git(repo, "restore", "--", "README.md")
    (repo / "untracked.md").write_text("keep")
    with pytest.raises(WorkspaceError, match="clean working tree"):
        w.git_pull({})
    (repo / "untracked.md").unlink()

    # Fast-forward only: a local commit not on remote must remain intact.
    git(repo, "config", "user.name", "CI")
    git(repo, "config", "user.email", "ci@example.test")
    (repo / "local.md").write_text("device")
    git(repo, "add", "local.md")
    git(repo, "commit", "-q", "-m", "local")
    head_before = git(repo, "rev-parse", "HEAD")
    (seed / "remote.md").write_text("origin")
    git(seed, "add", "remote.md")
    git(seed, "commit", "-q", "-m", "remote")
    git(seed, "push", "-q", "origin", "main")
    with pytest.raises(WorkspaceError, match="divergent history; fast-forward is not possible"):
        w.git_pull({})
    assert git(repo, "rev-parse", "HEAD") == head_before
    assert not (repo / "remote.md").exists()


def test_pull_and_git_status_agree_about_nested_untracked_files(origin, tmp_path):
    bare, _ = origin
    repo = new_workspace(tmp_path, bare)
    w = Worker(repo, git_write_enabled=True)
    w.git_pull({"branch": "main"})
    folder = repo / "benchmarks" / "qwen-image-q4ks-t4x2"
    folder.mkdir(parents=True)
    (folder / "benchmark.bin").write_bytes(b"temporary")
    summary = w.git_status({})
    assert summary["working_tree_clean"] is False
    assert summary["hidden_changes"] is False
    assert {"state": "??", "path": "benchmarks/"} in summary["entries"]
    head_before = git(repo, "rev-parse", "HEAD")
    with pytest.raises(WorkspaceError, match="clean working tree"):
        w.git_pull({"branch": "main"})
    assert git(repo, "rev-parse", "HEAD") == head_before
    assert (folder / "benchmark.bin").read_bytes() == b"temporary"


def test_pull_wrong_current_branch_is_rejected(origin, tmp_path):
    bare, _ = origin
    repo = new_workspace(tmp_path, bare)
    w = Worker(repo, git_write_enabled=True)
    w.git_pull({"branch": "main"})
    git(repo, "switch", "-q", "-c", "feature")
    with pytest.raises(WorkspaceError, match="cannot switch branches"):
        w.git_pull({"branch": "main"})
    with pytest.raises(WorkspaceError, match="Invalid branch"):
        w.git_pull({"branch": "--upload-pack=sh"})


def test_fetch_pull_require_agent_git_write_permission(origin, tmp_path):
    bare, _ = origin
    repo = new_workspace(tmp_path, bare)
    w = Worker(repo)
    with pytest.raises(WorkspaceError, match="disabled"):
        w.git_fetch({})
    with pytest.raises(WorkspaceError, match="disabled"):
        w.git_pull({})


def test_network_origin_validation_and_explicit_flags(origin, tmp_path, monkeypatch):
    bare, _ = origin
    repo = new_workspace(tmp_path, bare)
    w = Worker(repo, git_write_enabled=True)
    # Restore production transport, which does not allow file:// or ext::.
    monkeypatch.undo()
    with pytest.raises(WorkspaceError, match="HTTPS GitHub"):
        w.git_fetch({})
    git(repo, "remote", "set-url", "origin", "ext::danger")
    with pytest.raises(WorkspaceError, match="HTTPS GitHub"):
        w.git_pull({})

    git(repo, "remote", "set-url", "origin", "https://github.com/org/repo.git")
    obj = GitWrite(repo, w.path)
    assert obj._github_origin() == "https://github.com/org/repo.git"
    git(repo, "remote", "set-url", "origin", "https://attacker.example/repo")
    with pytest.raises(Exception, match="HTTPS GitHub"):
        obj._github_origin()
    git(repo, "remote", "set-url", "origin", "https://name:short@github.com/org/repo.git")
    with pytest.raises(Exception, match="Invalid Agent GitHub credential"):
        obj._github_origin()


@pytest.mark.asyncio
async def test_gateway_rejects_fetch_pull_when_writes_disabled():
    state = State({"d": "t" * 40}, "c" * 40, git_writes_enabled=False)
    for operation in ("git_fetch", "git_pull"):
        with pytest.raises(HTTPException) as exc:
            await state.submit(Dispatch(device_id="d", operation=operation))
        assert exc.value.status_code == 403


def test_private_github_origins_are_sanitized(tmp_path):
    repo = tmp_path / "workspace"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "remote", "add", "origin", "https://github.com/o/r.git")
    obj = GitWrite(repo, lambda path: repo / path)
    for url, credential in (
        ("https://github.com/owner/private.git", None),
        ("https://x-access-token:ghp_example_token_123@github.com/owner/private.git",
         "ghp_example_token_123"),
        ("https://ghp_example_token_123@github.com/owner/private.git",
         "ghp_example_token_123"),
        ("git@github.com:owner/private.git", None),
        ("ssh://git@github.com/owner/private.git", None),
    ):
        git(repo, "remote", "set-url", "origin", url)
        assert obj._github_remote() == ("https://github.com/owner/private.git", credential)
        assert obj._github_origin() == "https://github.com/owner/private.git"
    for url in (
        "https://bad.example/owner/private.git",
        "http://github.com/owner/private.git",
        "https://github.com:8443/owner/private.git",
        "https://github.com/owner/private.git?token=foo",
        "ext::bad",
    ):
        git(repo, "remote", "set-url", "origin", url)
        with pytest.raises(Exception, match="HTTPS GitHub"):
            obj._github_origin()


def test_network_git_uses_canonical_url_not_credentialed_origin(tmp_path, monkeypatch):
    repo = tmp_path / "workspace"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "remote", "add", "origin",
        "https://x-access-token:ghp_example_token_123@github.com/owner/private.git")
    for name in ("KRW_GIT_PUSH_TOKEN", "KRW_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    obj = GitWrite(repo, lambda path: repo / path)
    original = obj._invoke
    calls = []

    def capture(args, *, timeout=12, token=None):
        if args == ["remote", "get-url", "origin"] or args == [
            "ls-remote", "--get-url", "https://github.com/owner/private.git"
        ]:
            return original(args, timeout=timeout, token=token)
        calls.append((args, token))
        return b""

    monkeypatch.setattr(obj, "_invoke", capture)
    obj._network_git(["fetch", "--no-tags", "origin"])
    args, token = calls[0]
    assert len(calls) == 1
    assert token == "ghp_example_token_123"
    assert "ghp_example_token_123" not in repr(args)
    assert "https://github.com/owner/private.git" in args
    assert "+refs/heads/*:refs/remotes/origin/*" in args
    assert "origin" not in args
    assert "protocol.allow=never" in args


def test_network_git_blocks_url_rewrite(tmp_path):
    repo = tmp_path / "workspace"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "remote", "add", "origin", "https://github.com/owner/private.git")
    git(repo, "config", "url.https://bad.example/.insteadOf", "https://github.com/")
    obj = GitWrite(repo, lambda path: repo / path)
    with pytest.raises(Exception, match="HTTPS GitHub|URL rewrite"):
        obj._network_git(["fetch", "--no-tags", "origin"])


def test_gh_auth_and_env_token_precedence(tmp_path, monkeypatch):
    repo = tmp_path / "workspace"
    repo.mkdir()
    git(repo, "init", "-q")
    obj = GitWrite(repo, lambda path: repo / path)
    for name in ("KRW_GIT_PUSH_TOKEN", "KRW_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(obj, "_gh_token", lambda: "ghp_from_gh_123456")
    assert obj._fetch_token() == "ghp_from_gh_123456"
    assert obj._fetch_token("ghp_from_url_123456") == "ghp_from_url_123456"
    monkeypatch.setenv("GH_TOKEN", "ghp_from_env_123456")
    assert obj._fetch_token() == "ghp_from_env_123456"
    monkeypatch.setenv("KRW_GIT_PUSH_TOKEN", "ghp_agent_env_123456")
    assert obj._fetch_token() == "ghp_agent_env_123456"


def test_gh_auth_reads_agent_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("agent.git_write.shutil.which",
                        lambda name, path=None: "/usr/bin/gh")
    captured = {}

    def fake_run(argv, **kwargs):
        captured.update({"argv": argv, "env": kwargs["env"]})
        return subprocess.CompletedProcess(argv, 0, stdout="ghp_sample_123456\n", stderr="")

    monkeypatch.setattr("agent.git_write.subprocess.run", fake_run)
    assert GitWrite._gh_token() == "ghp_sample_123456"
    assert captured["argv"] == ["/usr/bin/gh", "auth", "token", "--hostname", "github.com"]
    assert captured["env"]["HOME"] == str(tmp_path)


def test_git_pull_reports_only_known_non_fast_forward_error(tmp_path, monkeypatch):
    """Precise diagnostics must not copy untrusted Git stderr or affect fetch."""
    repo = tmp_path / "workspace"
    repo.mkdir()
    git(repo, "init", "-q")
    obj = GitWrite(repo, lambda path: repo / path)
    pull_args = ["-c", "protocol.allow=never", "pull", "--ff-only",
                 "--no-rebase", "--no-tags", "origin", "main"]

    failures = [
        (b"hint: Diverging branches can't be fast-forwarded.\n"
         b"fatal: Not possible to fast-forward, aborting.\n",
         "Pull rejected: divergent history; fast-forward is not possible"),
        (b"fatal: refusing to merge unrelated histories\n",
         "Pull rejected: divergent history; fast-forward is not possible"),
        (b"remote: token=GH_SECRET_EXAMPLE\nfatal: Authentication failed\n",
         "Git operation failed; check repository state, identity and permissions"),
    ]
    for stderr, message in failures:
        monkeypatch.setattr(
            "agent.git_write.subprocess.run",
            lambda args, **kwargs: subprocess.CompletedProcess(
                args, 128, stdout=b"", stderr=stderr,
            ),
        )
        with pytest.raises(GitReadOnlyError) as error:
            obj._invoke(pull_args)
        assert str(error.value) == message
        assert "GH_SECRET_EXAMPLE" not in str(error.value)
        assert "remote:" not in str(error.value)

    # Same fatal line from a fetch operation is not misclassified as a pull.
    stderr = b"fatal: Not possible to fast-forward, aborting.\n"
    with pytest.raises(GitReadOnlyError, match="Git operation failed"):
        obj._invoke(["fetch", "--no-tags", "origin"])

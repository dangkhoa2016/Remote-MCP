"""Fixed-argument Git management for explicitly authorized local repositories.

Git writes are enabled separately from file writes. No shell strings, arbitrary
flags, force pushes, hooks or external remote helpers. Push supports HTTPS
GitHub with a private Agent token only.
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from agent.git_readonly import GitReadOnly, GitReadOnlyError

_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,120}\Z")
_EMAIL = re.compile(r"[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+\Z")


class GitWrite(GitReadOnly):
    def _invoke(self, args: list[str], *, timeout: int = 12,
                token: str | None = None) -> bytes:
        env = {
            "PATH": "/usr/bin:/bin", "HOME": "/", "LC_ALL": "C.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull, "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat",
            "GIT_NO_LAZY_FETCH": "1", "GIT_ASKPASS": "/bin/false",
        }
        if token is not None:
            encoded = base64.b64encode(("x-access-token:" + token).encode()).decode()
            env.update({
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic " + encoded,
            })
        cmd = [
            self.git, "-c", "core.hooksPath=/dev/null",
            "-c", "core.fsmonitor=false", "-c", "commit.gpgsign=false",
            "-c", "tag.gpgsign=false", "-c", "credential.helper=",
            "-c", "protocol.ext.allow=never", "-c", "protocol.file.allow=never",
            *args,
        ]
        try:
            process = subprocess.run(cmd, cwd=self.root, env=env, capture_output=True,
                                     stdin=subprocess.DEVNULL, timeout=timeout, check=False)
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise GitReadOnlyError("Git operation unavailable or timed out") from exc
        if process.returncode:
            # Never reflect credential-bearing remote error messages.
            raise GitReadOnlyError("Git operation failed; check repository state, identity and permissions")
        if len(process.stdout) > 65536:
            raise GitReadOnlyError("Git output exceeds limit")
        return process.stdout

    def _branch(self, branch: str) -> str:
        if not isinstance(branch, str) or not _BRANCH.fullmatch(branch):
            raise GitReadOnlyError("Invalid branch name")
        self._invoke(["check-ref-format", "--branch", branch])
        return branch

    def _path(self, path: str) -> str:
        if not isinstance(path, str) or not 1 <= len(path) <= 400 or any(
                ord(c) < 32 or ord(c) == 127 for c in path):
            raise GitReadOnlyError("Invalid Git path")
        try:
            target = self.validate_path(path)
        except Exception as exc:
            raise GitReadOnlyError("Git path is restricted") from exc
        if target.is_symlink() or target.is_dir():
            raise GitReadOnlyError("Git path must be a file, or a deleted file")
        return target.relative_to(self.root).as_posix()

    def stage(self, path: str) -> dict:
        relative = self._path(path)
        self._invoke(["add", "--", relative])
        return {"path": relative, "staged": True}

    def unstage(self, path: str) -> dict:
        relative = self._path(path)
        self._invoke(["restore", "--staged", "--", relative])
        return {"path": relative, "unstaged": True}

    def commit(self, message: str, author_name: str, author_email: str) -> dict:
        if (not isinstance(message, str) or not 1 <= len(message) <= 500 or
                any(ord(c) < 32 and c != "\n" for c in message)):
            raise GitReadOnlyError("Invalid commit message")
        if (not isinstance(author_name, str) or not 1 <= len(author_name) <= 100
                or any(ord(c) < 32 for c in author_name) or
                not isinstance(author_email, str) or not _EMAIL.fullmatch(author_email)):
            raise GitReadOnlyError("Invalid author identity")
        # Do not commit pre-staged private files, even if staged outside KRW.
        staged = self._invoke(["diff", "--cached", "--name-only", "-z", "--no-renames"])
        if not staged:
            raise GitReadOnlyError("No staged changes")
        for item in staged.split(b"\0"):
            if not item:
                continue
            try:
                self._path(item.decode("utf-8"))
            except (UnicodeDecodeError, GitReadOnlyError) as exc:
                raise GitReadOnlyError("Staged path is not authorized") from exc
        self._invoke([
            "-c", "user.name=" + author_name, "-c", "user.email=" + author_email,
            "commit", "--no-gpg-sign", "-m", message,
        ])
        sha = self._invoke(["rev-parse", "HEAD"]).decode().strip()
        return {"committed": True, "sha": sha, "message": message[:200]}

    def branch_create(self, branch: str) -> dict:
        branch = self._branch(branch)
        self._invoke(["branch", branch])
        return {"branch": branch, "created": True}

    def branch_switch(self, branch: str) -> dict:
        branch = self._branch(branch)
        # Untracked files do not automatically make a branch switch unsafe.
        # Reject all tracked modifications, staged changes and merge conflicts.
        # Git's regular non-force switch refuses any untracked-file collision
        # with a file that the target branch would check out.
        status = self._invoke([
            "status", "--porcelain=v1", "-z", "--no-renames",
            "--untracked-files=all",
        ])
        for item in status.split(b"\0"):
            if item and not item.startswith(b"?? "):
                raise GitReadOnlyError(
                    "Tracked or staged changes must be resolved before switching branches"
                )
        self._invoke(["switch", "--", branch])
        return {"branch": branch, "switched": True}

    def push(self, branch: str, token: str) -> dict:
        branch = self._branch(branch)
        if not isinstance(token, str) or len(token) < 12 or len(token) > 1024:
            raise GitReadOnlyError("GitHub push token not configured on Agent")
        raw = self._invoke(["remote", "get-url", "origin"]).decode("utf-8").strip()
        parsed = urlsplit(raw)
        if (parsed.scheme != "https" or parsed.netloc != "github.com"
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment
                or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", parsed.path)):
            raise GitReadOnlyError("Push requires a credential-free HTTPS GitHub origin")
        current = self._invoke(["branch", "--show-current"]).decode().strip()
        if current != branch:
            raise GitReadOnlyError("Only the current branch may be pushed")
        self._invoke(["push", "origin", "refs/heads/" + branch + ":refs/heads/" + branch],
                     timeout=19, token=token)
        return {"branch": branch, "pushed": True, "remote": "origin"}

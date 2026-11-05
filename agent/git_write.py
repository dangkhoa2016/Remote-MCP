"""Fixed-argument Git management for explicitly authorized local repositories.

Git writes are enabled separately from file writes. No shell strings, arbitrary
flags, force pushes, hooks or external remote helpers. Network Git operations
are restricted to GitHub using canonical HTTPS transport. Private repos may use
Agent tokens, gh CLI auth or HTTPS URL tokens; credentials stay on Agent.
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

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
            # Match only known Git-generated fatal lines; NEVER relay stderr,
            # which can contain remote URLs or authentication details.
            # The pull command has already been restricted to --ff-only.
            if "pull" in args and "--ff-only" in args:
                fatal_lines = process.stderr[-8192:].splitlines()
                if any(line.startswith((
                        b"fatal: Not possible to fast-forward",
                        b"fatal: refusing to merge unrelated histories",
                )) for line in fatal_lines):
                    raise GitReadOnlyError(
                        "Pull rejected: divergent history; fast-forward is not possible"
                    )
            raise GitReadOnlyError(
                "Git operation failed; check repository state, identity and permissions"
            )
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

    @staticmethod
    def _valid_token(token: str) -> str:
        if not isinstance(token, str) or not 12 <= len(token) <= 1024 or any(
                ord(c) <= 32 or ord(c) == 127 for c in token):
            raise GitReadOnlyError("Invalid Agent GitHub credential")
        return token

    def _github_remote(self) -> tuple[str, str | None]:
        """Canonical HTTPS GitHub URL and any token in the existing origin."""
        raw = self._invoke(["remote", "get-url", "origin"]).decode("utf-8").strip()
        embedded = None
        if raw.startswith("git@github.com:"):
            path = "/" + raw[len("git@github.com:"):]
        else:
            try:
                parsed = urlsplit(raw)
                if parsed.hostname != "github.com" or parsed.port is not None or (
                        parsed.query or parsed.fragment):
                    raise ValueError("Unsupported origin")
                if parsed.scheme == "https":
                    path = parsed.path
                    if parsed.password is not None:
                        embedded = unquote(parsed.password)
                    elif parsed.username is not None:
                        embedded = unquote(parsed.username)
                elif (parsed.scheme == "ssh" and parsed.username == "git"
                      and parsed.password is None):
                    path = parsed.path
                else:
                    raise ValueError("Unsupported origin")
            except ValueError as exc:
                raise GitReadOnlyError(
                    "Network Git requires a valid HTTPS GitHub or git@github.com origin"
                ) from exc
        if not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", path):
            raise GitReadOnlyError(
                "Network Git requires a valid HTTPS GitHub or git@github.com origin"
            )
        if embedded is not None:
            self._valid_token(embedded)
        return "https://github.com" + path, embedded

    def _github_origin(self) -> str:
        return self._github_remote()[0]

    @staticmethod
    def _gh_token() -> str | None:
        # Git ignores global credential helpers; read gh credentials separately.
        gh = shutil.which("gh", path="/usr/local/bin:/usr/bin:/bin:/opt/conda/bin")
        if not gh:
            return None
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": os.getenv("HOME", "/"),
            "GH_PROMPT_DISABLED": "1",
        }
        if os.getenv("GH_CONFIG_DIR"):
            env["GH_CONFIG_DIR"] = os.environ["GH_CONFIG_DIR"]
        try:
            result = subprocess.run(
                [gh, "auth", "token", "--hostname", "github.com"],
                env=env, stdin=subprocess.DEVNULL, capture_output=True,
                text=True, timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    def _fetch_token(self, embedded: str | None = None,
                     explicit: str | None = None) -> str | None:
        token = (explicit or os.getenv("KRW_GIT_PUSH_TOKEN")
                 or os.getenv("KRW_GITHUB_TOKEN") or os.getenv("GH_TOKEN")
                 or os.getenv("GITHUB_TOKEN") or embedded or self._gh_token())
        return self._valid_token(token) if token else None

    def _network_git(self, args: list[str], *, timeout: int = 18,
                     require_token: bool = False, explicit_token: str | None = None) -> None:
        origin, embedded = self._github_remote()
        token = self._fetch_token(embedded, explicit_token)
        if require_token and token is None:
            raise GitReadOnlyError("GitHub push token not configured on Agent")

        # Detect local url.*.insteadOf rules before network access.
        resolved = self._invoke(["ls-remote", "--get-url", origin]).decode().strip()
        if resolved != origin:
            raise GitReadOnlyError("GitHub URL rewrite is not allowed")

        # Never use 'origin' for transport: -c remote.origin.url appends to
        # multi-valued URLs and might still use the credential-bearing entry.
        if args == ["fetch", "--no-tags", "origin"]:
            command = ["fetch", "--no-tags", origin,
                       "+refs/heads/*:refs/remotes/origin/*"]
        elif (len(args) == 6 and args[:5] ==
              ["pull", "--ff-only", "--no-rebase", "--no-tags", "origin"]):
            command = [*args[:4], origin, args[5]]
        elif len(args) == 3 and args[:2] == ["push", "origin"]:
            command = ["push", origin, args[2]]
        else:
            raise GitReadOnlyError("Unsupported network Git operation")
        self._invoke([
            "-c", "protocol.allow=never",
            "-c", "protocol.https.allow=always",
            "-c", "http.followRedirects=false",
            *command,
        ], timeout=timeout, token=token)

    def fetch(self) -> dict:
        # Updates remote-tracking refs only. Never checkout, merge, or rebase.
        self._network_git(["fetch", "--no-tags", "origin"], timeout=18)
        return {"remote": "origin", "fetched": True, "working_tree_changed": False}

    def pull(self, branch: str = "main") -> dict:
        branch = self._branch(branch)
        # Require completely clean worktree, including untracked files. A Git
        # checkout could otherwise overwrite or disclose unexpected local data.
        if self._invoke([
                "status", "--porcelain=v1", "-z", "--no-renames",
                "--untracked-files=all",
        ]):
            raise GitReadOnlyError("Pull requires a clean working tree (including untracked files)")
        current = self._invoke(["symbolic-ref", "--quiet", "--short", "HEAD"]).decode().strip()
        try:
            self._invoke(["rev-parse", "--verify", "HEAD"])
            has_commits = True
        except GitReadOnlyError:
            has_commits = False
        if has_commits:
            if current != branch:
                raise GitReadOnlyError("Pull cannot switch branches; checkout the requested branch first")
            self._network_git(["pull", "--ff-only", "--no-rebase", "--no-tags",
                               "origin", branch], timeout=18)
        else:
            # A freshly 'git init' workspace has no local history. This is an
            # initial checkout of origin/<branch>, not a merge/rebase.
            self.fetch()
            self._invoke(["rev-parse", "--verify", "refs/remotes/origin/" + branch])
            self._invoke(["switch", "--create", branch, "--track", "origin/" + branch])
        head = self._invoke(["rev-parse", "--verify", "HEAD"]).decode().strip()
        return {"remote": "origin", "branch": branch, "pulled": True,
                "fast_forward_only": True, "initial_checkout": not has_commits, "head": head}

    def push(self, branch: str, token: str = "") -> dict:
        branch = self._branch(branch)
        current = self._invoke(["branch", "--show-current"]).decode().strip()
        if current != branch:
            raise GitReadOnlyError("Only the current branch may be pushed")
        self._network_git(
            ["push", "origin", "refs/heads/" + branch + ":refs/heads/" + branch],
            timeout=19, require_token=True, explicit_token=token or None,
        )
        return {"branch": branch, "pushed": True, "remote": "origin"}

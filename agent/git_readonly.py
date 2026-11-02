"""Restricted read-only Git queries scoped to exactly one workspace repository.

No shell strings, user-provided flags, user-provided refs or Git writes.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable


class GitReadOnlyError(Exception):
    pass


ALLOWED_SUFFIXES = frozenset({'.py', '.md', '.sh', '.txt', '.json', '.toml', '.ini', '.yml', '.yaml', '.rb', '.erb', '.js', '.ts', '.css', '.html', '.sql'})
MAX_RESULTS = 150
MAX_DIFF_CHARS = 12_000


class GitReadOnly:
    def __init__(self, root: Path, validate_path: Callable[[str], Path]):
        self.root = root
        self.validate_path = validate_path
        gitdir = root / '.git'
        # A worktree .git pointer may refer to a directory outside workspace.
        if gitdir.is_symlink() or not gitdir.is_dir():
            raise GitReadOnlyError('Git queries require an in-workspace .git directory')
        if not gitdir.resolve().is_relative_to(root):
            raise GitReadOnlyError('Git metadata escapes workspace')
        self.git = shutil.which('git')
        if not self.git:
            raise GitReadOnlyError('Git executable is not installed')

    def _run(self, args: list[str], *, max_output: int = 131072) -> bytes:
        # Minimal environment avoids attacker-supplied GIT_* overrides.
        env = {
            'PATH': '/usr/bin:/bin', 'HOME': '/', 'LC_ALL': 'C.UTF-8',
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_CONFIG_SYSTEM': os.devnull, 'GIT_OPTIONAL_LOCKS': '0',
            'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_TERMINAL_PROMPT': '0',
            'GIT_PAGER': 'cat', 'GIT_NO_LAZY_FETCH': '1',
        }
        argv = [self.git, '--no-optional-locks', '-c', 'core.fsmonitor=false',
                '-c', 'core.untrackedCache=false', '-c', 'core.hooksPath=/dev/null',
                *args]
        try:
            result = subprocess.run(
                argv, cwd=self.root, env=env, capture_output=True,
                timeout=10, stdin=subprocess.DEVNULL, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitReadOnlyError('Git query timed out') from exc
        except OSError as exc:
            raise GitReadOnlyError('Git query unavailable') from exc
        if result.returncode != 0:
            raise GitReadOnlyError('Git query failed (check whether repo is initialized)')
        if len(result.stdout) > max_output:
            raise GitReadOnlyError('Git output exceeds safe limit')
        return result.stdout

    def _safe_path(self, path: str, *, allow_missing: bool = False) -> str:
        if not isinstance(path, str) or not path or len(path) > 400:
            raise GitReadOnlyError('Invalid Git file path')
        # Reuse the same workspace security boundary as read_file.
        try:
            target = self.validate_path(path)
        except Exception as exc:
            raise GitReadOnlyError('Git path is restricted') from exc
        if target.is_symlink() or (not allow_missing and not target.is_file()) or target.is_dir():
            raise GitReadOnlyError('Git path must be a regular file')
        relative = target.relative_to(self.root).as_posix()
        if any(ord(c) < 32 or ord(c) == 127 for c in relative):
            raise GitReadOnlyError('Control characters are prohibited in Git paths')
        if target.suffix.lower() not in ALLOWED_SUFFIXES:
            raise GitReadOnlyError('File extension not approved for Git diff')
        return relative

    def status(self) -> dict:
        raw = self._run(['status', '--porcelain=v1', '-z', '--no-renames', '--untracked-files=normal'])
        entries = []
        for record in raw.split(b'\x00'):
            if not record:
                continue
            if len(record) < 4 or record[2:3] != b' ':
                raise GitReadOnlyError('Unexpected Git status output')
            try:
                path = record[3:].decode('utf-8', errors='strict')
                safe_path = self._safe_path(path, allow_missing=True)
            except (UnicodeDecodeError, GitReadOnlyError):
                # Never disclose rejected/hidden/symlink entries.
                continue
            entries.append({'state': record[:2].decode('ascii', 'replace'), 'path': safe_path})
            if len(entries) >= MAX_RESULTS:
                break
        return {'entries': entries, 'limited': len(entries) >= MAX_RESULTS, 'read_only': True}

    def diff(self, path: str, staged: bool = False) -> dict:
        if type(staged) is not bool:
            raise GitReadOnlyError('Invalid staged flag')
        safe_path = self._safe_path(path)
        args = ['diff', '--no-ext-diff', '--no-textconv', '--no-color', '--unified=3']
        if staged:
            args.append('--cached')
        args += ['--', safe_path]
        data = self._run(args, max_output=65536)
        try:
            text = data.decode('utf-8', errors='strict')
        except UnicodeDecodeError as exc:
            raise GitReadOnlyError('Binary/invalid-UTF8 diff rejected') from exc
        # Bound lines and characters. Never invoke external diff drivers.
        if '\x00' in text:
            raise GitReadOnlyError('Binary diff rejected')
        return {'path': safe_path, 'staged': staged, 'diff': text[:MAX_DIFF_CHARS],
                'truncated': len(text) > MAX_DIFF_CHARS, 'read_only': True}

    def log(self, count: int = 10) -> dict:
        if type(count) is not int or not 1 <= count <= 20:
            raise GitReadOnlyError('count must be between 1 and 20')
        raw = self._run(['log', '-n', str(count), '--no-show-signature',
                         '--format=%H%x1f%h%x1f%s%x1f%aI%x1e'], max_output=24000)
        entries = []
        for record in raw.decode('utf-8', 'replace').split('\x1e'):
            fields = record.strip('\r\n').split('\x1f')
            if len(fields) != 4 or not re.fullmatch('[a-f0-9]{40,64}', fields[0]):
                continue
            subject = ''.join(c for c in fields[2] if c.isprintable())[:200]
            entries.append({'sha': fields[0], 'short_sha': fields[1],
                            'subject': subject, 'author_date': fields[3][:40]})
        return {'commits': entries, 'read_only': True}

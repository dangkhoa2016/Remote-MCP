"""Phase 4-C: scoped text writes and NON-EXECUTING syntax checks.

Worker.path validates secrets/traversal. Descriptor-relative O_NOFOLLOW
traversal prevents symlink races. SHA-256 conflict detection is best-effort
against other local processes; it is not an OS transactional compare-and-swap.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import secrets
import stat
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 Agent
    import tomli as tomllib
from pathlib import Path
from typing import Callable

MAX_WRITE_BYTES = 16_384
MAX_EXISTING_BYTES = 262_144
MAX_CHECK_BYTES = 262_144
EDITABLE_SUFFIXES = frozenset({
    '.py', '.md', '.txt', '.json', '.toml', '.ini', '.yml', '.yaml',
    '.rb', '.erb', '.js', '.ts', '.css', '.html', '.sql',
})
CHECK_SUFFIXES = frozenset({'.py', '.json', '.toml'})
_HASH = re.compile(r'\A[0-9a-f]{64}\Z')


class WorkspaceEditError(Exception):
    """Expected, user-safe refusal for scoped workspace operations."""


class WorkspaceEditor:
    def __init__(self, root: Path, validate_path: Callable[[str], Path]):
        self.root = root
        self.validate_path = validate_path

    def _validated(self, path: str, suffixes: frozenset[str]) -> tuple[str, ...]:
        if not isinstance(path, str) or not path or len(path) > 400:
            raise WorkspaceEditError('Invalid relative file path')
        if path == '.' or path.endswith('/') or any(ord(c) < 32 or ord(c) == 127 for c in path):
            raise WorkspaceEditError('Invalid file path')
        try:
            target = self.validate_path(path)
        except Exception as exc:
            raise WorkspaceEditError('Path restricted') from exc
        if target.suffix.lower() not in suffixes:
            raise WorkspaceEditError('File extension not allowed')
        parts = target.relative_to(self.root).parts
        if not parts or parts[0] == '..':
            raise WorkspaceEditError('Path restricted')
        return parts

    def _parent_fd(self, parts: tuple[str, ...]) -> int:
        if (os.name != 'posix' or not hasattr(os, 'O_NOFOLLOW')
                or not hasattr(os, 'O_DIRECTORY') or os.open not in os.supports_dir_fd):
            raise WorkspaceEditError('Secure directory access unavailable')
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        try:
            fd = os.open(self.root, flags)
        except OSError as exc:
            raise WorkspaceEditError('Workspace unavailable') from exc
        try:
            for piece in parts[:-1]:
                next_fd = os.open(piece, flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            return fd
        except OSError as exc:
            os.close(fd)
            raise WorkspaceEditError('Parent directory restricted or missing') from exc

    @staticmethod
    def _open_existing(parent: int, name: str) -> int | None:
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_NONBLOCK', 0),
                         dir_fd=parent)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise WorkspaceEditError('Target is restricted or unavailable') from exc
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise WorkspaceEditError('Target must be a regular file')
        return fd

    def file_sha256(self, path: str) -> dict:
        """Read-only SHA-256 of one existing allowed text source (max 256 KiB)."""
        parts = self._validated(path, EDITABLE_SUFFIXES)
        parent = self._parent_fd(parts)
        try:
            fd = self._open_existing(parent, parts[-1])
            if fd is None:
                raise WorkspaceEditError('File missing')
            try:
                if os.fstat(fd).st_size > MAX_EXISTING_BYTES:
                    raise WorkspaceEditError('File too large to hash')
                data = os.read(fd, MAX_EXISTING_BYTES + 1)
                if len(data) > MAX_EXISTING_BYTES:
                    raise WorkspaceEditError('File too large to hash')
            finally:
                os.close(fd)
        finally:
            os.close(parent)
        return {'path': path, 'sha256': hashlib.sha256(data).hexdigest(),
                'bytes_read': len(data)}

    def write_file(self, path: str, content: str, expected_sha256: str | None = None) -> dict:
        parts = self._validated(path, EDITABLE_SUFFIXES)
        if not isinstance(content, str) or '\x00' in content:
            raise WorkspaceEditError('Content must be UTF-8 text without NUL')
        try:
            payload = content.encode('utf-8')
        except UnicodeEncodeError as exc:
            raise WorkspaceEditError('Invalid UTF-8 content') from exc
        if len(payload) > MAX_WRITE_BYTES:
            raise WorkspaceEditError('Content exceeds 16 KiB limit')
        if expected_sha256 is not None and (not isinstance(expected_sha256, str)
                                            or not _HASH.fullmatch(expected_sha256)):
            raise WorkspaceEditError('Invalid expected SHA-256')
        parent = self._parent_fd(parts)
        filename = parts[-1]
        temp_name: str | None = None
        try:
            existing = self._open_existing(parent, filename)
            current = None
            existing_stat = None
            if existing is not None:
                try:
                    existing_stat = os.fstat(existing)
                    if existing_stat.st_size > MAX_EXISTING_BYTES:
                        raise WorkspaceEditError('Existing file too large to update')
                    data = os.read(existing, MAX_EXISTING_BYTES + 1)
                    if len(data) > MAX_EXISTING_BYTES:
                        raise WorkspaceEditError('Existing file too large to update')
                    current = hashlib.sha256(data).hexdigest()
                finally:
                    os.close(existing)
                if expected_sha256 is None:
                    raise WorkspaceEditError('File exists: expected_sha256 required for update')
                if current != expected_sha256:
                    raise WorkspaceEditError('File changed: SHA-256 mismatch')
                if not (existing_stat.st_mode & stat.S_IWUSR):
                    raise WorkspaceEditError('Target file is read-only')
                if existing_stat.st_nlink != 1:
                    raise WorkspaceEditError('Hard-linked file update refused')
            elif expected_sha256 is not None:
                raise WorkspaceEditError('File missing: cannot update')
            # Create a private temporary inode inside verified parent directory.
            temp_name = '.krw-tmp-' + secrets.token_hex(16)
            tmp_fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=parent)
            try:
                if existing_stat is not None:
                    os.fchmod(tmp_fd, stat.S_IMODE(existing_stat.st_mode) & 0o666)
                with os.fdopen(tmp_fd, 'wb', closefd=False) as stream:
                    stream.write(payload)
                    stream.flush()
                os.fsync(tmp_fd)
            finally:
                os.close(tmp_fd)
            if existing_stat is None:
                try:
                    # Atomic create-only: never silently clobber a newly created path.
                    os.link(temp_name, filename, src_dir_fd=parent, dst_dir_fd=parent,
                            follow_symlinks=False)
                except FileExistsError as exc:
                    raise WorkspaceEditError('File appeared during create') from exc
                action = 'created'
            else:
                try:
                    now = os.stat(filename, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError as exc:
                    raise WorkspaceEditError('File removed during update') from exc
                if (now.st_ino != existing_stat.st_ino or now.st_dev != existing_stat.st_dev
                        or now.st_mtime_ns != existing_stat.st_mtime_ns
                        or now.st_size != existing_stat.st_size or not stat.S_ISREG(now.st_mode)):
                    raise WorkspaceEditError('File changed during update')
                os.replace(temp_name, filename, src_dir_fd=parent, dst_dir_fd=parent)
                temp_name = None
                action = 'updated'
            os.fsync(parent)
            return {'path': path, 'action': action,
                    'sha256': hashlib.sha256(payload).hexdigest(), 'bytes_written': len(payload)}
        except OSError as exc:
            raise WorkspaceEditError('Secure file operation failed') from exc
        finally:
            if temp_name is not None:
                try:
                    os.unlink(temp_name, dir_fd=parent)
                except FileNotFoundError:
                    pass
            os.close(parent)

    def check_syntax(self, path: str) -> dict:
        parts = self._validated(path, CHECK_SUFFIXES)
        parent = self._parent_fd(parts)
        try:
            fd = self._open_existing(parent, parts[-1])
            if fd is None:
                raise WorkspaceEditError('File missing')
            try:
                if os.fstat(fd).st_size > MAX_CHECK_BYTES:
                    raise WorkspaceEditError('File too large to check')
                raw = os.read(fd, MAX_CHECK_BYTES + 1)
                if len(raw) > MAX_CHECK_BYTES:
                    raise WorkspaceEditError('File too large to check')
            finally:
                os.close(fd)
        finally:
            os.close(parent)
        try:
            decoded = raw.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise WorkspaceEditError('File is not valid UTF-8') from exc
        suffix = Path(parts[-1]).suffix.lower()
        try:
            if suffix == '.py':
                ast.parse(decoded, filename='<workspace file>')
            elif suffix == '.json':
                json.loads(decoded)
            elif suffix == '.toml':
                tomllib.loads(decoded)
        except (SyntaxError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
            return {'path': path, 'language': suffix.lstrip('.'), 'valid': False,
                    'executed': False, 'line': getattr(exc, 'lineno', None), 'error': type(exc).__name__}
        return {'path': path, 'language': suffix.lstrip('.'), 'valid': True, 'executed': False}

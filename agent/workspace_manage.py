"""Opt-in workspace file management, without arbitrary shell execution.

All paths stay within the configured workspace. Directory traversal and
file operations use descriptor-relative, no-follow access on POSIX.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any

from agent.workspace_edit import (
    WorkspaceEditor, WorkspaceEditError, EDITABLE_SUFFIXES,
    MAX_WRITE_BYTES, _HASH,
)

DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class WorkspaceManager(WorkspaceEditor):
    def _directory_parts(self, path: str) -> tuple[str, ...]:
        if not isinstance(path, str) or path in ("", ".") or path.endswith("/"):
            raise WorkspaceEditError("Invalid directory path")
        try:
            target = self.validate_path(path)
            parts = target.relative_to(self.root).parts
        except Exception as exc:
            raise WorkspaceEditError("Path restricted") from exc
        if not parts:
            raise WorkspaceEditError("Cannot modify workspace root")
        return parts

    def _load_text(self, path: str) -> tuple[str, str]:
        parts = self._validated(path, EDITABLE_SUFFIXES)
        parent = self._parent_fd(parts)
        try:
            fd = self._open_existing(parent, parts[-1])
            if fd is None:
                raise WorkspaceEditError("File missing")
            try:
                if os.fstat(fd).st_size > MAX_WRITE_BYTES:
                    raise WorkspaceEditError("File too large to edit")
                raw = os.read(fd, MAX_WRITE_BYTES + 1)
                if len(raw) > MAX_WRITE_BYTES:
                    raise WorkspaceEditError("File too large to edit")
            finally:
                os.close(fd)
        finally:
            os.close(parent)
        try:
            return raw.decode("utf-8"), hashlib.sha256(raw).hexdigest()
        except UnicodeDecodeError as exc:
            raise WorkspaceEditError("File is not valid UTF-8") from exc

    def edit_file(self, path: str, old_string: str, new_string: str,
                  expected_replacements: int = 1,
                  expected_sha256: str | None = None) -> dict[str, Any]:
        if (not isinstance(old_string, str) or not old_string or
                not isinstance(new_string, str) or "\x00" in new_string or
                type(expected_replacements) is not int or
                not 1 <= expected_replacements <= 1000):
            raise WorkspaceEditError("Invalid edit arguments")
        current_text, current_hash = self._load_text(path)
        if expected_sha256 is not None and current_hash != expected_sha256:
            raise WorkspaceEditError("File changed: SHA-256 mismatch")
        count = current_text.count(old_string)
        if count != expected_replacements:
            raise WorkspaceEditError(
                f"Expected {expected_replacements} matches, found {count}")
        updated = current_text.replace(old_string, new_string, expected_replacements)
        result = self.write_file(path, updated, expected_sha256=current_hash)
        result["replacements"] = count
        return result

    def create_directory(self, path: str, parents: bool = True) -> dict[str, Any]:
        parts = self._directory_parts(path)
        if type(parents) is not bool:
            raise WorkspaceEditError("parents must be boolean")
        try:
            fd = os.open(self.root, DIR_FLAGS)
        except OSError as exc:
            raise WorkspaceEditError("Workspace unavailable") from exc
        created = []
        try:
            for i, piece in enumerate(parts):
                try:
                    next_fd = os.open(piece, DIR_FLAGS, dir_fd=fd)
                except FileNotFoundError:
                    if not parents and i != len(parts) - 1:
                        raise WorkspaceEditError("Parent directory missing")
                    try:
                        os.mkdir(piece, mode=0o755, dir_fd=fd)
                        created.append(str(Path(*parts[:i + 1])))
                        os.fsync(fd)
                        next_fd = os.open(piece, DIR_FLAGS, dir_fd=fd)
                    except FileExistsError:
                        next_fd = os.open(piece, DIR_FLAGS, dir_fd=fd)
                os.close(fd)
                fd = next_fd
        except OSError as exc:
            raise WorkspaceEditError("Directory restricted or unavailable") from exc
        finally:
            os.close(fd)
        return {"path": path, "created": created, "already_exists": not created}

    def delete_file(self, path: str, expected_sha256: str | None = None) -> dict[str, Any]:
        parts = self._validated(path, EDITABLE_SUFFIXES)
        if expected_sha256 is not None and (
                not isinstance(expected_sha256, str) or not _HASH.fullmatch(expected_sha256)):
            raise WorkspaceEditError("Invalid expected SHA-256")
        parent = self._parent_fd(parts)
        try:
            fd = self._open_existing(parent, parts[-1])
            if fd is None:
                raise WorkspaceEditError("File missing")
            try:
                meta = os.fstat(fd)
                if meta.st_nlink != 1:
                    raise WorkspaceEditError("Hard-linked file deletion refused")
                if expected_sha256 is not None:
                    if meta.st_size > MAX_WRITE_BYTES:
                        raise WorkspaceEditError("File too large to verify")
                    raw = os.read(fd, MAX_WRITE_BYTES + 1)
                    if hashlib.sha256(raw).hexdigest() != expected_sha256:
                        raise WorkspaceEditError("File changed: SHA-256 mismatch")
                latest = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                if (latest.st_ino != meta.st_ino or latest.st_dev != meta.st_dev
                        or not stat.S_ISREG(latest.st_mode)):
                    raise WorkspaceEditError("File changed during delete")
                os.unlink(parts[-1], dir_fd=parent)
                os.fsync(parent)
            finally:
                os.close(fd)
        except OSError as exc:
            raise WorkspaceEditError("Secure delete failed") from exc
        finally:
            os.close(parent)
        return {"path": path, "deleted": True}

    def move_file(self, source: str, destination: str,
                  expected_sha256: str | None = None) -> dict[str, Any]:
        if source == destination:
            raise WorkspaceEditError("Source and destination must differ")
        self._validated(destination, EDITABLE_SUFFIXES)
        text, sha = self._load_text(source)
        if expected_sha256 is not None and sha != expected_sha256:
            raise WorkspaceEditError("File changed: SHA-256 mismatch")
        created = self.write_file(destination, text)
        try:
            self.delete_file(source, expected_sha256=sha)
        except WorkspaceEditError:
            # Best-effort rollback: preserve source if it changed while moving.
            try:
                self.delete_file(destination, expected_sha256=created["sha256"])
            except WorkspaceEditError:
                pass
            raise
        return {"source": source, "destination": destination, "moved": True,
                "sha256": sha}

    def search_files(self, query: str, path: str = ".", mode: str = "both",
                     max_results: int = 50, case_sensitive: bool = False) -> dict[str, Any]:
        if not isinstance(query, str) or not query or len(query) > 128 or "\x00" in query:
            raise WorkspaceEditError("Invalid search query")
        if mode not in ("name", "content", "both"):
            raise WorkspaceEditError("Invalid search mode")
        if type(max_results) is not int or not 1 <= max_results <= 100:
            raise WorkspaceEditError("max_results outside range")
        if type(case_sensitive) is not bool:
            raise WorkspaceEditError("case_sensitive must be boolean")
        if path == ".":
            parts = ()
        else:
            parts = self._directory_parts(path)
        if parts:
            fd = self._parent_fd(parts + ("_unused_",))
        else:
            fd = os.open(self.root, DIR_FLAGS)
        needle = query if case_sensitive else query.casefold()
        results: list[dict[str, Any]] = []
        scanned = 0
        truncated = False

        def matches(text: str) -> bool:
            return needle in (text if case_sensitive else text.casefold())

        def walk(directory_fd: int, prefix: tuple[str, ...], depth: int) -> None:
            nonlocal scanned, truncated
            try:
                entries = sorted(os.scandir(directory_fd), key=lambda e: e.name.casefold())
            except OSError:
                return
            for entry in entries:
                if scanned >= 2000 or len(results) >= max_results:
                    truncated = True
                    break
                rel_parts = prefix + (entry.name,)
                rel = str(Path(*rel_parts))
                try:
                    self.validate_path(rel)
                except Exception:
                    continue
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if depth < 8:
                        try:
                            child = os.open(entry.name, DIR_FLAGS, dir_fd=directory_fd)
                        except OSError:
                            continue
                        try:
                            walk(child, rel_parts, depth + 1)
                        finally:
                            os.close(child)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                scanned += 1
                if mode in ("name", "both") and matches(entry.name):
                    results.append({"path": rel, "match": "name"})
                    if len(results) >= max_results:
                        truncated = True
                        break
                if mode not in ("content", "both") or Path(entry.name).suffix.lower() not in EDITABLE_SUFFIXES:
                    continue
                try:
                    f = os.open(entry.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
                    try:
                        if not stat.S_ISREG(os.fstat(f).st_mode):
                            continue
                        raw = os.read(f, 262_145)
                    finally:
                        os.close(f)
                    if len(raw) > 262_144:
                        continue
                    text = raw.decode("utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                for number, line in enumerate(text.splitlines(), 1):
                    if matches(line):
                        results.append({"path": rel, "match": "content", "line": number,
                                        "snippet": line[:240]})
                        if len(results) >= max_results:
                            truncated = True
                            break
        try:
            walk(fd, parts, 0)
        finally:
            os.close(fd)
        return {"query": query, "path": path, "mode": mode, "matches": results,
                "files_scanned": scanned, "truncated": truncated}

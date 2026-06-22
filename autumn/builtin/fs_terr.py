"""Sandboxed filesystem capability domain.

All paths are resolved relative to the ``root`` directory passed at construction
time. Any attempt to traverse outside the root (via ``..`` or symlinks) is
rejected with :class:`ValueError`. The ``root`` must exist on disk; the tool
will not create it for you — that's a one-line :func:`pathlib.Path.mkdir` call
in your setup code.

Primitive tools (standalone-callable):
    read_file, write_file, list_dir, file_info, delete_file,
    search_files, copy_file, move_file

Compound skills (orchestrate multiple primitives):
    grep_files, file_tree, read_multiple
"""
from __future__ import annotations

import datetime
import fnmatch
import os
import re
import shutil
from pathlib import Path
from typing import Any

from ..core.components.skill import Skill
from ..core.components.terr import Terr
from ..core.components.tool import Tool, ToolParameter
from ..core.security import is_within_root as _within_root

_MAX_READ_BYTES = 2_000_000  # 2MB per read
_MAX_WRITE_BYTES = 2_000_000  # 2MB per write
_MAX_GREP_RESULTS = 100


def _resolve_sandboxed(root: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``root``, rejecting traversal outside root."""
    if os.path.isabs(relative):
        raise ValueError(f"absolute paths are not allowed inside the sandbox: {relative!r}")
    target = (root / relative).resolve()
    root_resolved = root.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"path escapes sandbox root: {relative!r}") from exc
    return target


def _stat_summary(p: Path) -> dict[str, Any]:
    st = p.stat()
    return {
        "name": p.name,
        "path": str(p),
        "is_dir": p.is_dir(),
        "is_file": p.is_file(),
        "size": st.st_size,
        "modified": datetime.datetime.fromtimestamp(st.st_mtime, tz=datetime.UTC).isoformat(),
    }


def fs_terr(root: str | Path) -> Terr:
    """Build the ``fs`` Terr sandboxed at ``root``.

    Primitive tools (standalone-callable):
        read_file(path)                → utf-8 text contents
        write_file(path, content)      → writes utf-8 (creates parent dirs)
        list_dir(path=".", recursive)  → ordered list of entries
        file_info(path)                → metadata dict
        delete_file(path)              → unlink one file (not directories)
        search_files(pattern, path, recursive) → glob-match file names
        copy_file(src, dst)            → copy a file within the sandbox
        move_file(src, dst)            → move/rename a file within the sandbox

    Compound skills (orchestrate primitives):
        grep_files(pattern, path, recursive, file_glob, max_results) → content search
        file_tree(path, max_depth)     → directory tree as formatted string
        read_multiple(paths)           → batch read → {path: content} dict
    """
    root = Path(root)
    if not root.exists():
        raise ValueError(f"root does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"root is not a directory: {root}")
    root_resolved = root.resolve()

    # ── Primitive tool closures ───────────────────────────────────────────────

    async def read_file(path: str) -> str:
        target = _resolve_sandboxed(root_resolved, path)
        if not target.is_file():
            raise FileNotFoundError(f"not a file: {path}")
        size = target.stat().st_size
        if size > _MAX_READ_BYTES:
            raise ValueError(f"file exceeds {_MAX_READ_BYTES} bytes: {size}")
        return target.read_text(encoding="utf-8")

    async def write_file(path: str, content: str) -> str:
        if len(content.encode("utf-8")) > _MAX_WRITE_BYTES:
            raise ValueError(f"content exceeds {_MAX_WRITE_BYTES} bytes")
        target = _resolve_sandboxed(root_resolved, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"[wrote {len(content)} chars to {path}]"

    async def list_dir(path: str = ".", recursive: bool = False) -> list[dict[str, Any]]:
        target = _resolve_sandboxed(root_resolved, path)
        if not target.is_dir():
            raise NotADirectoryError(f"not a directory: {path}")
        if recursive:
            # rglob can descend through a symlinked subdirectory and surface
            # paths outside the sandbox — drop any entry whose real path escapes
            # root so a recursive listing can't disclose external files.
            entries = [
                p for p in sorted(target.rglob("*"))
                if _within_root(p, root_resolved)
            ]
        else:
            entries = sorted(target.iterdir())
        return [_stat_summary(p) for p in entries]

    async def file_info(path: str) -> dict[str, Any]:
        target = _resolve_sandboxed(root_resolved, path)
        if not target.exists():
            raise FileNotFoundError(f"not found: {path}")
        return _stat_summary(target)

    async def delete_file(path: str) -> str:
        target = _resolve_sandboxed(root_resolved, path)
        if target.is_dir():
            raise IsADirectoryError(f"refusing to delete directory: {path}")
        if not target.exists():
            raise FileNotFoundError(f"not found: {path}")
        target.unlink()
        return f"[deleted {path}]"

    async def search_files(
        pattern: str,
        path: str = ".",
        recursive: bool = True,
    ) -> list[dict[str, Any]]:
        """Find files whose names match a glob pattern under ``path``."""
        target = _resolve_sandboxed(root_resolved, path)
        if not target.is_dir():
            raise NotADirectoryError(f"not a directory: {path}")
        if recursive:
            candidates = [
                p for p in sorted(target.rglob("*"))
                if _within_root(p, root_resolved) and p.is_file()
            ]
        else:
            candidates = [p for p in sorted(target.iterdir()) if p.is_file()]
        matched = [p for p in candidates if fnmatch.fnmatch(p.name, pattern)]
        return [_stat_summary(p) for p in matched]

    async def copy_file(src: str, dst: str) -> str:
        """Copy a file within the sandbox. Creates destination parent dirs."""
        src_path = _resolve_sandboxed(root_resolved, src)
        dst_path = _resolve_sandboxed(root_resolved, dst)
        if not src_path.is_file():
            raise FileNotFoundError(f"not a file: {src}")
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, dst_path)
        return f"[copied {src} → {dst}]"

    async def move_file(src: str, dst: str) -> str:
        """Move or rename a file within the sandbox. Creates destination parent dirs."""
        src_path = _resolve_sandboxed(root_resolved, src)
        dst_path = _resolve_sandboxed(root_resolved, dst)
        if not src_path.exists():
            raise FileNotFoundError(f"not found: {src}")
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))
        return f"[moved {src} → {dst}]"

    # ── Compound skill closures ───────────────────────────────────────────────

    async def grep_files(
        pattern: str,
        path: str = ".",
        recursive: bool = True,
        file_glob: str = "*",
        max_results: int = 50,
    ) -> str:
        """Search file contents for a regex pattern, returning matching lines.

        Returns ``file:line: content`` lines, capped at ``max_results``.
        Binary files and files exceeding 2MB are skipped silently.
        """
        target = _resolve_sandboxed(root_resolved, path)
        if not target.is_dir():
            raise NotADirectoryError(f"not a directory: {path}")
        if recursive:
            files = [
                p for p in sorted(target.rglob(file_glob))
                if _within_root(p, root_resolved) and p.is_file()
            ]
        else:
            files = [p for p in sorted(target.glob(file_glob)) if p.is_file()]

        try:
            compiled = re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid regex pattern: {exc}") from exc

        n = max(1, min(int(max_results), _MAX_GREP_RESULTS))
        results: list[str] = []
        for file_path in files:
            try:
                if file_path.stat().st_size > _MAX_READ_BYTES:
                    continue
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except (PermissionError, OSError):
                continue
            rel = str(file_path.relative_to(root_resolved))
            for i, line in enumerate(content.splitlines(), 1):
                if compiled.search(line):
                    results.append(f"{rel}:{i}: {line.rstrip()}")
                    if len(results) >= n:
                        return "\n".join(results) + f"\n[... capped at {n} results]"
        return "\n".join(results) if results else f"[grep_files: no matches for {pattern!r}]"

    async def file_tree(path: str = ".", max_depth: int = 3) -> str:
        """Render a directory as an ASCII tree (similar to the ``tree`` command).

        Entries are sorted: directories first, then files, all alphabetically.
        Traversal is bounded to ``max_depth`` levels and to paths that stay
        inside the sandbox root.
        """
        target = _resolve_sandboxed(root_resolved, path)
        if not target.is_dir():
            raise NotADirectoryError(f"not a directory: {path}")
        depth = max(0, int(max_depth))

        lines = [target.name + "/"]

        def _build(dir_path: Path, prefix: str, current_depth: int) -> None:
            if current_depth > depth:
                return
            try:
                entries = sorted(
                    dir_path.iterdir(),
                    key=lambda p: (not p.is_dir(), p.name.lower()),
                )
            except PermissionError:
                return
            valid = [e for e in entries if _within_root(e, root_resolved)]
            for i, entry in enumerate(valid):
                is_last = i == len(valid) - 1
                connector = "└── " if is_last else "├── "
                suffix = "/" if entry.is_dir() else ""
                lines.append(f"{prefix}{connector}{entry.name}{suffix}")
                if entry.is_dir() and current_depth < depth:
                    extension = "    " if is_last else "│   "
                    _build(entry, prefix + extension, current_depth + 1)

        _build(target, "", 0)
        return "\n".join(lines)

    async def read_multiple(paths: list[str]) -> dict[str, str]:
        """Batch-read up to 50 files, returning a {path: content} dict.

        Errors (file not found, too large, non-UTF-8) are returned as
        ``"[error: ...]"`` strings for the affected path — they never
        raise so partial success is still useful.
        """
        if len(paths) > 50:
            raise ValueError("read_multiple supports at most 50 paths at once")
        result: dict[str, str] = {}
        for p in paths:
            try:
                target = _resolve_sandboxed(root_resolved, p)
                if not target.is_file():
                    result[p] = "[error: not a file]"
                elif target.stat().st_size > _MAX_READ_BYTES:
                    result[p] = "[error: file too large (>2MB)]"
                else:
                    result[p] = target.read_text(encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                result[p] = f"[error: {e}]"
        return result

    return Terr(
        name="fs",
        description=f"Sandboxed filesystem rooted at {root_resolved}.",
        tools=[
            Tool(
                name="read_file",
                description="Read a UTF-8 text file relative to the sandbox root.",
                fn=read_file,
                parameters=[
                    ToolParameter("path", "string", "Path relative to the sandbox root."),
                ],
            ),
            Tool(
                name="write_file",
                description=(
                    "Write UTF-8 text to a file inside the sandbox, creating parent "
                    "directories as needed. Overwrites existing content."
                ),
                fn=write_file,
                parameters=[
                    ToolParameter("path", "string", "Path relative to the sandbox root."),
                    ToolParameter("content", "string", "UTF-8 text to write."),
                ],
            ),
            Tool(
                name="list_dir",
                description="List entries in a sandbox directory.",
                fn=list_dir,
                parameters=[
                    ToolParameter("path", "string",
                                  "Directory relative to the sandbox root. Default '.'.",
                                  required=False),
                    ToolParameter("recursive", "boolean",
                                  "Recurse into subdirectories. Default false.",
                                  required=False),
                ],
            ),
            Tool(
                name="file_info",
                description="Return metadata for a file or directory.",
                fn=file_info,
                parameters=[
                    ToolParameter("path", "string", "Path relative to the sandbox root."),
                ],
            ),
            Tool(
                name="delete_file",
                description="Remove a single file (will NOT delete directories).",
                fn=delete_file,
                parameters=[
                    ToolParameter("path", "string", "File path relative to the sandbox root."),
                ],
            ),
            Tool(
                name="search_files",
                description=(
                    "Find files by name glob pattern (e.g. '*.py', 'report_*.csv'). "
                    "Searches recursively by default."
                ),
                fn=search_files,
                parameters=[
                    ToolParameter("pattern", "string",
                                  "Glob pattern to match file names (e.g. '*.txt')."),
                    ToolParameter("path", "string",
                                  "Directory to search under. Default '.'.",
                                  required=False),
                    ToolParameter("recursive", "boolean",
                                  "Search recursively. Default true.",
                                  required=False),
                ],
            ),
            Tool(
                name="copy_file",
                description="Copy a file within the sandbox. Creates destination parent directories.",
                fn=copy_file,
                parameters=[
                    ToolParameter("src", "string", "Source path relative to sandbox root."),
                    ToolParameter("dst", "string", "Destination path relative to sandbox root."),
                ],
            ),
            Tool(
                name="move_file",
                description="Move or rename a file within the sandbox.",
                fn=move_file,
                parameters=[
                    ToolParameter("src", "string", "Source path relative to sandbox root."),
                    ToolParameter("dst", "string", "Destination path relative to sandbox root."),
                ],
            ),
        ],
        skills=[
            Skill(
                name="grep_files",
                description=(
                    "Search file contents for a regex pattern and return matching lines "
                    "as 'file:line: content' strings. Searches recursively by default. "
                    "Skips files larger than 2MB and binary files."
                ),
                handler=grep_files,
                parameters=[
                    ToolParameter("pattern", "string", "Python regex pattern to search for."),
                    ToolParameter("path", "string",
                                  "Directory to search under. Default '.'.",
                                  required=False),
                    ToolParameter("recursive", "boolean",
                                  "Search recursively. Default true.",
                                  required=False),
                    ToolParameter("file_glob", "string",
                                  "Glob pattern to filter which files to search. Default '*'.",
                                  required=False),
                    ToolParameter("max_results", "integer",
                                  "Maximum matching lines to return (1–100). Default 50.",
                                  required=False),
                ],
            ),
            Skill(
                name="file_tree",
                description=(
                    "Render the directory structure as a formatted ASCII tree. "
                    "Directories are listed before files at each level. "
                    "Depth is bounded to max_depth (default 3)."
                ),
                handler=file_tree,
                parameters=[
                    ToolParameter("path", "string",
                                  "Root of the tree. Default '.'.",
                                  required=False),
                    ToolParameter("max_depth", "integer",
                                  "Maximum levels to descend. Default 3.",
                                  required=False),
                ],
            ),
            Skill(
                name="read_multiple",
                description=(
                    "Read up to 50 files in one call and return a dict of "
                    "{path: content}. Errors are returned as '[error: ...]' "
                    "strings for the affected paths."
                ),
                handler=read_multiple,
                parameters=[
                    ToolParameter("paths", "array",
                                  "List of file paths (max 50) relative to sandbox root.",
                                  extra={"items": {"type": "string"}}),
                ],
            ),
        ],
    )


__all__ = ["fs_terr"]

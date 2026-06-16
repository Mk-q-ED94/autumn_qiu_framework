"""Sandboxed filesystem capability domain.

All paths are resolved relative to the ``root`` directory passed at construction
time. Any attempt to traverse outside the root (via ``..`` or symlinks) is
rejected with :class:`ValueError`. The ``root`` must exist on disk; the tool
will not create it for you — that's a one-line :func:`pathlib.Path.mkdir` call
in your setup code.
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Any

from ..core.components.terr import Terr
from ..core.components.tool import Tool, ToolParameter
from ..core.security import is_within_root as _within_root

_MAX_READ_BYTES = 2_000_000  # 2MB per read
_MAX_WRITE_BYTES = 2_000_000  # 2MB per write


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

    Tools:
        read_file(path)                → utf-8 text contents
        write_file(path, content)      → writes utf-8 (creates parent dirs)
        list_dir(path=".", recursive)  → ordered list of entries
        file_info(path)                → metadata dict
        delete_file(path)              → unlink one file (not directories)
    """
    root = Path(root)
    if not root.exists():
        raise ValueError(f"root does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"root is not a directory: {root}")
    root_resolved = root.resolve()

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
        ],
    )


__all__ = ["fs_terr"]

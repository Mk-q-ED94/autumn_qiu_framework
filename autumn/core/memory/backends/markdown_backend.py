"""Markdown-as-source-of-truth memory backend (RFC 4D-memory P1-A).

Implements the generic :class:`MemoryBackend` KV contract on top of a directory
of plain ``.md`` files, so memory becomes readable, editable, grep-able and
Git-versionable (the EverOS "markdown as source of truth" idea, adapted to
Autumn's 4D model).

Layout under ``root``::

    <root>/
      <area>/                       # e.g. mom1, mom2, shared (the key prefix)
        <entry_id>.md               # one file per history entry (4D frontmatter)
        _kv/<hash>.md               # one file per plain key-value pair

The special ``<area>:history`` key (a list of :class:`MemoryEntry` dicts) is
exploded into one file per entry; every other key is a single ``_kv`` file. A
history entry file carries the four dimensions in its frontmatter and the
``content`` as the body — so a string memory is fully human-readable and
editable in place::

    ---
    id: "a1b2c3"
    timestamp: 1718412345.0
    importance: 1.0
    tags: ["deploy", "db"]
    meta: {}
    expires_at: null
    aim: {"intent": "deploy_guardrail", "goal_ref": "goal:ship-v2", "scope": ["deploy"]}
    use: {"mode": "constrain", "weight": 2.0, "template": null, "stats": {"count": 3, ...}}
    trigger: {"half_life": null, "cues": ["部署"], "base_weight": 1.0, ...}
    content_type: "text"
    ---
    生产库必须走只读副本，不得直连主库

Frontmatter values are JSON (one ``key: <json>`` line each) — no YAML dependency,
and a perfect round-trip back into the entry dict that
:meth:`MemoryEntry.from_dict` expects. The backend stays a pure KV store: it
knows nothing about scoring; it only special-cases the reserved ``history`` key
so the dimensions land in frontmatter rather than an opaque blob.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from ..base import MemoryBackend

_FENCE = "---"
_HISTORY_SUB = "history"
_KV_DIR = "_kv"
_ROOT_AREA = "_root"  # holds keys that arrived without an "<area>:" prefix


# ── frontmatter (de)serialisation — JSON values, no YAML dep ──────────────────

def _dump(fields: dict[str, Any], body: str) -> str:
    lines = [_FENCE]
    for key, value in fields.items():
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    lines.append(_FENCE)
    return "\n".join(lines) + "\n" + body


def _parse(text: str) -> tuple[dict[str, Any], str]:
    """Split a file into (frontmatter fields, body). Tolerant of no frontmatter."""
    if not text.startswith(_FENCE):
        return {}, text
    lines = text.split("\n")
    fields: dict[str, Any] = {}
    body_start = len(lines)
    for i in range(1, len(lines)):
        if lines[i] == _FENCE:
            body_start = i + 1
            break
        key, sep, raw = lines[i].partition(": ")
        if sep:
            try:
                fields[key] = json.loads(raw)
            except json.JSONDecodeError:
                fields[key] = raw
    body = "\n".join(lines[body_start:])
    if body.startswith("\n"):
        body = body[1:]
    return fields, body


# ── entry ⇄ markdown ──────────────────────────────────────────────────────────

_ENTRY_FIELDS = ("id", "timestamp", "importance", "tags", "meta", "expires_at",
                 "aim", "use", "trigger")


def _entry_to_md(entry: dict[str, Any]) -> str:
    content = entry.get("content")
    if isinstance(content, str):
        body, content_type = content, "text"
    else:
        body, content_type = json.dumps(content, ensure_ascii=False), "json"
    fields = {k: entry.get(k) for k in _ENTRY_FIELDS}
    fields["content_type"] = content_type
    return _dump(fields, body)


def _md_to_entry(text: str) -> dict[str, Any]:
    fields, body = _parse(text)
    content_type = fields.pop("content_type", "text")
    content = json.loads(body) if content_type == "json" else body
    entry: dict[str, Any] = {"_m": True, "_v": 2, "content": content}
    entry.update(fields)
    return entry


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)  # atomic on POSIX & Windows


class MarkdownBackend(MemoryBackend):
    """A :class:`MemoryBackend` backed by a tree of markdown files.

    Pluggable wherever ``SQLiteBackend`` / ``DictBackend`` is used (typically
    wrapped in ``HybridBackend`` for a short-term cache). File I/O runs in the
    default executor so it never blocks the event loop.
    """

    def __init__(self, root: str | Path):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    # ── key routing ───────────────────────────────────────────────────────────

    def _split(self, key: str) -> tuple[str, str]:
        area, sep, sub = key.partition(":")
        return (area, sub) if sep else (_ROOT_AREA, key)

    def _area_dir(self, area: str) -> Path:
        return self._root / area

    def _kv_path(self, key: str) -> Path:
        area, _ = self._split(key)
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        return self._area_dir(area) / _KV_DIR / f"{digest}.md"

    # ── sync internals ────────────────────────────────────────────────────────

    def _get_sync(self, key: str) -> Any:
        area, sub = self._split(key)
        if sub == _HISTORY_SUB:
            area_dir = self._area_dir(area)
            if not area_dir.is_dir():
                return None
            entries = [
                _md_to_entry(p.read_text(encoding="utf-8"))
                for p in area_dir.glob("*.md")
                if p.is_file()
            ]
            if not entries:
                return None
            entries.sort(key=lambda e: e.get("timestamp", 0.0))
            return entries
        path = self._kv_path(key)
        if not path.is_file():
            return None
        fields, body = _parse(path.read_text(encoding="utf-8"))
        return json.loads(body) if fields.get("value_type") == "json" else body

    def _set_sync(self, key: str, value: Any) -> None:
        area, sub = self._split(key)
        if sub == _HISTORY_SUB:
            area_dir = self._area_dir(area)
            area_dir.mkdir(parents=True, exist_ok=True)
            entries = value or []
            keep_ids = set()
            for entry in entries:
                eid = str(entry.get("id") or hashlib.sha1(
                    json.dumps(entry, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest()[:16])
                keep_ids.add(eid)
                md = _entry_to_md(entry)
                target = area_dir / f"{eid}.md"
                # Skip the atomic-write (temp file + rename + fsync) when the
                # on-disk content is already identical — a single-entry change
                # (reinforce / annotate / pin) then rewrites one file, not all N.
                if target.is_file() and target.read_text(encoding="utf-8") == md:
                    continue
                _atomic_write(target, md)
            # Drop entry files that are no longer present (eviction / forget).
            for p in area_dir.glob("*.md"):
                if p.is_file() and p.stem not in keep_ids:
                    p.unlink()
            return
        path = self._kv_path(key)
        if isinstance(value, str):
            body, value_type = value, "text"
        else:
            body, value_type = json.dumps(value, ensure_ascii=False), "json"
        _atomic_write(path, _dump({"key": key, "value_type": value_type}, body))

    def _delete_sync(self, key: str) -> None:
        area, sub = self._split(key)
        if sub == _HISTORY_SUB:
            area_dir = self._area_dir(area)
            if area_dir.is_dir():
                for p in area_dir.glob("*.md"):
                    if p.is_file():
                        p.unlink()
            return
        path = self._kv_path(key)
        if path.is_file():
            path.unlink()

    def _keys_sync(self) -> list[str]:
        if not self._root.is_dir():
            return []
        result: list[str] = []
        for area_dir in self._root.iterdir():
            if not area_dir.is_dir():
                continue
            area = area_dir.name
            if any(p.is_file() and p.suffix == ".md" for p in area_dir.iterdir()):
                result.append(_HISTORY_SUB if area == _ROOT_AREA else f"{area}:{_HISTORY_SUB}")
            kv_dir = area_dir / _KV_DIR
            if kv_dir.is_dir():
                for p in kv_dir.glob("*.md"):
                    fields, _ = _parse(p.read_text(encoding="utf-8"))
                    if (k := fields.get("key")) is not None:
                        result.append(k)
        return result

    def _clear_sync(self) -> None:
        if self._root.exists():
            shutil.rmtree(self._root)
        self._root.mkdir(parents=True, exist_ok=True)

    # ── async public API ──────────────────────────────────────────────────────

    def _run(self, fn, *args):
        return asyncio.get_running_loop().run_in_executor(None, fn, *args)

    async def get(self, key: str) -> Any:
        return await self._run(self._get_sync, key)

    async def set(self, key: str, value: Any) -> None:
        await self._run(self._set_sync, key, value)

    async def delete(self, key: str) -> None:
        await self._run(self._delete_sync, key)

    async def keys(self) -> list[str]:
        return await self._run(self._keys_sync)

    async def clear(self) -> None:
        await self._run(self._clear_sync)

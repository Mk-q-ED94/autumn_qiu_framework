"""Collection / data-wrangling capability domain.

List and dict reshaping primitives — dedup, flatten, chunk, count, group, sort —
that pair with ``data`` (JSON/CSV) so the model can massage structured payloads
without hand-writing a loop each time. All stdlib, no I/O. Collections are
size-bounded so a runaway input can't blow up memory.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from ..core.components.terr import Terr
from ..core.components.tool import Tool, ToolParameter

_MAX_ITEMS = 100_000  # cap element count; protects against OOM on pathological input.


def _check_size(items: list, label: str = "items") -> None:
    if len(items) > _MAX_ITEMS:
        raise ValueError(f"{label} exceeds {_MAX_ITEMS} elements")


def _hashable_key(value: Any) -> Any:
    """A stable, hashable key for arbitrary JSON values (dicts/lists included)."""
    if isinstance(value, (dict, list)):
        import json
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return value


async def _unique(items: list) -> list:
    """Remove duplicates, preserving first-seen order. Handles nested values."""
    _check_size(items)
    seen: set = set()
    out: list = []
    for item in items:
        key = _hashable_key(item)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


async def _flatten(items: list, depth: int = 1) -> list:
    """Flatten nested lists up to ``depth`` levels (depth<0 flattens fully)."""
    _check_size(items)
    out: list = []
    for item in items:
        if isinstance(item, list) and depth != 0:
            out.extend(await _flatten(item, depth - 1))
        else:
            out.append(item)
    return out


async def _chunk(items: list, size: int) -> list:
    """Split a list into consecutive chunks of at most ``size`` elements."""
    _check_size(items)
    if size < 1:
        raise ValueError("size must be >= 1")
    return [items[i:i + size] for i in range(0, len(items), size)]


async def _frequencies(items: list) -> dict:
    """Count occurrences of each distinct value. Returns value→count."""
    _check_size(items)
    counter: Counter = Counter(_hashable_key(item) for item in items)
    return dict(counter)


async def _group_by(rows: list, key: str) -> dict:
    """Group a list of dicts by the value at ``key``. Returns group→rows."""
    _check_size(rows, "rows")
    groups: dict[str, list] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("every row must be a dict")
        bucket = str(row.get(key))
        groups.setdefault(bucket, []).append(row)
    return groups


async def _sort_records(rows: list, by: str, reverse: bool = False) -> list:
    """Sort a list of dicts by the value at ``by``. Missing keys sort last."""
    _check_size(rows, "rows")
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("every row must be a dict")
    # (key_missing, value) keeps rows without the key at the end in either order.
    return sorted(
        rows,
        key=lambda r: (by not in r, r.get(by)),
        reverse=reverse,
    )


def collection_terr() -> Terr:
    """Build the ``collection`` Terr — list/dict reshaping utilities."""
    return Terr(
        name="collection",
        description="List and dict reshaping: dedup, flatten, chunk, count, group, sort.",
        tools=[
            Tool(
                name="unique",
                description="Remove duplicate elements, preserving first-seen order.",
                fn=_unique,
                parameters=[
                    ToolParameter("items", "array", "The list to deduplicate."),
                ],
            ),
            Tool(
                name="flatten",
                description="Flatten nested lists. depth=1 by default; -1 flattens fully.",
                fn=_flatten,
                parameters=[
                    ToolParameter("items", "array", "The nested list to flatten."),
                    ToolParameter("depth", "integer",
                                  "Levels to flatten; -1 for unlimited.",
                                  required=False),
                ],
            ),
            Tool(
                name="chunk",
                description="Split a list into consecutive chunks of a fixed size.",
                fn=_chunk,
                parameters=[
                    ToolParameter("items", "array", "The list to chunk."),
                    ToolParameter("size", "integer", "Maximum elements per chunk."),
                ],
            ),
            Tool(
                name="frequencies",
                description="Count how many times each distinct value appears.",
                fn=_frequencies,
                parameters=[
                    ToolParameter("items", "array", "The values to tally."),
                ],
            ),
            Tool(
                name="group_by",
                description="Group a list of dicts by the value at a given key.",
                fn=_group_by,
                parameters=[
                    ToolParameter("rows", "array", "The dict rows to group.",
                                  extra={"items": {"type": "object"}}),
                    ToolParameter("key", "string", "The field to group on."),
                ],
            ),
            Tool(
                name="sort_records",
                description="Sort a list of dicts by the value at a given field.",
                fn=_sort_records,
                parameters=[
                    ToolParameter("rows", "array", "The dict rows to sort.",
                                  extra={"items": {"type": "object"}}),
                    ToolParameter("by", "string", "The field to sort on."),
                    ToolParameter("reverse", "boolean",
                                  "Sort descending instead of ascending.",
                                  required=False),
                ],
            ),
        ],
    )


__all__ = ["collection_terr", "_MAX_ITEMS"]

"""Collection / data-wrangling capability domain.

List and dict reshaping primitives — dedup, flatten, chunk, count, group, sort,
filter, pluck, join — that pair with ``data`` (JSON/CSV) so the model can
massage structured payloads without hand-writing a loop each time.
All stdlib, no I/O. Collections are size-bounded so a runaway input can't
blow up memory.

Primitive tools (standalone-callable):
    unique, flatten, chunk, frequencies, group_by, sort_records,
    filter_records, pluck, zip_records

Compound skills (orchestrate multiple primitives):
    top_n, join_records
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from ..core.components.skill import Skill
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


# ── Primitive tool functions (exported for standalone use) ────────────────────


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


_FILTER_OPS: dict[str, Any] = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "lt": lambda a, b: a < b,
    "le": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "ge": lambda a, b: a >= b,
    "contains": lambda a, b: b in str(a) if a is not None else False,
    "startswith": lambda a, b: str(a).startswith(str(b)) if a is not None else False,
    "endswith": lambda a, b: str(a).endswith(str(b)) if a is not None else False,
}


async def _filter_records(rows: list, field: str, op: str, value: Any) -> list:
    """Filter a list of dicts where ``field`` satisfies ``op`` against ``value``.

    Operators: eq, ne, lt, le, gt, ge, contains, startswith, endswith.
    Rows missing the field or with incomparable types are excluded.
    """
    _check_size(rows, "rows")
    fn = _FILTER_OPS.get(op)
    if fn is None:
        raise ValueError(f"unknown op: {op!r}; use one of {sorted(_FILTER_OPS)}")
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("every row must be a dict")
        field_val = row.get(field)
        try:
            if fn(field_val, value):
                result.append(row)
        except TypeError:
            pass  # incompatible types → skip row
    return result


async def _pluck(rows: list, fields: list[str]) -> list:
    """Extract only the specified fields from each dict row.

    Fields missing from a row are omitted from its output dict.
    """
    _check_size(rows, "rows")
    return [
        {f: row[f] for f in fields if f in row}
        for row in rows
        if isinstance(row, dict)
    ]


async def _zip_records(keys: list[str], values: list) -> list[dict]:
    """Zip a list of keys and a list of values into a list of {key: value} dicts.

    Produces one dict per position: ``[{k1: v1}, {k2: v2}, ...]``.  Both lists
    must have the same length.
    """
    if len(keys) != len(values):
        raise ValueError(
            f"keys ({len(keys)}) and values ({len(values)}) must have the same length"
        )
    _check_size(keys)
    return [{k: v} for k, v in zip(keys, values)]


# ── Compound skill functions (exported for standalone use) ────────────────────


async def _top_n(rows: list, field: str, n: int = 5, reverse: bool = True) -> list:
    """Return the top n records sorted by ``field``.

    By default returns the highest values first (``reverse=True``). Pass
    ``reverse=False`` to get the lowest-valued records instead. Rows missing
    the field are excluded.
    """
    _check_size(rows, "rows")
    if n < 1:
        raise ValueError("n must be >= 1")
    valid = [r for r in rows if isinstance(r, dict) and field in r]
    try:
        return sorted(valid, key=lambda r: r[field], reverse=reverse)[:n]
    except TypeError as exc:
        raise ValueError(f"field {field!r} values are not comparable: {exc}") from exc


async def _join_records(
    left: list,
    right: list,
    on: str,
    how: str = "inner",
) -> list:
    """SQL-like join of two record lists on a key field.

    ``how`` selects the join type:
    - inner  (default) — only rows with matching keys in both
    - left             — all left rows; right fields null when no match
    - right            — all right rows; left fields null when no match
    - outer            — all rows from both sides
    """
    _check_size(left, "left")
    _check_size(right, "right")
    if how not in ("inner", "left", "right", "outer"):
        raise ValueError(f"unsupported how: {how!r}; use inner | left | right | outer")

    # Build index on the right side
    right_idx: dict[Any, list[dict]] = {}
    for r in right:
        if isinstance(r, dict):
            k = r.get(on)
            right_idx.setdefault(k, []).append(r)

    left_keys_seen: set[Any] = set()
    result: list[dict] = []

    for l_row in left:
        if not isinstance(l_row, dict):
            continue
        k = l_row.get(on)
        left_keys_seen.add(k)
        r_rows = right_idx.get(k, [])
        if r_rows:
            for r_row in r_rows:
                result.append({**l_row, **r_row})
        elif how in ("left", "outer"):
            result.append(dict(l_row))

    if how in ("right", "outer"):
        for r_row in right:
            if isinstance(r_row, dict):
                k = r_row.get(on)
                if k not in left_keys_seen:
                    result.append(dict(r_row))

    return result


# ── Terr factory ──────────────────────────────────────────────────────────────


def collection_terr() -> Terr:
    """Build the ``collection`` Terr — list/dict reshaping utilities.

    Primitive tools (standalone-callable):
        unique(items)                               → deduplicate, preserve order
        flatten(items, depth)                       → flatten nested lists
        chunk(items, size)                          → fixed-size consecutive chunks
        frequencies(items)                          → count occurrences
        group_by(rows, key)                         → group list of dicts by field
        sort_records(rows, by, reverse)             → sort list of dicts by field
        filter_records(rows, field, op, value)      → filter by field comparison
        pluck(rows, fields)                         → keep only specified fields
        zip_records(keys, values)                   → zip into list of single-key dicts

    Compound skills (orchestrate primitives):
        top_n(rows, field, n, reverse)             → top/bottom N records by field
        join_records(left, right, on, how)          → SQL-like inner/left/right/outer join
    """
    return Terr(
        name="collection",
        description=(
            "List and dict reshaping: dedup, flatten, chunk, count, group, sort, "
            "filter, pluck, join, and top-N selection."
        ),
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
            Tool(
                name="filter_records",
                description=(
                    "Filter a list of dicts by a field comparison. "
                    "Operators: eq, ne, lt, le, gt, ge, contains, startswith, endswith."
                ),
                fn=_filter_records,
                parameters=[
                    ToolParameter("rows", "array", "The dict rows to filter.",
                                  extra={"items": {"type": "object"}}),
                    ToolParameter("field", "string", "The field to compare."),
                    ToolParameter("op", "string",
                                  "eq | ne | lt | le | gt | ge | contains | startswith | endswith.",
                                  extra={"enum": sorted(_FILTER_OPS)}),
                    ToolParameter("value", "object",
                                  "The value to compare against.",
                                  extra={"description": "Any comparable value."}),
                ],
            ),
            Tool(
                name="pluck",
                description=(
                    "Extract only the specified fields from each dict row. "
                    "Fields missing from a row are omitted in its output dict."
                ),
                fn=_pluck,
                parameters=[
                    ToolParameter("rows", "array", "The dict rows to pluck from.",
                                  extra={"items": {"type": "object"}}),
                    ToolParameter("fields", "array", "Field names to keep.",
                                  extra={"items": {"type": "string"}}),
                ],
            ),
            Tool(
                name="zip_records",
                description=(
                    "Zip a list of keys and a list of values into a list of "
                    "single-key dicts: [{k1: v1}, {k2: v2}, ...]."
                ),
                fn=_zip_records,
                parameters=[
                    ToolParameter("keys", "array", "Field names.",
                                  extra={"items": {"type": "string"}}),
                    ToolParameter("values", "array", "Corresponding values."),
                ],
            ),
        ],
        skills=[
            Skill(
                name="top_n",
                description=(
                    "Return the top n records from a list of dicts sorted by a field. "
                    "reverse=true (default) returns the highest values; "
                    "reverse=false returns the lowest."
                ),
                handler=_top_n,
                parameters=[
                    ToolParameter("rows", "array", "The dict rows to rank.",
                                  extra={"items": {"type": "object"}}),
                    ToolParameter("field", "string", "The field to rank by."),
                    ToolParameter("n", "integer", "How many records to return. Default 5.",
                                  required=False),
                    ToolParameter("reverse", "boolean",
                                  "True (default) = highest first; False = lowest first.",
                                  required=False),
                ],
            ),
            Skill(
                name="join_records",
                description=(
                    "SQL-like join of two record lists on a shared key field. "
                    "how: inner (default), left, right, or outer."
                ),
                handler=_join_records,
                parameters=[
                    ToolParameter("left", "array", "Left record list.",
                                  extra={"items": {"type": "object"}}),
                    ToolParameter("right", "array", "Right record list.",
                                  extra={"items": {"type": "object"}}),
                    ToolParameter("on", "string", "The shared key field to join on."),
                    ToolParameter("how", "string",
                                  "inner | left | right | outer.",
                                  required=False,
                                  extra={"enum": ["inner", "left", "right", "outer"]}),
                ],
            ),
        ],
    )


__all__ = [
    "collection_terr",
    "_MAX_ITEMS",
    # primitive fns
    "_unique", "_flatten", "_chunk", "_frequencies", "_group_by", "_sort_records",
    "_filter_records", "_pluck", "_zip_records",
    # compound skill fns
    "_top_n", "_join_records",
]

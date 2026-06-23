"""Data serialization capability domain.

Parse/emit JSON and CSV via stdlib. The model needs these so often (ingesting
a tool's stringified response or massaging output into a clean shape) that
forcing every agent author to wire them up by hand is wasteful.

Primitive tools (standalone-callable):
    parse_json, to_json, parse_csv, to_csv, json_path,
    merge_json, flatten_json

Compound skills (orchestrate multiple primitives):
    json_transform, csv_filter
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from ..core.components.skill import Skill
from ..core.components.terr import Terr
from ..core.components.tool import Tool, ToolParameter

_MAX_INPUT = 1_000_000  # 1MB cap; protects the framework from OOM on bad input.


def _check_size(value: str, label: str) -> None:
    if len(value) > _MAX_INPUT:
        raise ValueError(f"{label} exceeds {_MAX_INPUT} chars")


# ── Primitive tool functions (exported for standalone use) ────────────────────


async def _parse_json(text: str) -> Any:
    _check_size(text, "text")
    return json.loads(text)


async def _to_json(value: Any, indent: int = 0) -> str:
    pretty = indent if indent > 0 else None
    result = json.dumps(value, ensure_ascii=False, indent=pretty)
    _check_size(result, "json output")  # cap emitted size, not just parsed input
    return result


async def _parse_csv(text: str, has_header: bool = True, delimiter: str = ",") -> list[dict | list]:
    _check_size(text, "text")
    if len(delimiter) != 1:
        raise ValueError("delimiter must be a single character")
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)
    if not rows:
        return []
    if has_header:
        header = rows[0]
        return [dict(zip(header, r)) for r in rows[1:]]
    return rows


async def _to_csv(rows: list[dict | list], delimiter: str = ",") -> str:
    if not rows:
        return ""
    if len(delimiter) != 1:
        raise ValueError("delimiter must be a single character")
    buf = io.StringIO()
    first = rows[0]
    if isinstance(first, dict):
        # Stable column order: keys from the first row, plus any extras seen later.
        fieldnames: list[str] = list(first.keys())
        seen = set(fieldnames)
        for row in rows[1:]:
            if not isinstance(row, dict):
                raise ValueError("rows must be uniformly dicts or lists")
            for k in row:
                if k not in seen:
                    fieldnames.append(k)
                    seen.add(k)
        writer = csv.DictWriter(buf, fieldnames=fieldnames, delimiter=delimiter)
        writer.writeheader()
        writer.writerows(rows)
    else:
        writer = csv.writer(buf, delimiter=delimiter)
        writer.writerows(rows)
    result = buf.getvalue()
    _check_size(result, "csv output")  # cap emitted size, not just parsed input
    return result


async def _json_path(data: Any, path: str) -> Any:
    """Dotted-path lookup. ``a.b.0.c`` reads dict keys and integer list indices."""
    cur: Any = data
    if not path:
        return cur
    for segment in path.split("."):
        if isinstance(cur, list):
            try:
                index = int(segment)
            except ValueError as exc:
                raise KeyError(f"expected integer index at {segment!r}") from exc
            cur = cur[index]
        elif isinstance(cur, dict):
            cur = cur[segment]
        else:
            raise KeyError(f"cannot descend into {type(cur).__name__} at {segment!r}")
    return cur


def _deep_merge(base: Any, patch: Any) -> Any:
    """Recursively merge ``patch`` into ``base``. Patch values win on conflict."""
    if isinstance(base, dict) and isinstance(patch, dict):
        result = dict(base)
        for k, v in patch.items():
            result[k] = _deep_merge(base.get(k), v) if k in base else v
        return result
    return patch


async def _merge_json(base: Any, patch: Any) -> Any:
    """Deep-merge ``patch`` into ``base``.

    For dict inputs, recursively merges nested dicts; patch keys win on
    conflict at every level. Non-dict values (lists, scalars) at any level
    are replaced wholesale by the patch value.
    """
    return _deep_merge(base, patch)


def _flatten_dict(data: Any, separator: str, prefix: str) -> dict[str, Any]:
    """Recursive helper for flatten_json."""
    items: dict[str, Any] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            key = f"{prefix}{separator}{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                items.update(_flatten_dict(v, separator, key))
            else:
                items[key] = v
    elif isinstance(data, list):
        for i, v in enumerate(data):
            key = f"{prefix}{separator}{i}" if prefix else str(i)
            if isinstance(v, (dict, list)):
                items.update(_flatten_dict(v, separator, key))
            else:
                items[key] = v
    else:
        items[prefix] = data
    return items


async def _flatten_json(data: Any, separator: str = ".") -> dict[str, Any]:
    """Flatten a nested dict/list into a flat dict with separator-joined keys.

    Example: ``{"a": {"b": 1}}`` → ``{"a.b": 1}``
    Arrays use integer indices: ``{"a": [1, 2]}`` → ``{"a.0": 1, "a.1": 2}``
    """
    if len(separator) == 0:
        raise ValueError("separator must be at least one character")
    return _flatten_dict(data, separator, "")


# ── Compound skill functions (exported for standalone use) ────────────────────


async def _json_transform(data: Any, mapping: dict[str, str]) -> dict[str, Any]:
    """Map fields from ``data`` to a new dict using a field-name mapping.

    ``mapping`` is a dict of ``{output_field: input_dotted_path}`` pairs.
    Each value is a dotted path into ``data`` (same syntax as ``json_path``).
    Missing or null paths produce ``null`` in the output, not an error.

    Example::

        data    = {"user": {"id": 1, "name": "Alice"}}
        mapping = {"id": "user.id", "username": "user.name"}
        → {"id": 1, "username": "Alice"}
    """
    result: dict[str, Any] = {}
    for out_key, in_path in mapping.items():
        try:
            result[out_key] = await _json_path(data, in_path)
        except (KeyError, IndexError):
            result[out_key] = None
    return result


async def _csv_filter(
    text: str,
    field: str,
    op: str,
    value: str,
    has_header: bool = True,
    delimiter: str = ",",
) -> str:
    """Parse a CSV, filter rows where ``field`` satisfies ``op`` against ``value``,
    and return the filtered CSV (with the original header preserved).

    Operators: eq, ne, contains, startswith, endswith, lt, le, gt, ge.
    All comparisons are string-based; numeric ops (lt/le/gt/ge) attempt a
    numeric coercion first and fall back to lexicographic comparison.
    """
    _check_size(text, "text")
    rows = await _parse_csv(text, has_header=has_header, delimiter=delimiter)
    if not rows:
        return ""

    def _compare(cell: str, op: str, val: str) -> bool:
        if op == "eq":
            return cell == val
        if op == "ne":
            return cell != val
        if op == "contains":
            return val in cell
        if op == "startswith":
            return cell.startswith(val)
        if op == "endswith":
            return cell.endswith(val)
        # Numeric comparisons — try float first
        try:
            c, v = float(cell), float(val)
        except (ValueError, TypeError):
            c, v = cell, val  # type: ignore[assignment]
        if op == "lt":
            return c < v
        if op == "le":
            return c <= v
        if op == "gt":
            return c > v
        if op == "ge":
            return c >= v
        raise ValueError(f"unknown op: {op!r}")

    if isinstance(rows[0], dict):
        filtered = [r for r in rows if isinstance(r, dict) and _compare(str(r.get(field, "")), op, value)]
    else:
        # No header: field is a column index
        try:
            col = int(field)
        except ValueError:
            raise ValueError("field must be a column index (integer) when has_header=false")
        filtered = [r for r in rows if isinstance(r, list) and len(r) > col and _compare(str(r[col]), op, value)]

    if not filtered:
        return ""
    return await _to_csv(filtered, delimiter=delimiter)


async def _data_profile(rows: list[dict]) -> str:
    """Profile a list-of-dicts dataset, returning a JSON column summary.

    For each column (union of all keys across rows) reports: the distinct
    Python types seen, null/missing count, number of distinct values, and a
    sample value. The top level also reports the total row count. Use this to
    understand the shape of an unfamiliar dataset before transforming it.
    """
    if not isinstance(rows, list):
        raise ValueError("rows must be a list of dicts")
    if not rows:
        return json.dumps({"row_count": 0, "columns": {}}, ensure_ascii=False)

    # Preserve first-seen column order.
    columns: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("every row must be a dict")
        for k in row:
            if k not in columns:
                columns.append(k)

    profile: dict[str, Any] = {}
    n = len(rows)
    for col in columns:
        present = [row[col] for row in rows if col in row and row[col] is not None]
        missing = n - len(present)
        types = sorted({type(v).__name__ for v in present})
        distinct: set[Any] = set()
        for v in present:
            distinct.add(
                json.dumps(v, sort_keys=True, ensure_ascii=False)
                if isinstance(v, (dict, list)) else v
            )
        profile[col] = {
            "types": types,
            "missing": missing,
            "distinct": len(distinct),
            "sample": present[0] if present else None,
        }
    return json.dumps({"row_count": n, "columns": profile}, ensure_ascii=False)


# ── Terr factory ──────────────────────────────────────────────────────────────


def data_terr() -> Terr:
    """Build the ``data`` Terr — JSON / CSV parsing, emission, and transformation.

    Primitive tools (standalone-callable):
        parse_json(text)                         → structured data
        to_json(value, indent)                   → JSON string
        parse_csv(text, has_header, delimiter)   → list of dicts or lists
        to_csv(rows, delimiter)                  → CSV string
        json_path(data, path)                    → dotted-path lookup
        merge_json(base, patch)                  → deep-merge patch into base
        flatten_json(data, separator)            → flatten nested structure

    Compound skills (orchestrate primitives):
        json_transform(data, mapping)            → field remap via dotted paths
        csv_filter(text, field, op, value)       → filter CSV rows
    """
    return Terr(
        name="data",
        description=(
            "JSON and CSV serialization, parsing, transformation, and filtering. "
            "Primitive tools for single data operations; compound skills for "
            "field remapping and row filtering."
        ),
        tools=[
            Tool(
                name="parse_json",
                description="Parse a JSON string into structured data.",
                fn=_parse_json,
                parameters=[
                    ToolParameter("text", "string", "The JSON text to parse."),
                ],
            ),
            Tool(
                name="to_json",
                description="Serialize structured data into a JSON string.",
                fn=_to_json,
                parameters=[
                    ToolParameter("value", "object", "The data to serialize.",
                                  extra={"description": "Any JSON-serializable value."}),
                    ToolParameter("indent", "integer",
                                  "Indent spaces for pretty-print, 0 for compact.",
                                  required=False),
                ],
            ),
            Tool(
                name="parse_csv",
                description="Parse a CSV string. Returns rows as dicts when has_header is true.",
                fn=_parse_csv,
                parameters=[
                    ToolParameter("text", "string", "The CSV text to parse."),
                    ToolParameter("has_header", "boolean",
                                  "Whether the first row is a header.",
                                  required=False),
                    ToolParameter("delimiter", "string",
                                  "Column delimiter, default ','.",
                                  required=False),
                ],
            ),
            Tool(
                name="to_csv",
                description="Serialize a list of dicts (or lists) into a CSV string.",
                fn=_to_csv,
                parameters=[
                    ToolParameter("rows", "array", "Rows to serialize.",
                                  extra={"items": {"type": "object"}}),
                    ToolParameter("delimiter", "string", "Column delimiter, default ','.",
                                  required=False),
                ],
            ),
            Tool(
                name="json_path",
                description=(
                    "Read a nested JSON value via a dotted path. "
                    "Example: 'users.0.name'."
                ),
                fn=_json_path,
                parameters=[
                    ToolParameter("data", "object", "The structured data to query."),
                    ToolParameter("path", "string", "Dotted path, e.g. 'a.b.0.c'."),
                ],
            ),
            Tool(
                name="merge_json",
                description=(
                    "Deep-merge a patch dict into a base dict. "
                    "Patch values win on conflict at every level. "
                    "Non-dict values are replaced wholesale."
                ),
                fn=_merge_json,
                parameters=[
                    ToolParameter("base", "object", "The base structure.",
                                  extra={"description": "Any JSON-serializable value."}),
                    ToolParameter("patch", "object", "The patch to apply.",
                                  extra={"description": "Any JSON-serializable value."}),
                ],
            ),
            Tool(
                name="flatten_json",
                description=(
                    "Flatten a nested dict/list into a flat dict with "
                    "separator-joined keys. E.g. {a:{b:1}} → {'a.b': 1}."
                ),
                fn=_flatten_json,
                parameters=[
                    ToolParameter("data", "object", "The nested structure to flatten.",
                                  extra={"description": "Any JSON-serializable value."}),
                    ToolParameter("separator", "string",
                                  "Key separator. Default '.'.",
                                  required=False),
                ],
            ),
        ],
        skills=[
            Skill(
                name="json_transform",
                description=(
                    "Remap fields from a JSON structure using a mapping dict. "
                    "Each entry is {output_field: input_dotted_path}. "
                    "Missing paths produce null in the output."
                ),
                handler=_json_transform,
                parameters=[
                    ToolParameter("data", "object",
                                  "The source JSON structure.",
                                  extra={"description": "Any JSON-serializable value."}),
                    ToolParameter("mapping", "object",
                                  "Dict mapping output field names to input dotted paths.",
                                  extra={"additionalProperties": {"type": "string"}}),
                ],
            ),
            Skill(
                name="csv_filter",
                description=(
                    "Parse a CSV and filter rows where a field satisfies a comparison. "
                    "Returns the filtered CSV (header preserved). "
                    "Operators: eq, ne, contains, startswith, endswith, lt, le, gt, ge."
                ),
                handler=_csv_filter,
                parameters=[
                    ToolParameter("text", "string", "The CSV text to filter."),
                    ToolParameter("field", "string",
                                  "Field name (with header) or column index (without)."),
                    ToolParameter("op", "string",
                                  "eq | ne | contains | startswith | endswith | lt | le | gt | ge.",
                                  extra={"enum": ["eq", "ne", "contains", "startswith",
                                                  "endswith", "lt", "le", "gt", "ge"]}),
                    ToolParameter("value", "string", "The value to compare against."),
                    ToolParameter("has_header", "boolean",
                                  "Whether the first row is a header. Default true.",
                                  required=False),
                    ToolParameter("delimiter", "string",
                                  "Column delimiter. Default ','.",
                                  required=False),
                ],
            ),
            Skill(
                name="data_profile",
                description=(
                    "Profile a list-of-dicts dataset and return a JSON column summary: "
                    "per-column types, missing count, distinct count, and a sample value, "
                    "plus the total row count. Use to understand an unfamiliar dataset."
                ),
                handler=_data_profile,
                parameters=[
                    ToolParameter("rows", "array", "The dataset as a list of dict rows.",
                                  extra={"items": {"type": "object"}}),
                ],
            ),
        ],
    )


__all__ = [
    "data_terr",
    # primitive fns
    "_parse_json", "_to_json", "_parse_csv", "_to_csv", "_json_path",
    "_merge_json", "_flatten_json",
    # compound skill fns
    "_json_transform", "_csv_filter", "_data_profile",
]

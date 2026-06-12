"""Data serialization capability domain.

Parse/emit JSON and CSV via stdlib. The model needs these so often (ingesting
a tool's stringified response or massaging output into a clean shape) that
forcing every agent author to wire them up by hand is wasteful.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from ..core.components.terr import Terr
from ..core.components.tool import Tool, ToolParameter

_MAX_INPUT = 1_000_000  # 1MB cap; protects the framework from OOM on bad input.


def _check_size(value: str, label: str) -> None:
    if len(value) > _MAX_INPUT:
        raise ValueError(f"{label} exceeds {_MAX_INPUT} chars")


async def _parse_json(text: str) -> Any:
    _check_size(text, "text")
    return json.loads(text)


async def _to_json(value: Any, indent: int = 0) -> str:
    pretty = indent if indent > 0 else None
    return json.dumps(value, ensure_ascii=False, indent=pretty)


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
    return buf.getvalue()


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


def data_terr() -> Terr:
    """Build the ``data`` Terr — JSON / CSV parsing and emission."""
    return Terr(
        name="data",
        description="JSON and CSV serialization, parsing, and dotted-path lookup.",
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
        ],
    )

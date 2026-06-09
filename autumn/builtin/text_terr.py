"""Text processing capability domain.

Regex and counting primitives the model frequently needs to ground its output —
``count_words`` for token budgeting, ``regex_find`` for structured extraction,
``extract_urls`` for follow-up fetches. Inputs are size-bounded to limit
ReDoS exposure (Python's :mod:`re` has no native timeout).
"""
from __future__ import annotations

import re

from ..core.components.terr import Terr
from ..core.components.tool import Tool, ToolParameter


_MAX_INPUT = 200_000  # ~200KB; the model rarely benefits from larger inputs.
_MAX_MATCHES = 200
_MAX_PATTERN = 1024


def _check_size(text: str, label: str = "text") -> None:
    if len(text) > _MAX_INPUT:
        raise ValueError(f"{label} exceeds {_MAX_INPUT} chars")


_URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)


async def _count(text: str, unit: str = "words") -> str:
    _check_size(text)
    if unit == "words":
        return str(len(text.split()))
    if unit == "chars":
        return str(len(text))
    if unit == "lines":
        return str(text.count("\n") + (1 if text and not text.endswith("\n") else 0))
    if unit == "non_whitespace_chars":
        return str(sum(1 for c in text if not c.isspace()))
    raise ValueError(f"unknown unit: {unit}")


async def _regex_find(text: str, pattern: str, flags: str = "") -> list[str]:
    _check_size(text)
    if len(pattern) > _MAX_PATTERN:
        raise ValueError("pattern too long")
    flag_value = 0
    for ch in flags:
        if ch == "i":
            flag_value |= re.IGNORECASE
        elif ch == "m":
            flag_value |= re.MULTILINE
        elif ch == "s":
            flag_value |= re.DOTALL
        else:
            raise ValueError(f"unsupported flag: {ch!r}")
    compiled = re.compile(pattern, flag_value)
    matches = compiled.findall(text)
    # findall returns tuples when there are >1 groups — stringify.
    out: list[str] = []
    for m in matches[:_MAX_MATCHES]:
        if isinstance(m, tuple):
            out.append(" | ".join(m))
        else:
            out.append(m)
    return out


async def _extract_urls(text: str) -> list[str]:
    _check_size(text)
    seen: set[str] = set()
    urls: list[str] = []
    for m in _URL_RE.findall(text):
        if m not in seen:
            seen.add(m)
            urls.append(m)
            if len(urls) >= _MAX_MATCHES:
                break
    return urls


async def _split(text: str, separator: str = "\n", max_splits: int = -1) -> list[str]:
    _check_size(text)
    if max_splits < 0:
        return text.split(separator)
    return text.split(separator, max_splits)


async def _replace(text: str, find: str, replace_with: str) -> str:
    _check_size(text)
    if len(find) > _MAX_PATTERN:
        raise ValueError("find pattern too long")
    return text.replace(find, replace_with)


def text_terr() -> Terr:
    """Build the ``text`` Terr — string counting, regex, URL extraction."""
    return Terr(
        name="text",
        description="String counting, regex matching, URL extraction.",
        tools=[
            Tool(
                name="count_text",
                description="Count words, characters, or lines in a string.",
                fn=_count,
                parameters=[
                    ToolParameter("text", "string", "The text to measure."),
                    ToolParameter("unit", "string",
                                  "words | chars | lines | non_whitespace_chars.",
                                  required=False,
                                  extra={"enum": ["words", "chars", "lines",
                                                  "non_whitespace_chars"]}),
                ],
            ),
            Tool(
                name="regex_find",
                description="Find all regex matches. Flags: i (case), m (multiline), s (dotall).",
                fn=_regex_find,
                parameters=[
                    ToolParameter("text", "string", "The text to search."),
                    ToolParameter("pattern", "string", "Python regex pattern."),
                    ToolParameter("flags", "string",
                                  "Concatenation of i/m/s, e.g. 'im'.",
                                  required=False),
                ],
            ),
            Tool(
                name="extract_urls",
                description="Extract all http(s) URLs from a string.",
                fn=_extract_urls,
                parameters=[
                    ToolParameter("text", "string", "The text to scan."),
                ],
            ),
            Tool(
                name="split_text",
                description="Split a string by a separator.",
                fn=_split,
                parameters=[
                    ToolParameter("text", "string", "The text to split."),
                    ToolParameter("separator", "string",
                                  "Separator. Default newline.",
                                  required=False),
                    ToolParameter("max_splits", "integer",
                                  "Maximum splits, -1 for unlimited.",
                                  required=False),
                ],
            ),
            Tool(
                name="replace_text",
                description="Replace literal occurrences of a substring.",
                fn=_replace,
                parameters=[
                    ToolParameter("text", "string", "The text to transform."),
                    ToolParameter("find", "string", "Substring to replace."),
                    ToolParameter("replace_with", "string", "Replacement string."),
                ],
            ),
        ],
    )


# Re-export helpers so callers/tests can reuse the size limits.
__all__ = ["text_terr", "_MAX_INPUT", "_MAX_MATCHES"]

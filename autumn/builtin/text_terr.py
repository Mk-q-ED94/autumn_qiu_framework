"""Text processing capability domain.

Regex and counting primitives the model frequently needs to ground its output —
``count_words`` for token budgeting, ``regex_find`` for structured extraction,
``extract_urls`` for follow-up fetches. Inputs are size-bounded to limit
ReDoS exposure (Python's :mod:`re` has no native timeout).

Primitive tools (standalone-callable):
    count_text, regex_find, extract_urls, split_text, replace_text,
    extract_emails, extract_numbers, text_truncate, regex_replace

Compound skills (orchestrate multiple primitives):
    text_diff, text_normalize
"""
from __future__ import annotations

import difflib
import re
import unicodedata

from ..core.components.skill import Skill
from ..core.components.terr import Terr
from ..core.components.tool import Tool, ToolParameter

_MAX_INPUT = 200_000  # ~200KB; the model rarely benefits from larger inputs.
_MAX_MATCHES = 200
_MAX_PATTERN = 1024


def _check_size(text: str, label: str = "text") -> None:
    if len(text) > _MAX_INPUT:
        raise ValueError(f"{label} exceeds {_MAX_INPUT} chars")


_URL_RE = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")

_RE_FLAG_MAP = {"i": re.IGNORECASE, "m": re.MULTILINE, "s": re.DOTALL}


def _parse_flags(flags: str) -> int:
    value = 0
    for ch in flags:
        if ch not in _RE_FLAG_MAP:
            raise ValueError(f"unsupported flag: {ch!r}")
        value |= _RE_FLAG_MAP[ch]
    return value


# ── Primitive tool functions (exported for standalone use) ────────────────────


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
    compiled = re.compile(pattern, _parse_flags(flags))
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


async def _extract_emails(text: str) -> list[str]:
    """Extract all email addresses from text, deduplicated and in order."""
    _check_size(text)
    seen: set[str] = set()
    emails: list[str] = []
    for m in _EMAIL_RE.findall(text):
        if m not in seen:
            seen.add(m)
            emails.append(m)
            if len(emails) >= _MAX_MATCHES:
                break
    return emails


async def _extract_numbers(text: str) -> list[str]:
    """Extract all numeric values (integers, floats, scientific notation) from text."""
    _check_size(text)
    return _NUMBER_RE.findall(text)[:_MAX_MATCHES]


async def _text_truncate(text: str, max_chars: int, suffix: str = "...") -> str:
    """Truncate text to at most max_chars, appending suffix when truncated."""
    _check_size(text)
    if max_chars < 0:
        raise ValueError("max_chars must be non-negative")
    if len(text) <= max_chars:
        return text
    trim = max(0, max_chars - len(suffix))
    return text[:trim] + suffix


async def _regex_replace(text: str, pattern: str, replacement: str, flags: str = "") -> str:
    """Replace regex matches in text with replacement. Supports backreferences."""
    _check_size(text)
    if len(pattern) > _MAX_PATTERN:
        raise ValueError("pattern too long")
    return re.sub(pattern, replacement, text, flags=_parse_flags(flags))


# ── Compound skill functions (exported for standalone use) ────────────────────


async def _text_diff(a: str, b: str) -> str:
    """Return a unified diff between two strings, line by line.

    Compares ``a`` (labelled 'before') and ``b`` (labelled 'after') using
    Python's difflib, returning a unified diff string.  Returns '(no differences)'
    when the strings are identical.
    """
    _check_size(a, "a")
    _check_size(b, "b")
    a_lines = a.splitlines(keepends=True)
    b_lines = b.splitlines(keepends=True)
    diff = list(difflib.unified_diff(a_lines, b_lines, fromfile="before", tofile="after"))
    return "".join(diff) if diff else "(no differences)"


async def _text_normalize(text: str) -> str:
    """Normalize text: NFC Unicode, collapse internal whitespace, strip edges.

    Within each line, consecutive whitespace is collapsed to a single space.
    Newlines between lines are preserved. Leading/trailing whitespace on each
    line and at the document level is removed.
    """
    _check_size(text)
    normalized = unicodedata.normalize("NFC", text)
    lines = [" ".join(line.split()) for line in normalized.splitlines()]
    return "\n".join(lines).strip()


# ── Terr factory ──────────────────────────────────────────────────────────────


def text_terr() -> Terr:
    """Build the ``text`` Terr — string counting, regex, extraction, and diff.

    Primitive tools (standalone-callable):
        count_text(text, unit)                    → word/char/line count
        regex_find(text, pattern, flags)          → all regex matches
        extract_urls(text)                        → http(s) URLs
        split_text(text, separator, max_splits)   → split by separator
        replace_text(text, find, replace_with)    → literal substring replace
        extract_emails(text)                      → email addresses
        extract_numbers(text)                     → numeric values
        text_truncate(text, max_chars, suffix)    → safe truncation
        regex_replace(text, pattern, replacement) → regex-based substitution

    Compound skills (orchestrate primitives):
        text_diff(a, b)                           → unified diff
        text_normalize(text)                      → NFC + collapse whitespace
    """
    return Terr(
        name="text",
        description=(
            "String counting, regex matching, extraction, and transformation. "
            "Primitive tools for single operations; compound skills for diff "
            "and normalization."
        ),
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
            Tool(
                name="extract_emails",
                description="Extract all email addresses from a string, deduplicated and in order.",
                fn=_extract_emails,
                parameters=[
                    ToolParameter("text", "string", "The text to scan."),
                ],
            ),
            Tool(
                name="extract_numbers",
                description=(
                    "Extract all numeric values (integers, floats, scientific notation) "
                    "from a string as a list of strings."
                ),
                fn=_extract_numbers,
                parameters=[
                    ToolParameter("text", "string", "The text to scan."),
                ],
            ),
            Tool(
                name="text_truncate",
                description=(
                    "Truncate text to at most max_chars characters, "
                    "appending suffix (default '...') when truncated."
                ),
                fn=_text_truncate,
                parameters=[
                    ToolParameter("text", "string", "The text to truncate."),
                    ToolParameter("max_chars", "integer",
                                  "Maximum character count in the output."),
                    ToolParameter("suffix", "string",
                                  "Suffix to append when truncated. Default '...'.",
                                  required=False),
                ],
            ),
            Tool(
                name="regex_replace",
                description=(
                    "Replace regex matches in text with a replacement string. "
                    "Supports backreferences (\\1, \\g<name>). "
                    "Flags: i (case), m (multiline), s (dotall)."
                ),
                fn=_regex_replace,
                parameters=[
                    ToolParameter("text", "string", "The text to transform."),
                    ToolParameter("pattern", "string", "Python regex pattern."),
                    ToolParameter("replacement", "string",
                                  "Replacement string (backreferences allowed)."),
                    ToolParameter("flags", "string",
                                  "Concatenation of i/m/s.",
                                  required=False),
                ],
            ),
        ],
        skills=[
            Skill(
                name="text_diff",
                description=(
                    "Return a unified diff between two strings (line-by-line). "
                    "Labels the first string 'before' and the second 'after'. "
                    "Returns '(no differences)' when the strings are identical."
                ),
                handler=_text_diff,
                parameters=[
                    ToolParameter("a", "string", "The 'before' text."),
                    ToolParameter("b", "string", "The 'after' text."),
                ],
            ),
            Skill(
                name="text_normalize",
                description=(
                    "Normalize text: apply NFC Unicode normalization, collapse "
                    "consecutive whitespace within each line to a single space, "
                    "and strip leading/trailing whitespace."
                ),
                handler=_text_normalize,
                parameters=[
                    ToolParameter("text", "string", "The text to normalize."),
                ],
            ),
        ],
    )


# Re-export helpers so callers/tests can reuse the size limits.
__all__ = [
    "text_terr",
    "_MAX_INPUT",
    "_MAX_MATCHES",
    # primitive fns
    "_count", "_regex_find", "_extract_urls", "_split", "_replace",
    "_extract_emails", "_extract_numbers", "_text_truncate", "_regex_replace",
    # compound skill fns
    "_text_diff", "_text_normalize",
]

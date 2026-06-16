"""Knowledge / external-retrieval capability domain (0.3.0).

This Terr exists for the cooperative-workflow's A4 augmentation path: A4 is a
weak local model with no inherent access to the outside world, so it borrows
this domain's skills (via :meth:`WP4Mem.research`) to gather facts it cannot
recall — web search, document fetch, and a query into the local knowledge zone.

The same skills are ordinary Terr skills, so A2/A3 can use them too once the
domain is registered. Fetches go through the shared :mod:`autumn.builtin._http`
helper, which streams a 2MB size cap and refuses private/loopback/metadata
targets by default (set ``AUTUMN_ALLOW_PRIVATE_NETWORK=1`` to allow them).
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from ..core.components.skill import Skill
from ..core.components.terr import Terr
from ..core.components.tool import ToolParameter
from ._http import (
    FetchError,
    clean_inline,
    ddg_unwrap,
    is_text_content,
    looks_like_html,
    safe_fetch,
    strip_html,
)

_DDG_HTML = "https://html.duckduckgo.com/html/"

# DuckDuckGo HTML result anchors and snippets (no API key required).
_RESULT_A_RE = re.compile(
    r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def _parse_ddg_results(html: str, count: int) -> list[tuple[str, str, str]]:
    """Parse DDG HTML into ``[(title, url, snippet)]``, snippet aligned to its anchor.

    DDG hrefs are ``/l/?uddg=`` redirectors (unwrapped to the real destination),
    and snippet/title pairing is positional in the source — so each snippet is
    taken from the window *between this result anchor and the next* rather than a
    parallel ``findall``, which silently misaligns when a result lacks a snippet.
    """
    anchors = list(_RESULT_A_RE.finditer(html))
    results: list[tuple[str, str, str]] = []
    for i, m in enumerate(anchors[:count]):
        url = ddg_unwrap(m.group(1))
        title = clean_inline(m.group(2)) or "(untitled)"
        window_end = anchors[i + 1].start() if i + 1 < len(anchors) else len(html)
        sm = _SNIPPET_RE.search(html, m.end(), window_end)
        snippet = clean_inline(sm.group(1)) if sm else ""
        results.append((title, url, snippet))
    return results


async def _ddg_search(query: str, max_results: int = 5) -> str:
    """Skill: search the web via DuckDuckGo's keyless HTML endpoint.

    Returns a numbered list of ``title — url`` lines with snippets, or a clear
    message when the search returns nothing or the endpoint is unreachable.
    """
    try:
        count = max(1, min(int(max_results), 10))
    except (TypeError, ValueError):
        count = 5
    try:
        _, html, _ = await safe_fetch(
            _DDG_HTML,
            method="POST",
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (compatible; Autumn/0.3)"},
        )
    except FetchError as e:
        return f"[web_search failed: {e}]"

    results = _parse_ddg_results(html, count)
    if not results:
        return f"[web_search: no results for {query!r}]"

    lines: list[str] = []
    for i, (title, url, snippet) in enumerate(results):
        line = f"{i + 1}. {title} — {url}"
        if snippet:
            line += f"\n   {snippet}"
        lines.append(line)
    return "\n".join(lines)


async def _fetch_document(url: str, max_chars: int = 20_000) -> str:
    """Skill: fetch a URL and return readable text (HTML stripped if needed)."""
    try:
        _, body, content_type = await safe_fetch(url)
    except FetchError as e:
        return f"[fetch_document failed: {e}]"

    if not is_text_content(content_type):
        return f"[fetch_document: non-text content-type {content_type!r}; nothing to read]"
    text = strip_html(body) if looks_like_html(content_type, body) else body
    try:
        limit = max(500, int(max_chars))
    except (TypeError, ValueError):
        limit = 20_000
    if len(text) > limit:
        return text[:limit] + f"\n[truncated at {limit} chars]"
    return text


def knowledge_terr(
    recall_fn: Callable[[str, int], Awaitable[str]] | None = None,
) -> Terr:
    """Build the ``knowledge`` Terr — web search, document fetch, KB query.

    Parameters
    ----------
    recall_fn:
        Optional ``async (query, k) -> str`` that searches a local knowledge
        store and returns formatted snippets. When omitted, ``knowledge_base_query``
        reports that no local store is wired. The framework supplies one bound to
        the shared memory zone when it registers this Terr.
    """

    async def _knowledge_base_query(query: str, k: int = 5) -> str:
        if recall_fn is None:
            return "[knowledge_base_query unavailable: no local knowledge store configured]"
        try:
            n = max(1, min(int(k), 20))
        except (TypeError, ValueError):
            n = 5
        try:
            return await recall_fn(query, n)
        except Exception as e:  # noqa: BLE001 — surface to the model, never crash the loop
            return f"[knowledge_base_query failed: {e}]"

    return Terr(
        name="knowledge",
        description=(
            "External knowledge retrieval: web search, document fetch, and a query "
            "into the local knowledge store. A4 uses this to ground memory work in "
            "facts no local model holds on its own."
        ),
        skills=[
            Skill(
                name="web_search",
                description=(
                    "Search the web (DuckDuckGo, no API key) and return the top "
                    "results as title/url/snippet lines."
                ),
                handler=_ddg_search,
                parameters=[
                    ToolParameter("query", "string", "What to search for."),
                    ToolParameter(
                        "max_results", "integer",
                        "How many results to return (1–10, default 5).",
                        required=False,
                    ),
                ],
            ),
            Skill(
                name="fetch_document",
                description=(
                    "Fetch a URL and return its readable text, stripping HTML "
                    "(scripts/styles dropped) and collapsing whitespace."
                ),
                handler=_fetch_document,
                parameters=[
                    ToolParameter("url", "string", "URL to fetch (http or https)."),
                    ToolParameter(
                        "max_chars", "integer",
                        "Truncate output beyond this length (default 20000).",
                        required=False,
                    ),
                ],
            ),
            Skill(
                name="knowledge_base_query",
                description=(
                    "Query the local knowledge store for previously-saved facts "
                    "relevant to a natural-language question."
                ),
                handler=_knowledge_base_query,
                parameters=[
                    ToolParameter("query", "string", "What to look up locally."),
                    ToolParameter(
                        "k", "integer",
                        "Max entries to return (1–20, default 5).",
                        required=False,
                    ),
                ],
            ),
        ],
    )


__all__ = ["knowledge_terr"]

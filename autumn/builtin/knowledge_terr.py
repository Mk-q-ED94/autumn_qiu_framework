"""Knowledge / external-retrieval capability domain (0.3.0).

This Terr exists for the cooperative-workflow's A4 augmentation path: A4 is a
weak local model with no inherent access to the outside world, so it borrows
this domain's skills (via :meth:`WP4Mem.research`) to gather facts it cannot
recall — web search, document fetch, and a query into the local knowledge zone.

The same skills are ordinary Terr skills, so A2/A3 can use them too once the
domain is registered. Network access is the caller's responsibility — there is
no SSRF guard (same posture as :mod:`autumn.builtin.web_terr`).
"""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from html import unescape

import httpx

from ..core.components.skill import Skill
from ..core.components.terr import Terr
from ..core.components.tool import ToolParameter

_DEFAULT_TIMEOUT = 15.0
_MAX_BYTES = 2_000_000  # 2MB cap per response
_DDG_HTML = "https://html.duckduckgo.com/html/"

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"\s+")

# DuckDuckGo HTML result anchors and snippets (no API key required).
_RESULT_A_RE = re.compile(
    r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)


def _strip_html(html: str) -> str:
    """Crude HTML → text: drop <script>/<style>, then tags, then collapse whitespace."""
    no_scripts = _SCRIPT_RE.sub("", html)
    no_styles = _STYLE_RE.sub("", no_scripts)
    text = _TAG_RE.sub(" ", no_styles)
    return _WS_RE.sub(" ", unescape(text)).strip()


def _clean_inline(html_fragment: str) -> str:
    """Strip tags from a small inline fragment (a title or snippet)."""
    return _WS_RE.sub(" ", unescape(_TAG_RE.sub("", html_fragment))).strip()


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
        async with httpx.AsyncClient(follow_redirects=True, timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.post(
                _DDG_HTML,
                data={"q": query},
                headers={"User-Agent": "Mozilla/5.0 (compatible; Autumn/0.3)"},
            )
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPError as e:
        return f"[web_search failed: {e}]"

    titles = _RESULT_A_RE.findall(html)
    snippets = [_clean_inline(s) for s in _SNIPPET_RE.findall(html)]
    if not titles:
        return f"[web_search: no results for {query!r}]"

    lines: list[str] = []
    for i, (href, raw_title) in enumerate(titles[:count]):
        title = _clean_inline(raw_title) or "(untitled)"
        snippet = snippets[i] if i < len(snippets) else ""
        line = f"{i + 1}. {title} — {href}"
        if snippet:
            line += f"\n   {snippet}"
        lines.append(line)
    return "\n".join(lines)


async def _fetch_document(url: str, max_chars: int = 20_000) -> str:
    """Skill: fetch a URL and return readable text (HTML stripped if needed)."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=_DEFAULT_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            if len(resp.content) > _MAX_BYTES:
                return f"[fetch_document failed: response exceeds {_MAX_BYTES} bytes]"
            body = resp.text
    except httpx.HTTPError as e:
        return f"[fetch_document failed: {e}]"

    looks_html = "<" in body[:512] and ">" in body[:512]
    text = _strip_html(body) if looks_html else body
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

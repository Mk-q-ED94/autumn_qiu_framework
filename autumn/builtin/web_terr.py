"""Web / HTTP capability domain.

Uses ``httpx`` (already a core Autumn dependency) so no new install is needed.
Tools are opt-in because they make network requests. Fetches go through the
shared :mod:`autumn.builtin._http` helper, which streams a 2MB size cap and
refuses private/loopback/metadata targets by default (the model picks the URL);
set ``AUTUMN_ALLOW_PRIVATE_NETWORK=1`` to fetch internal hosts.

Primitive tools (standalone-callable):
    http_get, http_get_json, http_head, http_post, parse_url, build_url

Compound skills (orchestrate multiple primitives):
    fetch_text, batch_fetch
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from ..core.components.skill import Skill
from ..core.components.terr import Terr
from ..core.components.tool import Tool, ToolParameter
from ._http import (
    _DEFAULT_TIMEOUT,
    FetchError,
    clean_inline,
    looks_like_html,
    safe_fetch,
    safe_head,
    strip_html,
)

# Crude HTML extractors — consistent with _http.strip_html's regex approach
# (the codebase deliberately avoids pulling in a heavyweight HTML parser).
_HREF_RE = re.compile(r'<a\b[^>]*?\bhref\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_IMG_RE = re.compile(r'<img\b[^>]*?\bsrc\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_META_RE = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_META_ATTR_RE = re.compile(
    r'(name|property|content)\s*=\s*["\']([^"\']*)["\']', re.IGNORECASE
)
_TABLE_RE = re.compile(r"<table\b[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)
_TR_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<(?:td|th)\b[^>]*>(.*?)</(?:td|th)>", re.IGNORECASE | re.DOTALL)


# ── Primitive tool functions (exported for standalone use) ────────────────────


async def _http_get(url: str, timeout: float = _DEFAULT_TIMEOUT) -> str:
    _, body, _ = await safe_fetch(url, timeout=timeout)
    return body


async def _http_get_json(url: str, timeout: float = _DEFAULT_TIMEOUT) -> Any:
    _, body, _ = await safe_fetch(url, timeout=timeout)
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise FetchError(f"response was not valid JSON: {e}") from e


async def _http_head(url: str, timeout: float = _DEFAULT_TIMEOUT) -> dict[str, Any]:
    # safe_head re-validates every redirect hop (no SSRF-via-redirect) and drops
    # sensitive response headers. A 4xx status is surfaced, not raised.
    status, final_url, headers = await safe_head(url, timeout=timeout)
    return {"status": status, "url": final_url, "headers": headers}


async def _http_post(
    url: str,
    data: dict | str | None = None,
    headers: dict | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> str:
    """POST to a URL and return the response body as text.

    If ``data`` is a dict, it is serialized to JSON and sent with
    Content-Type: application/json.  If ``data`` is a string it is sent
    as the raw body.  Pass custom ``headers`` to override Content-Type or
    add auth tokens.
    """
    req_headers: dict[str, str] = {}
    if headers:
        req_headers.update(headers)

    if isinstance(data, dict):
        body_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
        _, response_body, _ = await safe_fetch(
            url, method="POST", content=body_bytes, headers=req_headers, timeout=timeout
        )
    elif isinstance(data, str):
        _, response_body, _ = await safe_fetch(
            url, method="POST", content=data, headers=req_headers or None, timeout=timeout
        )
    else:
        _, response_body, _ = await safe_fetch(
            url, method="POST", headers=req_headers or None, timeout=timeout
        )
    return response_body


async def _parse_url(url: str) -> dict[str, Any]:
    """Parse a URL into its components: scheme, host, path, query, fragment, params."""
    parts = urlsplit(url)
    return {
        "scheme": parts.scheme,
        "host": parts.netloc,
        "path": parts.path,
        "query": parts.query,
        "fragment": parts.fragment,
        "params": {
            k: v[0] if len(v) == 1 else v
            for k, v in parse_qs(parts.query).items()
        },
    }


async def _build_url(
    base: str,
    path: str = "",
    params: dict | None = None,
) -> str:
    """Construct a URL from a base, optional path suffix, and optional query params.

    Merges ``path`` onto ``base`` using standard URL joining semantics,
    then appends ``params`` as a query string.
    """
    url = urljoin(base, path) if path else base
    if params:
        query = urlencode({k: v for k, v in params.items()}, doseq=True)
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{query}"
    return url


# ── Compound skill functions (exported for standalone use) ────────────────────


async def _fetch_text(url: str, timeout: float = _DEFAULT_TIMEOUT, max_chars: int = 20_000) -> str:
    """Skill: GET ``url`` and return readable text (HTML stripped if needed)."""
    _, body, content_type = await safe_fetch(url, timeout=timeout)
    text = strip_html(body) if looks_like_html(content_type, body) else body
    if len(text) > max_chars:
        return text[:max_chars] + f"\n[truncated at {max_chars} chars]"
    return text


async def _batch_fetch(
    urls: list[str],
    max_chars: int = 10_000,
    timeout: float = _DEFAULT_TIMEOUT,
) -> list[dict[str, Any]]:
    """Skill: fetch multiple URLs in parallel and return readable text for each.

    Returns a list of ``{url, content, error}`` dicts.  ``content`` is the
    readable text (HTML stripped); ``error`` is a string when the fetch failed.
    At most 20 URLs per call; parallel fetches share the same timeout.
    """
    if len(urls) > 20:
        raise ValueError("batch_fetch supports at most 20 URLs per call")

    async def _one(url: str) -> dict[str, Any]:
        try:
            _, body, content_type = await safe_fetch(url, timeout=timeout)
            text = strip_html(body) if looks_like_html(content_type, body) else body
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n[truncated at {max_chars} chars]"
            return {"url": url, "content": text, "error": None}
        except Exception as e:  # noqa: BLE001
            return {"url": url, "content": None, "error": str(e)}

    return list(await asyncio.gather(*[_one(u) for u in urls]))


async def _extract_links(url: str, timeout: float = _DEFAULT_TIMEOUT) -> list[str]:
    """Skill: fetch a page and return all hyperlink targets as absolute URLs.

    Relative hrefs are resolved against the page URL; ``#`` fragments and
    ``javascript:``/``mailto:`` pseudo-links are dropped. Results are
    deduplicated, preserving first-seen order.
    """
    _, body, _ = await safe_fetch(url, timeout=timeout)
    seen: set[str] = set()
    links: list[str] = []
    for href in _HREF_RE.findall(body):
        href = href.strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(url, href)
        if absolute not in seen:
            seen.add(absolute)
            links.append(absolute)
    return links


async def _extract_metadata(url: str, timeout: float = _DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Skill: fetch a page and extract its title and ``<meta>`` tags.

    Returns ``{title, description, meta}`` where ``meta`` maps each
    name/property (e.g. ``og:title``, ``twitter:card``) to its content. Useful
    for link previews and quick page summaries without reading the full body.
    """
    _, body, _ = await safe_fetch(url, timeout=timeout)
    title_m = _TITLE_RE.search(body)
    title = clean_inline(title_m.group(1)) if title_m else ""

    meta: dict[str, str] = {}
    for tag in _META_RE.findall(body):
        attrs = {k.lower(): v for k, v in _META_ATTR_RE.findall(tag)}
        key = attrs.get("name") or attrs.get("property")
        if key and "content" in attrs:
            meta[key] = clean_inline(attrs["content"])

    description = meta.get("description") or meta.get("og:description", "")
    return {"url": url, "title": title, "description": description, "meta": meta}


async def _extract_tables(url: str, timeout: float = _DEFAULT_TIMEOUT) -> list[list[list[str]]]:
    """Skill: fetch a page and extract its HTML tables as nested arrays.

    Returns a list of tables; each table is a list of rows; each row is a list
    of cell texts (tags stripped, whitespace collapsed). At most 20 tables and
    200 rows per table are returned to bound output size.
    """
    _, body, _ = await safe_fetch(url, timeout=timeout)
    tables: list[list[list[str]]] = []
    for table_html in _TABLE_RE.findall(body)[:20]:
        rows: list[list[str]] = []
        for row_html in _TR_RE.findall(table_html)[:200]:
            cells = [clean_inline(c) for c in _CELL_RE.findall(row_html)]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


# ── Terr factory ──────────────────────────────────────────────────────────────


def web_terr() -> Terr:
    """Build the ``web`` Terr — HTTP requests, URL utilities, and text extraction.

    Fetches stream a 2MB cap and refuse private/loopback/metadata hosts by
    default (the model picks the URL). Set ``AUTUMN_ALLOW_PRIVATE_NETWORK=1`` to
    permit internal hosts; a proxy/container is still wise for stronger control.

    Primitive tools (standalone-callable):
        http_get(url, timeout)              → GET → response body text
        http_get_json(url, timeout)         → GET → parsed JSON
        http_head(url, timeout)             → HEAD → {status, url, headers}
        http_post(url, data, headers)       → POST (JSON dict or raw str) → text
        parse_url(url)                      → decompose URL into components
        build_url(base, path, params)       → assemble URL from parts

    Compound skills (orchestrate primitives):
        fetch_text(url, timeout, max_chars) → GET + HTML strip → readable text
        batch_fetch(urls, max_chars)        → parallel fetch up to 20 URLs
    """
    return Terr(
        name="web",
        description=(
            "HTTP GET, HEAD, POST, JSON fetch, URL construction, and text "
            "extraction from web pages. Batch fetch for parallel retrieval."
        ),
        tools=[
            Tool(
                name="http_get",
                description="GET a URL and return the response body as text.",
                fn=_http_get,
                parameters=[
                    ToolParameter("url", "string", "URL to fetch (http or https)."),
                    ToolParameter("timeout", "number",
                                  "Request timeout in seconds.",
                                  required=False),
                ],
            ),
            Tool(
                name="http_get_json",
                description="GET a URL and parse the response body as JSON.",
                fn=_http_get_json,
                parameters=[
                    ToolParameter("url", "string", "URL returning JSON."),
                    ToolParameter("timeout", "number",
                                  "Request timeout in seconds.",
                                  required=False),
                ],
            ),
            Tool(
                name="http_head",
                description=(
                    "HEAD a URL and return {status, url, headers}. "
                    "Useful for cheap reachability checks."
                ),
                fn=_http_head,
                parameters=[
                    ToolParameter("url", "string", "URL to probe."),
                    ToolParameter("timeout", "number",
                                  "Request timeout in seconds.",
                                  required=False),
                ],
            ),
            Tool(
                name="http_post",
                description=(
                    "POST to a URL and return the response body as text. "
                    "If data is a dict it is JSON-serialized (Content-Type: application/json). "
                    "If data is a string it is sent as the raw body."
                ),
                fn=_http_post,
                parameters=[
                    ToolParameter("url", "string", "URL to POST to (http or https)."),
                    ToolParameter("data", "object",
                                  "Request body: a dict (→ JSON) or string (→ raw).",
                                  required=False,
                                  extra={"description": "Dict or string body."}),
                    ToolParameter("headers", "object",
                                  "Additional request headers.",
                                  required=False,
                                  extra={"additionalProperties": {"type": "string"}}),
                    ToolParameter("timeout", "number",
                                  "Request timeout in seconds.",
                                  required=False),
                ],
            ),
            Tool(
                name="parse_url",
                description=(
                    "Parse a URL into its components: scheme, host, path, "
                    "query, fragment, and a params dict of decoded query parameters."
                ),
                fn=_parse_url,
                parameters=[
                    ToolParameter("url", "string", "The URL to parse."),
                ],
            ),
            Tool(
                name="build_url",
                description=(
                    "Construct a URL from a base, optional path, and optional "
                    "query parameters dict."
                ),
                fn=_build_url,
                parameters=[
                    ToolParameter("base", "string", "Base URL."),
                    ToolParameter("path", "string",
                                  "Path to append/join onto base.",
                                  required=False),
                    ToolParameter("params", "object",
                                  "Query parameters to append.",
                                  required=False,
                                  extra={"additionalProperties": True}),
                ],
            ),
        ],
        skills=[
            Skill(
                name="fetch_text",
                description=(
                    "Fetch a URL and return readable text, stripping HTML tags "
                    "(scripts/styles dropped) and collapsing whitespace."
                ),
                handler=_fetch_text,
                parameters=[
                    ToolParameter("url", "string", "URL to fetch."),
                    ToolParameter("timeout", "number",
                                  "Request timeout in seconds.",
                                  required=False),
                    ToolParameter("max_chars", "integer",
                                  "Truncate output beyond this length.",
                                  required=False),
                ],
            ),
            Skill(
                name="batch_fetch",
                description=(
                    "Fetch up to 20 URLs in parallel and return a list of "
                    "{url, content, error} dicts. HTML is stripped; content "
                    "is truncated at max_chars per URL."
                ),
                handler=_batch_fetch,
                parameters=[
                    ToolParameter("urls", "array", "List of URLs to fetch (max 20).",
                                  extra={"items": {"type": "string"}}),
                    ToolParameter("max_chars", "integer",
                                  "Max chars per page. Default 10000.",
                                  required=False),
                    ToolParameter("timeout", "number",
                                  "Request timeout in seconds per URL.",
                                  required=False),
                ],
            ),
            Skill(
                name="extract_links",
                description=(
                    "Fetch a page and return all hyperlink targets as absolute URLs "
                    "(relative hrefs resolved; fragments and js/mailto links dropped; "
                    "deduplicated in order)."
                ),
                handler=_extract_links,
                parameters=[
                    ToolParameter("url", "string", "The page URL to scrape links from."),
                    ToolParameter("timeout", "number",
                                  "Request timeout in seconds.",
                                  required=False),
                ],
            ),
            Skill(
                name="extract_metadata",
                description=(
                    "Fetch a page and extract its title and <meta> tags (including "
                    "OpenGraph/Twitter). Returns {url, title, description, meta}. "
                    "Ideal for link previews and quick page summaries."
                ),
                handler=_extract_metadata,
                parameters=[
                    ToolParameter("url", "string", "The page URL to inspect."),
                    ToolParameter("timeout", "number",
                                  "Request timeout in seconds.",
                                  required=False),
                ],
            ),
            Skill(
                name="extract_tables",
                description=(
                    "Fetch a page and extract its HTML tables as nested arrays "
                    "(list of tables → rows → cell texts). Tags stripped; "
                    "bounded to 20 tables and 200 rows each."
                ),
                handler=_extract_tables,
                parameters=[
                    ToolParameter("url", "string", "The page URL to scrape tables from."),
                    ToolParameter("timeout", "number",
                                  "Request timeout in seconds.",
                                  required=False),
                ],
            ),
        ],
    )


__all__ = [
    "web_terr",
    # primitive fns
    "_http_get", "_http_get_json", "_http_head", "_http_post",
    "_parse_url", "_build_url",
    # compound skill fns
    "_fetch_text", "_batch_fetch",
    "_extract_links", "_extract_metadata", "_extract_tables",
]

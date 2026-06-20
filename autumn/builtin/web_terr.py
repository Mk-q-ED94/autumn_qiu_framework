"""Web / HTTP capability domain.

Uses ``httpx`` (already a core Autumn dependency) so no new install is needed.
Tools are opt-in because they make network requests. Fetches go through the
shared :mod:`autumn.builtin._http` helper, which streams a 2MB size cap and
refuses private/loopback/metadata targets by default (the model picks the URL);
set ``AUTUMN_ALLOW_PRIVATE_NETWORK=1`` to fetch internal hosts.
"""
from __future__ import annotations

import json
from typing import Any

from ..core.components.skill import Skill
from ..core.components.terr import Terr
from ..core.components.tool import Tool, ToolParameter
from ._http import (
    _DEFAULT_TIMEOUT,
    FetchError,
    looks_like_html,
    safe_fetch,
    safe_head,
    strip_html,
)


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


async def _fetch_text(url: str, timeout: float = _DEFAULT_TIMEOUT, max_chars: int = 20_000) -> str:
    """Skill: GET ``url`` and return readable text (HTML stripped if needed)."""
    _, body, content_type = await safe_fetch(url, timeout=timeout)
    text = strip_html(body) if looks_like_html(content_type, body) else body
    if len(text) > max_chars:
        return text[:max_chars] + f"\n[truncated at {max_chars} chars]"
    return text


def web_terr() -> Terr:
    """Build the ``web`` Terr — HTTP GET / HEAD / JSON fetch + text-extract skill.

    Fetches stream a 2MB cap and refuse private/loopback/metadata hosts by
    default (the model picks the URL). Set ``AUTUMN_ALLOW_PRIVATE_NETWORK=1`` to
    permit internal hosts; a proxy/container is still wise for stronger control.
    """
    return Terr(
        name="web",
        description="HTTP GET, HEAD, JSON fetch, and text extraction from web pages.",
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
        ],
    )


__all__ = ["web_terr"]

"""Web / HTTP capability domain.

Uses ``httpx`` (already a core Autumn dependency) so no new install is needed.
Tools are opt-in because they make network requests. There is no SSRF
protection — the caller is responsible for restricting which hosts the model
can talk to via firewall/proxy rules.
"""
from __future__ import annotations

import re
from typing import Any

import httpx

from ..core.components.skill import Skill
from ..core.components.terr import Terr
from ..core.components.tool import Tool, ToolParameter

_DEFAULT_TIMEOUT = 15.0
_MAX_BYTES = 2_000_000  # 2MB cap per response

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    """Crude HTML → text: drops <script>/<style>, then tags, then collapses whitespace."""
    no_scripts = _SCRIPT_RE.sub("", html)
    no_styles = _STYLE_RE.sub("", no_scripts)
    text = _TAG_RE.sub(" ", no_styles)
    return _WS_RE.sub(" ", text).strip()


async def _http_get(url: str, timeout: float = _DEFAULT_TIMEOUT) -> str:
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        if len(resp.content) > _MAX_BYTES:
            raise ValueError(f"response exceeds {_MAX_BYTES} bytes")
        return resp.text


async def _http_get_json(url: str, timeout: float = _DEFAULT_TIMEOUT) -> Any:
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        if len(resp.content) > _MAX_BYTES:
            raise ValueError(f"response exceeds {_MAX_BYTES} bytes")
        return resp.json()


async def _http_head(url: str, timeout: float = _DEFAULT_TIMEOUT) -> dict[str, Any]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        resp = await client.head(url)
        # Don't raise — HEAD on 4xx is common; surface the status to the model.
        return {
            "status": resp.status_code,
            "url": str(resp.url),
            "headers": {k: v for k, v in resp.headers.items()},
        }


async def _fetch_text(url: str, timeout: float = _DEFAULT_TIMEOUT, max_chars: int = 20_000) -> str:
    """Skill: GET ``url`` and return readable text (HTML stripped if needed)."""
    html_or_text = await _http_get(url, timeout=timeout)
    looks_html = "<" in html_or_text[:512] and ">" in html_or_text[:512]
    text = _strip_html(html_or_text) if looks_html else html_or_text
    if len(text) > max_chars:
        return text[:max_chars] + f"\n[truncated at {max_chars} chars]"
    return text


def web_terr() -> Terr:
    """Build the ``web`` Terr — HTTP GET / HEAD / JSON fetch + text-extract skill.

    Network access is the caller's responsibility — there is no host
    allowlist or SSRF guard. Use a proxy or container if you need that.
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

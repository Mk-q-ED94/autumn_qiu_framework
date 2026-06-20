"""Shared, hardened HTTP fetch + HTML utilities for the network Terrs.

``web_terr`` and ``knowledge_terr`` both fetch model-supplied URLs. Centralising
the fetch path here means the streamed size cap, the SSRF guard, redirect
re-validation and the HTML stripper live in one audited place instead of being
copy-pasted (and drifting) across the two domains. The SSRF host policy and the
``FetchError`` type live in :mod:`autumn.core.security` (the central security
module) and are re-exported here for callers; this module owns only the
httpx-specific fetch and the HTML helpers.
"""
from __future__ import annotations

import re
from html import unescape
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

from ..core.security import (
    DEFAULT_HTTP_TIMEOUT as _DEFAULT_TIMEOUT,
)
from ..core.security import (
    MAX_FETCH_BYTES as _MAX_BYTES,
)
from ..core.security import (
    FetchError,
    assert_url_allowed,
)

_MAX_REDIRECTS = 5
_MAX_TIMEOUT = 60.0  # ceiling on a model-supplied timeout — one fetch can't pin a socket forever


def _clamp_timeout(timeout: float) -> float:
    """Bound a (model-chosen) timeout to a sane range."""
    if not timeout or timeout <= 0:
        return _DEFAULT_TIMEOUT
    return min(timeout, _MAX_TIMEOUT)

# Response headers a HEAD probe must never hand back to the model — a target's
# session cookie / auth material would otherwise leak through a reachability check.
_SENSITIVE_RESPONSE_HEADERS = frozenset({
    "set-cookie",
    "set-cookie2",
    "authorization",
    "proxy-authorization",
    "proxy-authenticate",
})

__all__ = [
    "FetchError",
    "assert_url_allowed",
    "safe_fetch",
    "safe_head",
    "strip_html",
    "clean_inline",
    "looks_like_html",
    "is_text_content",
    "ddg_unwrap",
]


async def safe_fetch(
    url: str,
    *,
    method: str = "GET",
    data: dict | None = None,
    headers: dict | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
    max_bytes: int = _MAX_BYTES,
) -> tuple[int, str, str]:
    """Fetch *url* with SSRF validation, manual redirect re-checking and a
    streamed size cap. Returns ``(status, text, content_type)``.

    Redirects are followed manually (up to :data:`_MAX_REDIRECTS`) so the SSRF
    guard re-runs on every hop — a public URL that 302s to ``localhost`` is
    refused. The body is streamed and aborted the moment it exceeds *max_bytes*,
    so the cap bounds memory instead of being checked only after a full buffer.
    Raises :class:`FetchError`.
    """
    current = url
    req_method = method.upper()
    timeout = _clamp_timeout(timeout)
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout, headers=headers) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            await assert_url_allowed(current)
            try:
                async with client.stream(req_method, current, data=data) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            raise FetchError("redirect without a Location header")
                        current = str(httpx.URL(current).join(location))
                        req_method, data = "GET", None  # never replay a POST body across a redirect
                        continue
                    resp.raise_for_status()
                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise FetchError(f"response exceeds {max_bytes} bytes")
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise FetchError(f"response exceeds {max_bytes} bytes")
                        chunks.append(chunk)
                    body = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
                    return resp.status_code, body, resp.headers.get("content-type", "")
            except httpx.HTTPError as e:
                raise FetchError(str(e)) from e
        raise FetchError(f"too many redirects (>{_MAX_REDIRECTS})")


async def safe_head(
    url: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
) -> tuple[int, str, dict[str, str]]:
    """HEAD *url* with SSRF validation and manual redirect re-checking.

    Like :func:`safe_fetch` but issues a HEAD and returns ``(status, final_url,
    headers)`` with no body. Redirects are followed manually (up to
    :data:`_MAX_REDIRECTS`) so the SSRF guard re-runs on every hop — a public URL
    that 302s to ``localhost`` / a metadata endpoint is refused, which a plain
    ``follow_redirects=True`` client would silently follow. Sensitive response
    headers (``Set-Cookie`` etc.) are stripped so a reachability probe can't
    exfiltrate a target's credentials to the model. Raises :class:`FetchError`.
    """
    current = url
    timeout = _clamp_timeout(timeout)
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            await assert_url_allowed(current)
            try:
                resp = await client.head(current)
            except httpx.HTTPError as e:
                raise FetchError(str(e)) from e
            if resp.is_redirect:
                location = resp.headers.get("location")
                if not location:
                    raise FetchError("redirect without a Location header")
                current = str(httpx.URL(current).join(location))
                continue
            headers = {
                k: v for k, v in resp.headers.items()
                if k.lower() not in _SENSITIVE_RESPONSE_HEADERS
            }
            return resp.status_code, str(resp.url), headers
    raise FetchError(f"too many redirects (>{_MAX_REDIRECTS})")


# ── HTML utilities ────────────────────────────────────────────────────────────

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_SCRIPT_RE = re.compile(r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_STYLE_RE = re.compile(r"<style[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(html: str) -> str:
    """Crude HTML → text: drop comments/<script>/<style>, then tags, then collapse ws."""
    s = _COMMENT_RE.sub("", html)
    s = _SCRIPT_RE.sub("", s)
    s = _STYLE_RE.sub("", s)
    s = _TAG_RE.sub(" ", s)
    return _WS_RE.sub(" ", unescape(s)).strip()


def clean_inline(fragment: str) -> str:
    """Strip tags from a small inline fragment (a title or snippet) and unescape."""
    return _WS_RE.sub(" ", unescape(_TAG_RE.sub("", fragment))).strip()


def looks_like_html(content_type: str, body: str) -> bool:
    """Decide whether *body* should be HTML-stripped.

    Trusts the Content-Type when it is informative (html → yes; json/xml/csv →
    no) and falls back to sniffing the body's first bytes for tag delimiters,
    which keeps working for the common ``text/plain``-mislabelled HTML page.
    """
    ct = (content_type or "").lower()
    if "html" in ct:
        return True
    if any(t in ct for t in ("json", "xml", "csv")):
        return False
    head = body[:512]
    return "<" in head and ">" in head


def is_text_content(content_type: str) -> bool:
    """True when a Content-Type is safe to decode as text (vs. binary)."""
    ct = (content_type or "").lower()
    if not ct:
        return True  # unknown — assume text and let decoding handle it
    return ct.startswith("text/") or any(
        t in ct for t in ("json", "xml", "csv", "html", "javascript", "x-www-form-urlencoded")
    )


def ddg_unwrap(href: str) -> str:
    """Unwrap a DuckDuckGo HTML redirect link to its real destination URL.

    DDG ``result__a`` anchors are ``//duckduckgo.com/l/?uddg=<urlencoded>&...``
    redirectors, not the destination. Returns the decoded target, or *href*
    unchanged when it is already a plain URL.
    """
    if href.startswith("//"):
        href = "https:" + href
    parts = urlsplit(href)
    if "duckduckgo.com" in parts.netloc and parts.path.startswith("/l/"):
        target = parse_qs(parts.query).get("uddg")
        if target:
            return unquote(target[0])
    return href

"""Shared, hardened HTTP fetch + HTML utilities for the network Terrs.

``web_terr`` and ``knowledge_terr`` both fetch model-supplied URLs. Centralising
the fetch path here means the streamed size cap, the SSRF guard, redirect
re-validation and the HTML stripper live in one audited place instead of being
copy-pasted (and drifting) across the two domains.

SSRF posture
------------
By default a fetch is refused when the target resolves to a private, loopback,
link-local, reserved or multicast address — the cloud-metadata endpoint
(``169.254.169.254``) and ``localhost`` services are the classic exfiltration
targets when the model chooses the URL. Literal-IP and obvious-internal-host
checks run without DNS so they work offline; a hostname is additionally resolved
opportunistically (a resolution that fails — e.g. no network — is not treated as
a block, so the check never produces false negatives that depend on the
environment). Set ``AUTUMN_ALLOW_PRIVATE_NETWORK=1`` to disable the guard for
deployments that legitimately fetch internal hosts.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
from html import unescape
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

_DEFAULT_TIMEOUT = 15.0
_MAX_BYTES = 2_000_000  # 2MB cap per response
_MAX_REDIRECTS = 5

# Hostnames that always denote the local machine / an internal network and
# should be refused without needing a DNS round-trip.
_INTERNAL_HOST_SUFFIXES = (".local", ".internal", ".localhost")
_INTERNAL_HOST_EXACT = frozenset({"localhost"})


class FetchError(Exception):
    """Raised when a fetch is refused or fails; the message is model-readable."""


def _allow_private() -> bool:
    return os.environ.get("AUTUMN_ALLOW_PRIVATE_NETWORK", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _ip_is_internal(ip: ipaddress._BaseAddress) -> bool:
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


async def assert_url_allowed(url: str) -> str:
    """Validate scheme + host of *url* for SSRF. Returns the hostname.

    Raises :class:`FetchError` for a non-http(s) scheme, a missing host, an
    obviously-internal hostname, a literal private/loopback/link-local IP, or a
    hostname that resolves (when resolvable) to such an address.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchError(f"unsupported URL scheme {parts.scheme or '(none)'!r}; only http/https allowed")
    host = parts.hostname
    if not host:
        raise FetchError("URL has no host")
    if _allow_private():
        return host

    lowered = host.lower()
    if lowered in _INTERNAL_HOST_EXACT or lowered.endswith(_INTERNAL_HOST_SUFFIXES):
        raise FetchError(f"refusing to fetch internal host {host!r} (set AUTUMN_ALLOW_PRIVATE_NETWORK=1 to allow)")

    # Literal IP — check without DNS so the guard works offline.
    try:
        if _ip_is_internal(ipaddress.ip_address(host)):
            raise FetchError(f"refusing to fetch private/internal address {host} (set AUTUMN_ALLOW_PRIVATE_NETWORK=1 to allow)")
        return host
    except ValueError:
        pass  # not a literal IP — fall through to opportunistic DNS

    # Hostname: resolve opportunistically. A resolution failure is not a block
    # (the actual request will fail on its own); a resolution that lands on an
    # internal address is.
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except (socket.gaierror, OSError):
        return host
    for info in infos:
        addr = info[4][0]
        try:
            if _ip_is_internal(ipaddress.ip_address(addr)):
                raise FetchError(f"refusing to fetch {host!r}: resolves to internal address {addr} (set AUTUMN_ALLOW_PRIVATE_NETWORK=1 to allow)")
        except ValueError:
            continue
    return host


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

"""Central security primitives for Autumn.

Autumn hands a model real capabilities — fetch URLs, read/write a filesystem
sandbox, drive an HTTP server — so the security-relevant logic that used to be
scattered across ``builtin/_http.py``, ``builtin/fs_terr.py`` and ``server/app.py``
lives here in one audited place:

* **SSRF policy** — classify hosts/IPs as internal and refuse model-chosen URLs
  that target private/loopback/link-local/metadata addresses.
* **Secret redaction** — strip API keys / bearer tokens from any string before
  it is logged or returned to a client.
* **Path sandboxing** — decide whether a resolved path stays under a root.
* **Resource limits** — the shared size/length ceilings that bound DoS surface.

The module depends only on the stdlib so it can be imported from anywhere
(core, builtin, server) without cycles.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
from collections.abc import Iterable
from pathlib import Path

__all__ = [
    "FetchError",
    "MAX_FETCH_BYTES",
    "MAX_REQUEST_BYTES",
    "DEFAULT_HTTP_TIMEOUT",
    "private_network_allowed",
    "is_internal_hostname",
    "ip_is_internal",
    "classify_literal_ip",
    "host_resolves_to_internal",
    "assert_url_allowed",
    "redact_secrets",
    "is_within_root",
]

# ── resource limits (shared DoS ceilings) ─────────────────────────────────────

MAX_FETCH_BYTES = 2_000_000       # per outbound fetch response (web/knowledge)
MAX_REQUEST_BYTES = 4_000_000     # per inbound HTTP request body (server)
DEFAULT_HTTP_TIMEOUT = 15.0       # seconds, outbound fetches


class FetchError(Exception):
    """Raised when an outbound fetch is refused or fails; message is model-readable."""


# ── SSRF host policy ──────────────────────────────────────────────────────────

# Hostnames that always denote the local machine / an internal network and are
# refused without needing a DNS round-trip.
_INTERNAL_HOST_SUFFIXES = (".local", ".internal", ".localhost")
_INTERNAL_HOST_EXACT = frozenset({"localhost"})


def private_network_allowed() -> bool:
    """True when the SSRF guard is explicitly disabled via the environment."""
    return os.environ.get("AUTUMN_ALLOW_PRIVATE_NETWORK", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def is_internal_hostname(host: str) -> bool:
    """True for hostnames that always denote the local machine / internal network."""
    h = host.lower().rstrip(".")
    return h in _INTERNAL_HOST_EXACT or h.endswith(_INTERNAL_HOST_SUFFIXES)


def ip_is_internal(ip: ipaddress._BaseAddress) -> bool:
    """True when an IP must never be reached from a model-chosen URL."""
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def classify_literal_ip(host: str) -> bool | None:
    """Classify *host* when it is a literal IP: True=internal, False=public, None=not an IP."""
    try:
        return ip_is_internal(ipaddress.ip_address(host))
    except ValueError:
        return None


async def host_resolves_to_internal(host: str) -> bool:
    """True when *host* resolves (DNS) to an internal address.

    A resolution failure returns False — the actual request will fail on its
    own, so an offline environment never produces a spurious block.
    """
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None)
    except (socket.gaierror, OSError):
        return False
    for info in infos:
        try:
            if ip_is_internal(ipaddress.ip_address(info[4][0])):
                return True
        except ValueError:
            continue
    return False


async def assert_url_allowed(url: str) -> str:
    """Validate scheme + host of *url* for SSRF. Returns the hostname.

    Raises :class:`FetchError` for a non-http(s) scheme, a missing host, an
    obviously-internal hostname, a literal private/loopback/link-local IP, or a
    hostname that resolves (when resolvable) to such an address. The guard is a
    no-op when ``AUTUMN_ALLOW_PRIVATE_NETWORK`` is set.
    """
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchError(f"unsupported URL scheme {parts.scheme or '(none)'!r}; only http/https allowed")
    host = parts.hostname
    if not host:
        raise FetchError("URL has no host")
    if private_network_allowed():
        return host

    if is_internal_hostname(host):
        raise FetchError(f"refusing to fetch internal host {host!r} (set AUTUMN_ALLOW_PRIVATE_NETWORK=1 to allow)")

    literal = classify_literal_ip(host)
    if literal is True:
        raise FetchError(f"refusing to fetch private/internal address {host} (set AUTUMN_ALLOW_PRIVATE_NETWORK=1 to allow)")
    if literal is False:
        return host  # public literal IP — no DNS needed

    if await host_resolves_to_internal(host):
        raise FetchError(f"refusing to fetch {host!r}: resolves to an internal address (set AUTUMN_ALLOW_PRIVATE_NETWORK=1 to allow)")
    return host


# ── secret redaction ──────────────────────────────────────────────────────────

# High-confidence secret shapes — redacted wherever they appear in a string.
_PREFIX_SECRET_RES = (
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),        # OpenAI-style API keys
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
    re.compile(r"gh[opsu]_[A-Za-z0-9]{20,}"),     # GitHub tokens
    re.compile(r"AKIA[0-9A-Z]{16}"),              # AWS access key id
)
_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}")
_KV_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|apikey|token|secret|password|passwd|authorization)\b(\s*[=:]\s*)"
    r"[\"']?[^\s\"'&,}]{4,}",
)


def redact_secrets(text: str, known: Iterable[str] = ()) -> str:
    """Mask API keys / bearer tokens / known secrets in *text* before it is
    logged or returned. ``known`` is an optional list of literal secret strings
    (e.g. the configured model API keys) to scrub verbatim.
    """
    if not text:
        return text
    out = text
    for secret in known:
        s = (secret or "").strip()
        if len(s) >= 6:
            out = out.replace(s, "***")
    out = _BEARER_RE.sub(r"\1***", out)
    out = _KV_SECRET_RE.sub(r"\1\2***", out)
    for pat in _PREFIX_SECRET_RES:
        out = pat.sub("***", out)
    return out


# ── path sandboxing ───────────────────────────────────────────────────────────

def is_within_root(path: Path, root_resolved: Path) -> bool:
    """True when *path*'s real (symlink-resolved) path stays under *root_resolved*."""
    try:
        path.resolve().relative_to(root_resolved)
        return True
    except (ValueError, OSError):
        return False

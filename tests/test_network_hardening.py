"""Tests for the hardened shared HTTP helper and the two network Terrs.

Covers the second-pass security/correctness fixes: the SSRF guard, the streamed
size cap, the DuckDuckGo redirect-unwrap + snippet alignment, and the content-
type-aware HTML handling — none of which had coverage before.
"""
import httpx
import pytest

from autumn.builtin import knowledge_terr, web_terr
from autumn.builtin._http import (
    FetchError,
    assert_url_allowed,
    ddg_unwrap,
    is_text_content,
    looks_like_html,
    safe_fetch,
    strip_html,
)
from autumn.builtin.knowledge_terr import _parse_ddg_results


def _patch_httpx(monkeypatch, transport):
    """Force httpx.AsyncClient to always use ``transport`` (swallows kwargs)."""
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: original(transport=transport))


def _tool(terr, name):
    return next(t for t in terr.tools if t.name == name)


def _skill(terr, name):
    return next(s for s in terr.skills if s.name == name)


# ── SSRF guard ────────────────────────────────────────────────────────────────


async def test_ssrf_blocks_cloud_metadata_ip():
    with pytest.raises(FetchError):
        await assert_url_allowed("http://169.254.169.254/latest/meta-data/")


async def test_ssrf_blocks_loopback_ip():
    with pytest.raises(FetchError):
        await assert_url_allowed("http://127.0.0.1:6379/")


async def test_ssrf_blocks_localhost_name():
    with pytest.raises(FetchError):
        await assert_url_allowed("http://localhost:8080/admin")


async def test_ssrf_blocks_internal_suffix():
    with pytest.raises(FetchError):
        await assert_url_allowed("http://db.internal/")


async def test_ssrf_rejects_non_http_scheme():
    with pytest.raises(FetchError):
        await assert_url_allowed("file:///etc/passwd")


async def test_ssrf_allows_public_literal_ip():
    # A public literal IP needs no DNS and must pass.
    assert await assert_url_allowed("http://8.8.8.8/") == "8.8.8.8"


async def test_ssrf_guard_can_be_disabled_via_env(monkeypatch):
    monkeypatch.setenv("AUTUMN_ALLOW_PRIVATE_NETWORK", "1")
    assert await assert_url_allowed("http://127.0.0.1:6379/") == "127.0.0.1"


async def test_web_http_get_blocked_for_internal_host():
    with pytest.raises(FetchError):
        await _tool(web_terr(), "http_get").call(url="http://169.254.169.254/")


# ── streamed size cap ─────────────────────────────────────────────────────────


async def test_safe_fetch_aborts_oversized_response(monkeypatch):
    big = b"x" * 3_000_000  # 3MB > 2MB cap
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=big))
    _patch_httpx(monkeypatch, transport)
    with pytest.raises(FetchError):
        await safe_fetch("http://8.8.8.8/big")


async def test_safe_fetch_returns_body_and_content_type(monkeypatch):
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, text="hello", headers={"content-type": "text/plain"}),
    )
    _patch_httpx(monkeypatch, transport)
    status, body, ctype = await safe_fetch("http://8.8.8.8/ok")
    assert status == 200
    assert body == "hello"
    assert "text/plain" in ctype


# ── DuckDuckGo parsing ────────────────────────────────────────────────────────


def test_ddg_unwrap_decodes_redirect():
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&rut=abc"
    assert ddg_unwrap(href) == "https://example.com/page"


def test_ddg_unwrap_passes_plain_url_through():
    assert ddg_unwrap("https://example.org/x") == "https://example.org/x"


def test_parse_ddg_aligns_snippet_to_its_anchor():
    # Second result deliberately has NO snippet — a positional zip would shift
    # result B's (missing) snippet onto a later one; the windowed parse must not.
    html = (
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.com">Title A</a>'
        '<a class="result__snippet">Snippet A</a>'
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fb.com">Title B</a>'
    )
    results = _parse_ddg_results(html, 5)
    assert results == [
        ("Title A", "https://a.com", "Snippet A"),
        ("Title B", "https://b.com", ""),
    ]


async def test_web_search_unwraps_and_lists(monkeypatch):
    html = (
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.com">A</a>'
        '<a class="result__snippet">about a</a>'
    )
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text=html))
    _patch_httpx(monkeypatch, transport)
    out = await _skill(knowledge_terr(), "web_search").execute(query="a", max_results="3")
    assert "https://a.com" in out
    assert "duckduckgo.com/l/" not in out  # the redirector must not leak through


# ── content-type aware handling ───────────────────────────────────────────────


def test_looks_like_html_trusts_content_type():
    assert looks_like_html("text/html", "no tags here") is True
    assert looks_like_html("application/json", '{"a": "<b>"}') is False


def test_looks_like_html_sniffs_when_generic():
    assert looks_like_html("text/plain", "<html><body>x</body></html>") is True
    assert looks_like_html("text/plain", "plain words") is False


def test_is_text_content():
    assert is_text_content("text/html") is True
    assert is_text_content("application/json") is True
    assert is_text_content("image/png") is False
    assert is_text_content("") is True  # unknown → assume text


def test_strip_html_drops_comments_and_scripts():
    html = "<!-- secret --><script>evil()</script><p>Visible &amp; clean</p>"
    out = strip_html(html)
    assert "secret" not in out
    assert "evil" not in out
    assert "Visible & clean" in out


async def test_fetch_document_rejects_binary_content(monkeypatch):
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, content=b"\x89PNG\r\n", headers={"content-type": "image/png"}),
    )
    _patch_httpx(monkeypatch, transport)
    out = await _skill(knowledge_terr(), "fetch_document").execute(url="http://8.8.8.8/img.png")
    assert "non-text" in out.lower()

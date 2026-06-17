"""Tests for the central security module and the new protections wired through
it: secret redaction, the SSRF host policy, path sandboxing, the math DoS
guards, and the server's body-size limit / security headers / error redaction.
"""
import os

import pytest
from fastapi.testclient import TestClient

from autumn.builtin import math_terr
from autumn.core.security import (
    FetchError,
    assert_url_allowed,
    classify_literal_ip,
    is_internal_hostname,
    is_within_root,
    redact_secrets,
)

os.environ.setdefault("AUTUMN_SKIP_INIT", "1")

from autumn.server.app import (  # noqa: E402
    _cors_origins,
    _known_secrets,
    _max_body_bytes,
    _safe_error,
    create_app,
)


# ── secret redaction ──────────────────────────────────────────────────────────


def test_redact_openai_style_key():
    out = redact_secrets("call failed: key sk-abcdEFGH1234 ijkl is bad")
    assert "sk-abcdEFGH1234" not in out
    assert "***" in out


def test_redact_bearer_token():
    out = redact_secrets("Authorization: Bearer abcDEF123456 denied")
    assert "abcDEF123456" not in out


def test_redact_key_value_forms():
    out = redact_secrets('connect with api_key=topsecretvalue and token: anothersecret')
    assert "topsecretvalue" not in out
    assert "anothersecret" not in out


def test_redact_known_literals():
    out = redact_secrets("the configured key hunter2hunter2 leaked", known=["hunter2hunter2"])
    assert "hunter2hunter2" not in out


def test_redact_empty_and_short_known_are_noops():
    assert redact_secrets("") == ""
    # too-short "known" values must not blanket-redact ordinary text
    assert redact_secrets("hello world", known=["ab"]) == "hello world"


# ── SSRF host policy ──────────────────────────────────────────────────────────


def test_internal_hostname_classification():
    assert is_internal_hostname("localhost") is True
    assert is_internal_hostname("db.internal") is True
    assert is_internal_hostname("host.local") is True
    assert is_internal_hostname("example.com") is False


def test_classify_literal_ip():
    assert classify_literal_ip("169.254.169.254") is True  # link-local metadata
    assert classify_literal_ip("10.0.0.1") is True          # private
    assert classify_literal_ip("8.8.8.8") is False          # public
    assert classify_literal_ip("not-an-ip") is None


async def test_assert_url_allowed_blocks_and_allows():
    with pytest.raises(FetchError):
        await assert_url_allowed("http://169.254.169.254/")
    with pytest.raises(FetchError):
        await assert_url_allowed("gopher://evil/")
    assert await assert_url_allowed("https://8.8.8.8/") == "8.8.8.8"


# ── path sandboxing ───────────────────────────────────────────────────────────


def test_is_within_root(tmp_path):
    root = (tmp_path / "root").resolve()
    root.mkdir()
    (root / "a.txt").write_text("x")
    assert is_within_root(root / "a.txt", root) is True
    assert is_within_root(tmp_path / "outside.txt", root) is False


# ── math DoS guards ───────────────────────────────────────────────────────────


def _calc_tool():
    return next(t for t in math_terr().tools if t.name == "calc")


async def test_calc_rejects_huge_exponent():
    with pytest.raises(ValueError, match="exponent"):
        await _calc_tool().call(expression="2 ** 99999999")


async def test_calc_rejects_huge_factorial():
    with pytest.raises(ValueError, match="factorial"):
        await _calc_tool().call(expression="factorial(99999999)")


async def test_calc_rejects_chained_power_blowup():
    with pytest.raises(ValueError, match="too large"):
        await _calc_tool().call(expression="(10 ** 5000) ** 100")


async def test_calc_normal_math_still_works():
    assert await _calc_tool().call(expression="2 ** 16") == "65536"
    assert await _calc_tool().call(expression="factorial(10)") == "3628800"


# ── server: helpers ───────────────────────────────────────────────────────────


def test_cors_origins_env(monkeypatch):
    monkeypatch.delenv("AUTUMN_CORS_ORIGINS", raising=False)
    assert _cors_origins() == ["*"]
    monkeypatch.setenv("AUTUMN_CORS_ORIGINS", "https://a.com, https://b.com")
    assert _cors_origins() == ["https://a.com", "https://b.com"]


def test_max_body_bytes_env(monkeypatch):
    monkeypatch.setenv("AUTUMN_MAX_BODY_BYTES", "1234")
    assert _max_body_bytes() == 1234
    monkeypatch.delenv("AUTUMN_MAX_BODY_BYTES", raising=False)
    assert _max_body_bytes() > 0  # falls back to the module default


class _StubReq:
    """Minimal Request stand-in for _known_secrets / _safe_error."""

    class _App:
        class state:  # noqa: N801
            autumn = None

    app = _App()


def test_safe_error_redacts_env_key(monkeypatch):
    monkeypatch.setenv("AUTUMN_API_KEY", "supersecretvalue")
    msg = _safe_error(_StubReq(), Exception("upstream rejected supersecretvalue at api"))
    assert "supersecretvalue" not in msg
    assert "supersecretvalue" in _known_secrets(_StubReq())


# ── server: middleware end-to-end ─────────────────────────────────────────────


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"


def test_oversized_body_rejected(client, monkeypatch):
    monkeypatch.setenv("AUTUMN_MAX_BODY_BYTES", "50")
    r = client.post("/process", json={"input": "x" * 500})
    assert r.status_code == 413
    assert "exceeds" in r.json()["detail"]


def test_normal_body_passes_size_gate(client, monkeypatch):
    # A small body clears the gate (it then 503s because no model is configured
    # in tests — the point is the size guard let it through).
    monkeypatch.setenv("AUTUMN_MAX_BODY_BYTES", "100000")
    r = client.post("/process", json={"input": "hi"})
    assert r.status_code != 413

"""Tests for the built-in capability domains shipped under ``autumn.builtin``.

These tests cover every Terr factory:
- always-safe: time, math, text, data
- opt-in: web (HTTP via httpx), fs (sandboxed), memory (wraps existing skills)
- helpers: register_safe_builtins, register_builtins
- mcp catalog: factory signatures and KNOWN_MCPS shape
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from autumn.builtin import (
    KNOWN_MCPS,
    data_terr,
    fs_terr,
    math_terr,
    memory_terr,
    register_safe_builtins,
    text_terr,
    time_terr,
    web_terr,
)
from autumn.builtin import mcp_catalog
from autumn.core.components.terr import Terr
from autumn.core.components.tool import Tool
from autumn.core.components.skill import Skill


# Helper for resolving tools/skills by name in a Terr.
def _tool(terr: Terr, name: str) -> Tool:
    for t in terr.tools:
        if t.name == name:
            return t
    raise KeyError(name)


def _skill(terr: Terr, name: str) -> Skill:
    for s in terr.skills:
        if s.name == name:
            return s
    raise KeyError(name)


async def _run_skill(terr: Terr, name: str, **kwargs):
    return await _skill(terr, name).execute(**kwargs)


# ── time_terr ─────────────────────────────────────────────────────────────────


async def test_time_now_iso_default():
    terr = time_terr()
    out = await _tool(terr, "now").call()
    # ISO 8601 UTC starts with date then 'T' then time.
    assert "T" in out
    assert out.endswith("+00:00") or out.endswith("Z")


async def test_time_now_unix():
    out = await _tool(time_terr(), "now").call(fmt="unix")
    assert out.isdigit()
    assert len(out) >= 10


async def test_time_now_date():
    out = await _tool(time_terr(), "now").call(fmt="date")
    assert len(out) == 10 and out[4] == "-" and out[7] == "-"


async def test_time_parse_time_iso_normalises():
    out = await _tool(time_terr(), "parse_time").call(value="2026-01-15T10:00:00+00:00")
    assert out.startswith("2026-01-15T10:00:00")


async def test_time_parse_time_unix():
    out = await _tool(time_terr(), "parse_time").call(value="0", fmt="unix")
    assert out.startswith("1970-01-01T00:00:00")


async def test_time_diff_seconds():
    out = await _tool(time_terr(), "time_diff").call(
        start="2026-01-01T00:00:00+00:00",
        end="2026-01-01T00:01:30+00:00",
    )
    assert out == "90.000"


async def test_time_diff_minutes():
    out = await _tool(time_terr(), "time_diff").call(
        start="2026-01-01T00:00:00+00:00",
        end="2026-01-01T01:00:00+00:00",
        unit="minutes",
    )
    assert out.startswith("60")


async def test_time_add_days():
    out = await _tool(time_terr(), "time_add").call(
        value="2026-01-01T00:00:00+00:00", amount=5, unit="days",
    )
    assert out.startswith("2026-01-06T00:00:00")


async def test_time_today_skill():
    out = await _run_skill(time_terr(), "time_today")
    # YYYY-MM-DD (WeekdayAbbrev)
    assert len(out) >= 16
    assert "(" in out and ")" in out


# ── math_terr ─────────────────────────────────────────────────────────────────


async def test_math_calc_arithmetic():
    calc = _tool(math_terr(), "calc")
    assert await calc.call(expression="2 + 2") == "4"
    assert await calc.call(expression="10 / 4") == "2.5"
    assert await calc.call(expression="2 ** 10") == "1024"
    assert await calc.call(expression="7 % 3") == "1"


async def test_math_calc_constants_and_functions():
    calc = _tool(math_terr(), "calc")
    assert await calc.call(expression="pi") == "3.141592654"
    assert (await calc.call(expression="sqrt(16)")) == "4"
    assert (await calc.call(expression="abs(-7)")) == "7"
    assert (await calc.call(expression="round(3.7)")) == "4"


async def test_math_calc_rejects_arbitrary_calls():
    calc = _tool(math_terr(), "calc")
    with pytest.raises(ValueError):
        await calc.call(expression="__import__('os')")
    with pytest.raises(ValueError):
        await calc.call(expression="open('/etc/passwd')")


async def test_math_calc_rejects_attribute_access():
    calc = _tool(math_terr(), "calc")
    with pytest.raises(ValueError):
        await calc.call(expression="(1).bit_length()")


async def test_math_calc_rejects_unknown_name():
    calc = _tool(math_terr(), "calc")
    with pytest.raises(ValueError):
        await calc.call(expression="x + 1")


async def test_math_calc_input_size_limit():
    calc = _tool(math_terr(), "calc")
    with pytest.raises(ValueError, match="too long"):
        await calc.call(expression="1" + ("+1" * 1024))


async def test_math_stats_metrics():
    stats = _tool(math_terr(), "stats")
    assert await stats.call(values=[1, 2, 3, 4, 5], metric="mean") == "3"
    assert await stats.call(values=[1, 2, 3, 4, 5], metric="median") == "3"
    assert await stats.call(values=[1, 2, 3, 4, 5], metric="sum") == "15"
    assert await stats.call(values=[1, 2, 3, 4, 5], metric="count") == "5"


async def test_math_stats_rejects_empty():
    stats = _tool(math_terr(), "stats")
    with pytest.raises(ValueError):
        await stats.call(values=[], metric="mean")


# ── text_terr ─────────────────────────────────────────────────────────────────


async def test_text_count_words_and_chars():
    terr = text_terr()
    assert await _tool(terr, "count_text").call(text="hello world") == "2"
    assert await _tool(terr, "count_text").call(text="hello", unit="chars") == "5"


async def test_text_count_lines():
    out = await _tool(text_terr(), "count_text").call(text="a\nb\nc", unit="lines")
    assert out == "3"


async def test_text_regex_find_basic():
    out = await _tool(text_terr(), "regex_find").call(
        text="cat bat rat",
        pattern=r"[cbr]at",
    )
    assert out == ["cat", "bat", "rat"]


async def test_text_regex_find_with_groups():
    out = await _tool(text_terr(), "regex_find").call(
        text="key1=val1 key2=val2",
        pattern=r"(\w+)=(\w+)",
    )
    assert out == ["key1 | val1", "key2 | val2"]


async def test_text_regex_find_flags():
    out = await _tool(text_terr(), "regex_find").call(
        text="Hello hello HELLO",
        pattern=r"hello",
        flags="i",
    )
    assert len(out) == 3


async def test_text_extract_urls_dedup():
    out = await _tool(text_terr(), "extract_urls").call(
        text="See https://a.com and https://b.com and again https://a.com",
    )
    assert out == ["https://a.com", "https://b.com"]


async def test_text_split_and_replace():
    terr = text_terr()
    assert await _tool(terr, "split_text").call(text="a,b,c", separator=",") == ["a", "b", "c"]
    assert await _tool(terr, "replace_text").call(
        text="foo bar foo", find="foo", replace_with="baz",
    ) == "baz bar baz"


# ── data_terr ─────────────────────────────────────────────────────────────────


async def test_data_parse_json_roundtrip():
    terr = data_terr()
    parsed = await _tool(terr, "parse_json").call(text='{"a": 1, "b": [2, 3]}')
    assert parsed == {"a": 1, "b": [2, 3]}
    s = await _tool(terr, "to_json").call(value=parsed)
    assert json.loads(s) == parsed


async def test_data_to_json_pretty():
    out = await _tool(data_terr(), "to_json").call(value={"a": 1}, indent=2)
    assert "\n" in out and "  " in out


async def test_data_parse_csv_with_header():
    rows = await _tool(data_terr(), "parse_csv").call(
        text="name,age\nalice,30\nbob,25\n",
    )
    assert rows == [{"name": "alice", "age": "30"}, {"name": "bob", "age": "25"}]


async def test_data_parse_csv_no_header():
    rows = await _tool(data_terr(), "parse_csv").call(
        text="a,b\n1,2\n", has_header=False,
    )
    assert rows == [["a", "b"], ["1", "2"]]


async def test_data_to_csv_from_dicts():
    out = await _tool(data_terr(), "to_csv").call(
        rows=[{"name": "alice", "age": 30}, {"name": "bob", "age": 25}],
    )
    lines = out.strip().split("\r\n")
    assert lines[0] == "name,age"
    assert "alice,30" in lines and "bob,25" in lines


async def test_data_json_path_dict_and_list():
    data = {"users": [{"name": "alice"}, {"name": "bob"}]}
    out1 = await _tool(data_terr(), "json_path").call(data=data, path="users.0.name")
    out2 = await _tool(data_terr(), "json_path").call(data=data, path="users.1.name")
    assert out1 == "alice"
    assert out2 == "bob"


# ── web_terr ──────────────────────────────────────────────────────────────────


def _patch_httpx(monkeypatch, transport):
    """Replace httpx.AsyncClient with one that always uses ``transport``.

    Captures the original class before patching so the substitute can still
    instantiate it. The signature swallows all kwargs (follow_redirects, timeout)
    that web_terr passes — they're irrelevant under the mock transport.
    """
    import httpx
    original = httpx.AsyncClient

    def fake(*_args, **_kwargs):
        return original(transport=transport)

    monkeypatch.setattr(httpx, "AsyncClient", fake)


async def test_web_http_get_via_mock(monkeypatch):
    import httpx

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="<html><body>hi</body></html>")
    )
    _patch_httpx(monkeypatch, transport)
    out = await _tool(web_terr(), "http_get").call(url="https://example.com")
    assert "<body>hi</body>" in out


async def test_web_http_get_json_via_mock(monkeypatch):
    import httpx

    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"ok": True, "n": 7})
    )
    _patch_httpx(monkeypatch, transport)
    out = await _tool(web_terr(), "http_get_json").call(url="https://example.com")
    assert out == {"ok": True, "n": 7}


async def test_web_fetch_text_strips_html(monkeypatch):
    import httpx

    html = "<html><head><style>x{}</style><script>alert(1)</script></head><body>Hello world</body></html>"
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text=html))
    _patch_httpx(monkeypatch, transport)
    out = await _run_skill(web_terr(), "fetch_text", url="https://example.com")
    assert "Hello world" in out
    assert "<script>" not in out
    assert "alert" not in out
    assert "x{}" not in out


# ── fs_terr (sandboxed) ───────────────────────────────────────────────────────


async def test_fs_write_and_read():
    with tempfile.TemporaryDirectory() as d:
        terr = fs_terr(d)
        await _tool(terr, "write_file").call(path="hello.txt", content="hi")
        out = await _tool(terr, "read_file").call(path="hello.txt")
        assert out == "hi"


async def test_fs_list_dir():
    with tempfile.TemporaryDirectory() as d:
        Path(d, "a.txt").write_text("a")
        Path(d, "sub").mkdir()
        Path(d, "sub", "b.txt").write_text("b")
        terr = fs_terr(d)
        entries = await _tool(terr, "list_dir").call(path=".")
        names = [e["name"] for e in entries]
        assert "a.txt" in names and "sub" in names


async def test_fs_list_dir_recursive():
    with tempfile.TemporaryDirectory() as d:
        Path(d, "sub").mkdir()
        Path(d, "sub", "b.txt").write_text("b")
        entries = await _tool(fs_terr(d), "list_dir").call(path=".", recursive=True)
        names = [e["name"] for e in entries]
        assert "b.txt" in names


async def test_fs_file_info():
    with tempfile.TemporaryDirectory() as d:
        Path(d, "x.txt").write_text("abcdef")
        info = await _tool(fs_terr(d), "file_info").call(path="x.txt")
        assert info["size"] == 6
        assert info["is_file"] is True


async def test_fs_delete_file():
    with tempfile.TemporaryDirectory() as d:
        target = Path(d, "doomed.txt")
        target.write_text("x")
        await _tool(fs_terr(d), "delete_file").call(path="doomed.txt")
        assert not target.exists()


async def test_fs_rejects_traversal():
    with tempfile.TemporaryDirectory() as d:
        terr = fs_terr(d)
        with pytest.raises(ValueError, match="escapes"):
            await _tool(terr, "read_file").call(path="../escape")


async def test_fs_rejects_absolute_paths():
    with tempfile.TemporaryDirectory() as d:
        terr = fs_terr(d)
        with pytest.raises(ValueError, match="absolute"):
            await _tool(terr, "read_file").call(path="/etc/passwd")


def test_fs_terr_requires_existing_root():
    with pytest.raises(ValueError, match="does not exist"):
        fs_terr("/nonexistent/path/that/should/not/exist/anywhere")


def test_fs_terr_rejects_file_as_root(tmp_path):
    f = tmp_path / "afile"
    f.write_text("not a dir")
    with pytest.raises(ValueError, match="not a directory"):
        fs_terr(str(f))


# ── memory_terr (wraps existing memory skills) ────────────────────────────────


async def test_memory_terr_recall_and_remember():
    from autumn.core.memory.backends import DictBackend
    from autumn.core.memory.shared import SharedZone

    shared = SharedZone(DictBackend())
    terr = memory_terr(shared, area_name="shared")
    assert terr.name == "memory"
    assert {s.name for s in terr.skills} == {"recall", "remember", "list_recent", "pin_memory"}

    await _run_skill(terr, "remember", key="favorite_season", value="autumn")
    out = await _run_skill(terr, "recall", query="favorite_season")
    assert out == "autumn"


# ── helpers ───────────────────────────────────────────────────────────────────


def test_register_safe_builtins_returns_expected_names():
    from autumn.plugins.loader import PluginLoader

    class _Stub:
        plugins = PluginLoader()

        def register_tool(self, tool):
            self.plugins.register(tool.name, tool)

        def register_skill(self, skill):
            self.plugins.register(skill.name, skill)

        # Reuse the real Autumn.register_terr — it only depends on the methods above.
        from autumn.core.framework import Autumn
        register_terr = Autumn.register_terr

    names = register_safe_builtins(_Stub())
    assert names == ["time", "math", "text", "data"]


# ── mcp catalog ───────────────────────────────────────────────────────────────


def test_mcp_filesystem_builds_stdio_client():
    client = mcp_catalog.mcp_filesystem("/tmp/data")
    assert "@modelcontextprotocol/server-filesystem" in client.command
    assert "/tmp/data" in client.command


def test_mcp_fetch_builds_stdio_client():
    client = mcp_catalog.mcp_fetch()
    assert "mcp-server-fetch" in client.command


def test_mcp_git_includes_repository_arg():
    client = mcp_catalog.mcp_git("/srv/myrepo")
    assert "--repository" in client.command
    assert "/srv/myrepo" in client.command


def test_mcp_brave_search_uses_env_for_key():
    client = mcp_catalog.mcp_brave_search("test-key")
    assert client.env == {"BRAVE_API_KEY": "test-key"}


def test_mcp_github_uses_env_for_token():
    client = mcp_catalog.mcp_github("ghp_abc")
    assert client.env == {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_abc"}


def test_known_mcps_catalog_shape():
    assert len(KNOWN_MCPS) >= 6
    for entry in KNOWN_MCPS:
        assert {"id", "name", "description", "factory", "required_args"} <= entry.keys()
        assert hasattr(mcp_catalog, entry["factory"])


# ── exposed source_terr metadata ──────────────────────────────────────────────


def test_tools_carry_source_terr_metadata():
    terr = math_terr()
    for tool in terr.tools:
        assert tool.source_terr == "math"
        assert tool.source_terr_description == terr.description


def test_skills_carry_source_terr_metadata():
    terr = web_terr()
    for skill in terr.skills:
        assert skill.source_terr == "web"

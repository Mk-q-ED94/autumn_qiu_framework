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
    collection_terr,
    data_terr,
    encoding_terr,
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


async def test_data_to_json_caps_emitted_size():
    # A value within the input cap can still serialize past it — the emitter must
    # bound its own output, not just parsed input (cost / OOM guard).
    with pytest.raises(ValueError, match="output"):
        await _tool(data_terr(), "to_json").call(value="x" * 1_100_000)


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


# ── encoding_terr ─────────────────────────────────────────────────────────────


async def test_encoding_base64_roundtrip():
    terr = encoding_terr()
    encoded = await _tool(terr, "base64_encode").call(text="hello 秋")
    decoded = await _tool(terr, "base64_decode").call(data=encoded)
    assert decoded == "hello 秋"


async def test_encoding_base64_urlsafe():
    terr = encoding_terr()
    encoded = await _tool(terr, "base64_encode").call(text="<<???>>", urlsafe=True)
    assert "+" not in encoded and "/" not in encoded
    decoded = await _tool(terr, "base64_decode").call(data=encoded, urlsafe=True)
    assert decoded == "<<???>>"


async def test_encoding_base64_decode_rejects_garbage():
    with pytest.raises(ValueError, match="invalid base64"):
        await _tool(encoding_terr(), "base64_decode").call(data="not base64!!!")


async def test_encoding_hash_known_vectors():
    h = _tool(encoding_terr(), "hash_text")
    # Well-known digests of the empty string.
    assert await h.call(text="", algorithm="md5") == "d41d8cd98f00b204e9800998ecf8427e"
    assert await h.call(text="", algorithm="sha256") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


async def test_encoding_hash_rejects_unknown_algo():
    with pytest.raises(ValueError, match="unsupported algorithm"):
        await _tool(encoding_terr(), "hash_text").call(text="x", algorithm="sha3")


async def test_encoding_hex_roundtrip():
    terr = encoding_terr()
    encoded = await _tool(terr, "hex_encode").call(text="ab")
    assert encoded == "6162"
    assert await _tool(terr, "hex_decode").call(data=encoded) == "ab"


async def test_encoding_url_roundtrip():
    terr = encoding_terr()
    encoded = await _tool(terr, "url_encode").call(text="a b&c=d")
    assert encoded == "a%20b%26c%3Dd"
    assert await _tool(terr, "url_decode").call(text=encoded) == "a b&c=d"


async def test_encoding_uuid_generate_count_and_shape():
    out = await _tool(encoding_terr(), "uuid_generate").call(count=3)
    assert len(out) == 3
    assert len(set(out)) == 3
    assert all(len(u) == 36 and u.count("-") == 4 for u in out)


async def test_encoding_uuid_rejects_bad_count():
    with pytest.raises(ValueError):
        await _tool(encoding_terr(), "uuid_generate").call(count=0)


# ── collection_terr ───────────────────────────────────────────────────────────


async def test_collection_unique_preserves_order():
    out = await _tool(collection_terr(), "unique").call(items=[3, 1, 3, 2, 1])
    assert out == [3, 1, 2]


async def test_collection_unique_handles_nested():
    out = await _tool(collection_terr(), "unique").call(
        items=[{"a": 1}, {"a": 1}, {"a": 2}],
    )
    assert out == [{"a": 1}, {"a": 2}]


async def test_collection_flatten_one_level_default():
    out = await _tool(collection_terr(), "flatten").call(items=[1, [2, 3], [4, [5]]])
    assert out == [1, 2, 3, 4, [5]]


async def test_collection_flatten_full_depth():
    out = await _tool(collection_terr(), "flatten").call(items=[1, [2, [3, [4]]]], depth=-1)
    assert out == [1, 2, 3, 4]


async def test_collection_chunk():
    out = await _tool(collection_terr(), "chunk").call(items=[1, 2, 3, 4, 5], size=2)
    assert out == [[1, 2], [3, 4], [5]]


async def test_collection_chunk_rejects_bad_size():
    with pytest.raises(ValueError):
        await _tool(collection_terr(), "chunk").call(items=[1], size=0)


async def test_collection_frequencies():
    out = await _tool(collection_terr(), "frequencies").call(items=["a", "b", "a", "a"])
    assert out == {"a": 3, "b": 1}


async def test_collection_group_by():
    rows = [
        {"team": "red", "n": 1},
        {"team": "blue", "n": 2},
        {"team": "red", "n": 3},
    ]
    out = await _tool(collection_terr(), "group_by").call(rows=rows, key="team")
    assert out == {
        "red": [{"team": "red", "n": 1}, {"team": "red", "n": 3}],
        "blue": [{"team": "blue", "n": 2}],
    }


async def test_collection_sort_records():
    rows = [{"n": 3}, {"n": 1}, {"n": 2}]
    out = await _tool(collection_terr(), "sort_records").call(rows=rows, by="n")
    assert [r["n"] for r in out] == [1, 2, 3]
    out_desc = await _tool(collection_terr(), "sort_records").call(rows=rows, by="n", reverse=True)
    assert [r["n"] for r in out_desc] == [3, 2, 1]


async def test_collection_sort_records_missing_key_last():
    rows = [{"n": 2}, {"x": 9}, {"n": 1}]
    out = await _tool(collection_terr(), "sort_records").call(rows=rows, by="n")
    assert out[-1] == {"x": 9}


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
    assert {s.name for s in terr.skills} == {
        "recall", "remember", "list_recent", "pin_memory", "annotate_memory",
    }

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
    assert names == ["time", "math", "text", "data", "encoding", "collection"]


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


def test_mcp_postgres_passes_connection_string():
    client = mcp_catalog.mcp_postgres("postgresql://u:p@localhost/db")
    assert "@modelcontextprotocol/server-postgres" in client.command
    assert "postgresql://u:p@localhost/db" in client.command


def test_mcp_slack_uses_env_for_credentials():
    client = mcp_catalog.mcp_slack("xoxb-token", "T123")
    assert client.env == {"SLACK_BOT_TOKEN": "xoxb-token", "SLACK_TEAM_ID": "T123"}


def test_mcp_gitlab_optional_api_url():
    default = mcp_catalog.mcp_gitlab("glpat-x")
    assert default.env == {"GITLAB_PERSONAL_ACCESS_TOKEN": "glpat-x"}
    custom = mcp_catalog.mcp_gitlab("glpat-x", api_url="https://gl.example.com/api/v4")
    assert custom.env["GITLAB_API_URL"] == "https://gl.example.com/api/v4"


def test_mcp_sequential_thinking_needs_no_credentials():
    client = mcp_catalog.mcp_sequential_thinking()
    assert "@modelcontextprotocol/server-sequential-thinking" in client.command


def test_known_mcps_catalog_shape():
    assert len(KNOWN_MCPS) >= 6
    ids = {entry["id"] for entry in KNOWN_MCPS}
    assert {"postgres", "slack", "gitlab", "sequential_thinking"} <= ids
    for entry in KNOWN_MCPS:
        assert {"id", "name", "description", "factory", "required_args"} <= entry.keys()
        assert hasattr(mcp_catalog, entry["factory"])


# ── deepened domain capabilities (second-tier) ────────────────────────────────


# time: scheduling
async def test_time_business_days_between():
    terr = time_terr()
    # Mon 2026-01-05 → Mon 2026-01-12 is exactly one week = 5 business days.
    out = await _tool(terr, "business_days_between").call(
        start="2026-01-05T00:00:00", end="2026-01-12T00:00:00")
    assert out == "5"
    # Reversed range is negative.
    rev = await _tool(terr, "business_days_between").call(
        start="2026-01-12T00:00:00", end="2026-01-05T00:00:00")
    assert rev == "-5"


async def test_time_next_weekday_by_name_and_index():
    terr = time_terr()
    # 2026-01-05 is a Monday; next Friday is 2026-01-09.
    out = await _tool(terr, "next_weekday").call(value="2026-01-05T12:00:00", weekday="Friday")
    assert out == "2026-01-09"
    # Same weekday, non-inclusive → jumps a week.
    nxt = await _tool(terr, "next_weekday").call(value="2026-01-05T12:00:00", weekday=0)
    assert nxt == "2026-01-12"


async def test_time_add_business_days_skips_weekend():
    terr = time_terr()
    # Fri 2026-01-09 + 1 business day = Mon 2026-01-12.
    out = await _tool(terr, "add_business_days").call(value="2026-01-09T09:00:00", amount=1)
    assert out.startswith("2026-01-12T09:00:00")


async def test_time_since_and_schedule_info():
    terr = time_terr()
    since = await _run_skill(terr, "time_since", value="2000-01-01T00:00:00+00:00")
    assert "ago" in since
    info = json.loads(await _run_skill(terr, "schedule_info", value="2026-01-05T00:00:00+00:00"))
    assert info["weekday"] == "Monday"
    assert info["quarter"] == 1
    assert info["is_weekend"] is False


# math: numerical analysis + units
async def test_math_convert_unit_groups():
    conv = _tool(math_terr(), "convert_unit")
    assert await conv.call(value=1, from_unit="km", to_unit="m") == "1000"
    assert await conv.call(value=100, from_unit="c", to_unit="f") == "212"
    assert await conv.call(value=1, from_unit="kg", to_unit="g") == "1000"


async def test_math_convert_unit_rejects_incompatible():
    with pytest.raises(ValueError, match="incompatible|unknown"):
        await _tool(math_terr(), "convert_unit").call(value=1, from_unit="kg", to_unit="m")


async def test_math_solve_and_interest():
    terr = math_terr()
    assert await _tool(terr, "solve_linear").call(a=2, b=-10) == "5"
    out = json.loads(await _tool(terr, "compound_interest").call(
        principal=1000, rate=0.1, periods=1))
    assert out["final_amount"] == 1100


async def test_math_linear_regression_perfect_fit():
    out = json.loads(await _run_skill(math_terr(), "linear_regression",
                                      points=[[0, 1], [1, 3], [2, 5]]))
    assert out["slope"] == 2
    assert out["intercept"] == 1
    assert out["r_squared"] == 1


async def test_math_stats_summary():
    out = json.loads(await _run_skill(math_terr(), "stats_summary", values=[1, 2, 3, 4]))
    assert out["count"] == 4
    assert out["mean"] == 2.5
    assert out["min"] == 1 and out["max"] == 4


async def test_math_percentage_clamp_scale():
    terr = math_terr()
    assert await _tool(terr, "percentage").call(value=25, total=200) == "12.5%"
    assert await _tool(terr, "clamp").call(value=15, min_v=0, max_v=10) == 10
    assert await _tool(terr, "linear_scale").call(
        value=5, in_min=0, in_max=10, out_min=0, out_max=100) == 50


# text: templating, stats, sections
async def test_text_render_template():
    out = await _tool(text_terr(), "render_template").call(
        text="Hello {{ name }}, you are {{ age }}.",
        variables={"name": "Alice", "age": 30})
    assert out == "Hello Alice, you are 30."


async def test_text_render_template_leaves_unknown():
    out = await _tool(text_terr(), "render_template").call(
        text="{{ known }} and {{ unknown }}", variables={"known": "X"})
    assert out == "X and {{ unknown }}"


async def test_text_extract_sentences_and_numbers():
    terr = text_terr()
    sents = await _tool(terr, "extract_sentences").call(text="Hi there. How are you? Fine!")
    assert len(sents) == 3
    nums = await _tool(terr, "extract_numbers").call(text="cost 3.5 and 12 items, -7 left")
    assert nums == ["3.5", "12", "-7"]


async def test_text_stats_skill():
    out = json.loads(await _run_skill(text_terr(), "text_stats",
                                      text="One two three. Four five."))
    assert out["words"] == 5
    assert out["sentences"] == 2


async def test_text_extract_sections():
    md = "# Title\n\nintro\n\n## Section A\ntext\n\n### Sub\nmore"
    out = await _run_skill(text_terr(), "extract_sections", text=md)
    assert [s["level"] for s in out] == [1, 2, 3]
    assert out[1]["title"] == "Section A"


async def test_text_diff_and_truncate():
    terr = text_terr()
    diff = await _run_skill(terr, "text_diff", a="line1\nline2\n", b="line1\nCHANGED\n")
    assert "CHANGED" in diff
    trunc = await _tool(terr, "text_truncate").call(text="abcdefgh", max_chars=5)
    assert trunc == "ab..."


async def test_text_regex_replace():
    out = await _tool(text_terr(), "regex_replace").call(
        text="2026-01-05", pattern=r"(\d+)-(\d+)-(\d+)", replacement=r"\3/\2/\1")
    assert out == "05/01/2026"


# data: merge, flatten, transform, profile
async def test_data_merge_and_flatten():
    terr = data_terr()
    merged = await _tool(terr, "merge_json").call(
        base={"a": 1, "nested": {"x": 1}}, patch={"b": 2, "nested": {"y": 2}})
    assert merged == {"a": 1, "b": 2, "nested": {"x": 1, "y": 2}}
    flat = await _tool(terr, "flatten_json").call(data={"a": {"b": [1, 2]}})
    assert flat == {"a.b.0": 1, "a.b.1": 2}


async def test_data_json_transform_and_profile():
    terr = data_terr()
    out = await _run_skill(terr, "json_transform",
                           data={"user": {"id": 1, "name": "Alice"}},
                           mapping={"id": "user.id", "username": "user.name", "missing": "x.y"})
    assert out == {"id": 1, "username": "Alice", "missing": None}
    prof = json.loads(await _run_skill(terr, "data_profile",
                                       rows=[{"a": 1, "b": "x"}, {"a": 2}]))
    assert prof["row_count"] == 2
    assert prof["columns"]["b"]["missing"] == 1


async def test_data_csv_filter():
    csv_text = "name,age\nalice,30\nbob,25\ncarol,40\n"
    out = await _run_skill(data_terr(), "csv_filter",
                           text=csv_text, field="age", op="gt", value="28")
    assert "alice" in out and "carol" in out and "bob" not in out


# collection: aggregate, pivot, window, join, filter
async def test_collection_aggregate():
    rows = [{"team": "red", "n": 10}, {"team": "red", "n": 20}, {"team": "blue", "n": 5}]
    out = await _run_skill(collection_terr(), "aggregate",
                           rows=rows, group_by="team", agg="sum", field="n")
    by_team = {r["team"]: r for r in out}
    assert by_team["red"]["sum_n"] == 30
    assert by_team["red"]["count"] == 2
    assert by_team["blue"]["sum_n"] == 5


async def test_collection_pivot_and_window():
    rows = [
        {"date": "d1", "metric": "clicks", "v": 5},
        {"date": "d1", "metric": "views", "v": 50},
        {"date": "d2", "metric": "clicks", "v": 7},
    ]
    pivoted = await _run_skill(collection_terr(), "pivot",
                               rows=rows, index="date", column="metric", value="v")
    d1 = next(r for r in pivoted if r["date"] == "d1")
    assert d1["clicks"] == 5 and d1["views"] == 50
    win = await _tool(collection_terr(), "window").call(items=[1, 2, 3, 4], size=2)
    assert win == [[1, 2], [2, 3], [3, 4]]


async def test_collection_filter_pluck_join():
    rows = [{"id": 1, "name": "a", "n": 5}, {"id": 2, "name": "b", "n": 15}]
    filtered = await _tool(collection_terr(), "filter_records").call(
        rows=rows, field="n", op="gt", value=10)
    assert filtered == [{"id": 2, "name": "b", "n": 15}]
    plucked = await _tool(collection_terr(), "pluck").call(rows=rows, fields=["id", "name"])
    assert plucked == [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
    joined = await _run_skill(collection_terr(), "join_records",
                              left=[{"id": 1, "x": "L"}], right=[{"id": 1, "y": "R"}], on="id")
    assert joined == [{"id": 1, "x": "L", "y": "R"}]


async def test_collection_top_n():
    rows = [{"n": 3}, {"n": 1}, {"n": 9}, {"n": 5}]
    out = await _run_skill(collection_terr(), "top_n", rows=rows, field="n", n=2)
    assert [r["n"] for r in out] == [9, 5]


# encoding: hmac, token, jwt, fingerprint, detect
async def test_encoding_hmac_and_token():
    import hashlib
    import hmac as _hmac
    terr = encoding_terr()
    sig = await _tool(terr, "hmac_sign").call(message="msg", key="secret")
    expected = _hmac.new(b"secret", b"msg", hashlib.sha256).hexdigest()
    assert sig == expected and len(sig) == 64
    tok = await _tool(terr, "random_token").call(length=16, charset="hex")
    assert len(tok) == 16 and all(c in "0123456789abcdef" for c in tok)


async def test_encoding_jwt_decode():
    # Standard example JWT (HS256) — header {alg:HS256,typ:JWT}, payload {sub,name,iat}.
    token = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
             "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
             "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
    out = await _tool(encoding_terr(), "jwt_decode").call(token=token)
    assert out["header"]["alg"] == "HS256"
    assert out["payload"]["name"] == "John Doe"


async def test_encoding_jwt_rejects_malformed():
    with pytest.raises(ValueError, match="three dot-separated"):
        await _tool(encoding_terr(), "jwt_decode").call(token="not.a.jwt.token.x")


async def test_encoding_fingerprint_order_invariant():
    fp = _skill(encoding_terr(), "fingerprint")
    a = await fp.execute(data={"x": 1, "y": 2})
    b = await fp.execute(data={"y": 2, "x": 1})
    assert a == b and len(a) == 64


async def test_encoding_detect_and_roundtrip():
    terr = encoding_terr()
    assert await _tool(terr, "detect_encoding").call(data="48656c6c6f") == "hex"
    assert await _tool(terr, "detect_encoding").call(data="hello%20world") == "url"
    j2b = await _tool(terr, "json_to_base64").call(data={"k": "v"})
    assert await _tool(terr, "base64_to_json").call(data=j2b) == {"k": "v"}


# web: URL utils + scraping (mocked transport)
async def test_web_parse_and_build_url():
    terr = web_terr()
    parsed = await _tool(terr, "parse_url").call(url="https://x.com/a/b?q=1&p=2")
    assert parsed["host"] == "x.com" and parsed["params"]["q"] == "1"
    built = await _tool(terr, "build_url").call(
        base="https://x.com/api", path="search", params={"q": "hi"})
    assert built == "https://x.com/search?q=hi"


async def test_web_extract_links_and_metadata(monkeypatch):
    import httpx
    html = (
        '<html><head><title>My Page</title>'
        '<meta name="description" content="A test page">'
        '<meta property="og:title" content="OG Title"></head>'
        '<body><a href="/about">About</a><a href="https://ext.com/x">Ext</a>'
        '<a href="#skip">frag</a></body></html>'
    )
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text=html))
    _patch_httpx(monkeypatch, transport)
    links = await _run_skill(web_terr(), "extract_links", url="https://site.com/page")
    assert "https://site.com/about" in links
    assert "https://ext.com/x" in links
    assert not any("#skip" in lnk for lnk in links)
    meta = await _run_skill(web_terr(), "extract_metadata", url="https://site.com/page")
    assert meta["title"] == "My Page"
    assert meta["description"] == "A test page"
    assert meta["meta"]["og:title"] == "OG Title"


async def test_web_extract_tables(monkeypatch):
    import httpx
    html = ("<table><tr><th>A</th><th>B</th></tr>"
            "<tr><td>1</td><td>2</td></tr></table>")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text=html))
    _patch_httpx(monkeypatch, transport)
    tables = await _run_skill(web_terr(), "extract_tables", url="https://x.com")
    assert tables == [[["A", "B"], ["1", "2"]]]


async def test_web_http_post_json(monkeypatch):
    import httpx

    def handler(request):
        return httpx.Response(200, text=request.content.decode())

    transport = httpx.MockTransport(handler)
    _patch_httpx(monkeypatch, transport)
    out = await _tool(web_terr(), "http_post").call(url="https://x.com", data={"a": 1})
    assert json.loads(out) == {"a": 1}


# fs: search, copy/move, grep, tree, dir_stats, replace
async def test_fs_search_copy_move():
    with tempfile.TemporaryDirectory() as d:
        Path(d, "a.txt").write_text("1")
        Path(d, "b.log").write_text("2")
        terr = fs_terr(d)
        found = await _tool(terr, "search_files").call(pattern="*.txt")
        assert [f["name"] for f in found] == ["a.txt"]
        await _tool(terr, "copy_file").call(src="a.txt", dst="copy.txt")
        assert Path(d, "copy.txt").read_text() == "1"
        await _tool(terr, "move_file").call(src="copy.txt", dst="moved.txt")
        assert not Path(d, "copy.txt").exists()
        assert Path(d, "moved.txt").exists()


async def test_fs_grep_and_tree_and_stats():
    with tempfile.TemporaryDirectory() as d:
        Path(d, "sub").mkdir()
        Path(d, "sub", "x.py").write_text("import os\nprint('hi')\n")
        Path(d, "y.py").write_text("print('bye')\n")
        terr = fs_terr(d)
        grep = await _run_skill(terr, "grep_files", pattern=r"print")
        assert grep.count("print") >= 2
        tree = await _run_skill(terr, "file_tree", path=".")
        assert "sub/" in tree and "y.py" in tree
        stats = json.loads(await _run_skill(terr, "dir_stats", path="."))
        assert stats["files"] == 2
        assert stats["by_extension"][".py"]["count"] == 2


async def test_fs_replace_in_files_and_read_multiple():
    with tempfile.TemporaryDirectory() as d:
        Path(d, "a.txt").write_text("foo bar foo")
        Path(d, "b.txt").write_text("nothing here")
        terr = fs_terr(d)
        summary = await _run_skill(terr, "replace_in_files",
                                   find="foo", replace_with="X", file_glob="*.txt")
        assert "2 replacement" in summary
        assert Path(d, "a.txt").read_text() == "X bar X"
        multi = await _run_skill(terr, "read_multiple", paths=["a.txt", "b.txt"])
        assert multi["a.txt"] == "X bar X"


# knowledge: research + cross_reference (mocked)
async def test_knowledge_research_and_cross_reference(monkeypatch):
    import httpx
    from autumn.builtin import knowledge_terr

    ddg_html = (
        '<a class="result__a" href="https://r1.com">Result One</a>'
        '<a class="result__snippet">snippet one</a>'
    )

    def handler(request):
        if "duckduckgo" in str(request.url):
            return httpx.Response(200, text=ddg_html)
        return httpx.Response(200, text="<html><body>Page body text</body></html>")

    transport = httpx.MockTransport(handler)
    _patch_httpx(monkeypatch, transport)

    async def recall_fn(query, k):
        return f"local:{query}"

    terr = knowledge_terr(recall_fn=recall_fn)
    research = await _run_skill(terr, "research", query="topic", max_results=1)
    assert "Result One" in research
    xref = await _run_skill(terr, "cross_reference", query="topic")
    assert "local:topic" in xref
    assert "Result One" in xref


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

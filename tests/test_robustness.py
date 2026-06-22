"""Second-pass robustness tests: API resilience, memory tolerance/concurrency,
checker/loader hardening, and the framework cooperative-workflow gates wired
end-to-end (rather than only as isolated config properties).
"""
import asyncio

import httpx
import pytest

from autumn import Autumn
from autumn.core.api.base import ModelAPIInterface
from autumn.core.components.checker import Checker
from autumn.core.config import AutumnConfig, BehaviorConfig, ModelConfig, StorageConfig
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea, MemoryBackend, _decode
from autumn.core.memory.project import ProjectMemory
from autumn.core.types import Message, Protocol, Role


# ── API: retry policy ─────────────────────────────────────────────────────────


def _api_with_handler(handler) -> ModelAPIInterface:
    api = ModelAPIInterface("k", "http://x", "m", Protocol.OPENAI)
    api._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return api


async def _no_sleep(*_a, **_k):
    return None


async def test_post_does_not_retry_client_error(monkeypatch):
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad request"})

    api = _api_with_handler(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await api.complete([Message(role=Role.USER, content="hi")])
    assert calls["n"] == 1  # failed fast — a 400 can never succeed on retry


async def test_post_retries_server_error(monkeypatch):
    monkeypatch.setattr("autumn.core.api.base.asyncio.sleep", _no_sleep)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(500, json={"error": "server"})

    api = _api_with_handler(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await api.complete([Message(role=Role.USER, content="hi")])
    assert calls["n"] == 4  # 1 initial + 3 retries


async def test_post_honors_retry_after(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr("autumn.core.api.base.asyncio.sleep", fake_sleep)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(429, headers={"retry-after": "2"}, json={"e": "slow down"})

    api = _api_with_handler(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await api.complete([Message(role=Role.USER, content="hi")])
    assert calls["n"] == 4  # 429 is retryable
    assert 2.0 in slept  # the Retry-After delay was observed


# ── API: usage + parse robustness ─────────────────────────────────────────────


def test_record_usage_tolerates_non_numeric():
    api = ModelAPIInterface("k", "http://x", "m", Protocol.OPENAI)
    api._record_usage({"usage": {"prompt_tokens": "abc", "completion_tokens": 5}})
    assert api.last_usage is None  # no crash on a successful call


def test_extract_content_graceful_on_empty_body():
    api = ModelAPIInterface("k", "http://x", "m", Protocol.OPENAI)
    assert api._extract_content({}) == ""
    assert api._parse_tool_response({}) == ("", [])


def test_parse_tool_response_tolerates_bad_arguments():
    api = ModelAPIInterface("k", "http://x", "m", Protocol.OPENAI)
    data = {
        "choices": [{"message": {"content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "f", "arguments": "not json"}},
        ]}}],
    }
    text, calls = api._parse_tool_response(data)
    assert calls[0].arguments == {}  # malformed args degrade to empty, not a crash


async def test_stream_complete_resets_stale_usage(monkeypatch):
    api = ModelAPIInterface("k", "http://x", "m", Protocol.OPENAI)
    api.last_usage = {"prompt_tokens": 99, "completion_tokens": 99}  # left over
    api._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="")))
    async for _ in api.stream_complete([Message(role=Role.USER, content="hi")]):
        pass
    assert api.last_usage is None  # not the stale 99/99 from a prior call


# ── memory: decode tolerance ──────────────────────────────────────────────────


def test_decode_skips_corrupt_entry():
    good = {"_m": True, "_v": 2, "id": "a", "content": "hi", "timestamp": 1.0}
    bad = {"_m": True}  # missing id/content/timestamp → would KeyError in from_dict
    out = _decode([good, bad])
    assert len(out) == 1
    assert out[0].content == "hi"


# ── memory: project metadata concurrency ──────────────────────────────────────


class _SlowDictBackend(MemoryBackend):
    """A backend whose get/set yield to the loop, forcing real interleaving so a
    missing read-modify-write lock would manifest as a lost update."""

    def __init__(self):
        self._d: dict = {}

    async def get(self, key):
        await asyncio.sleep(0)
        return self._d.get(key)

    async def set(self, key, value):
        await asyncio.sleep(0)
        self._d[key] = value

    async def delete(self, key):
        self._d.pop(key, None)

    async def keys(self):
        return list(self._d)

    async def clear(self):
        self._d.clear()


async def test_project_add_file_concurrent_no_lost_update():
    pm = ProjectMemory(_SlowDictBackend())
    zone = pm.zone("p1")
    await asyncio.gather(*(zone.add_file(f"f{i}.txt") for i in range(10)))
    meta = await zone.get_meta()
    assert sorted(meta.files) == sorted(f"f{i}.txt" for i in range(10))


# ── memory: markdown diff-before-write ────────────────────────────────────────


async def test_markdown_skips_unchanged_entry_writes(monkeypatch, tmp_path):
    import autumn.core.memory.backends.markdown_backend as mb

    calls = {"n": 0}
    original = mb._atomic_write

    def counting(path, text):
        calls["n"] += 1
        return original(path, text)

    monkeypatch.setattr(mb, "_atomic_write", counting)
    backend = mb.MarkdownBackend(tmp_path)
    hist = [
        {"_m": True, "_v": 2, "id": f"e{i}", "content": f"c{i}", "timestamp": float(i)}
        for i in range(3)
    ]
    await backend.set("shared:history", hist)
    assert calls["n"] == 3  # first store writes every entry
    calls["n"] = 0
    await backend.set("shared:history", hist)  # identical history
    assert calls["n"] == 0  # nothing rewritten


# ── checker: non-str API response ─────────────────────────────────────────────


class _NoneAPI:
    last_usage = None

    async def complete(self, messages, **kwargs):
        return None  # a misbehaving provider returns a non-string


async def test_checker_survives_non_str_response():
    chk = Checker("wp", _NoneAPI())
    memory = MemoryArea("x", DictBackend())
    ok, out = await chk.validate("this is a long enough output", memory)
    assert ok is True  # passes through instead of crashing the turn


# ── fs_terr: recursive listing must not disclose symlink escapes ──────────────


async def test_fs_recursive_list_excludes_symlink_escape(tmp_path):
    from autumn.builtin import fs_terr

    root = tmp_path / "sandbox"
    root.mkdir()
    (root / "inside.txt").write_text("ok")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    (root / "escape").symlink_to(outside)  # symlink inside root → file outside

    list_dir = next(t for t in fs_terr(root).tools if t.name == "list_dir")
    entries = await list_dir.call(path=".", recursive=True)
    names = {e["name"] for e in entries}
    assert "inside.txt" in names
    assert "escape" not in names  # escaping symlink filtered from the listing


# ── plugin loader: one bad plugin must not abort the rest ──────────────────────


async def test_loader_skips_broken_plugin(tmp_path):
    from autumn.plugins.loader import PluginLoader

    (tmp_path / "a_broken.py").write_text("raise RuntimeError('boom at import')\n")
    (tmp_path / "b_good.py").write_text(
        "from autumn import Tool, ToolParameter\n"
        "good_tool = Tool('good_tool', 'd', lambda x: x, [ToolParameter('x','string','d')])\n",
    )
    loader = PluginLoader()
    with pytest.warns(UserWarning):
        loader.load_from_directory(tmp_path)
    assert "good_tool" in loader.all()  # the healthy plugin still loaded


# ── framework: cooperative gates wired end-to-end ─────────────────────────────


def _config(tmp_path, behavior: BehaviorConfig) -> AutumnConfig:
    mc = ModelConfig("k", "http://localhost", "m", Protocol.OPENAI)
    return AutumnConfig(
        a1=mc, a2=mc, a3=mc, a4=mc,  # a4 present so the research path can light up
        storage=StorageConfig(db_path=str(tmp_path / "mem.db")),
        behavior=behavior,
    )


def test_master_switch_on_wires_features(tmp_path):
    b = BehaviorConfig(
        cooperative_workflow=True,
        a1_supervision=True,
        a4_delegate_to_a1=True,
        a4_knowledge_terr=True,
    )
    autumn = Autumn(_config(tmp_path, b))
    assert autumn.wp1._supervision is True
    assert autumn.wp4._delegation_api is autumn.a1
    assert "knowledge" in {t["name"] for t in autumn.describe_terrs()}
    assert len(autumn._collect_knowledge_skills()) == 5
    assert autumn.wp4.can_research is True


def test_master_switch_off_reverts_wiring(tmp_path):
    b = BehaviorConfig(
        cooperative_workflow=False,
        a1_supervision=True,
        a4_delegate_to_a1=True,
        a4_knowledge_terr=True,
    )
    autumn = Autumn(_config(tmp_path, b))
    assert autumn.wp1._supervision is False
    assert autumn.wp4._delegation_api is None
    assert "knowledge" not in {t["name"] for t in autumn.describe_terrs()}
    assert autumn._collect_knowledge_skills() == []


def test_capability_digest_omits_disabled_terr(tmp_path):
    from autumn.core.components.terr import Terr
    from autumn.core.components.tool import Tool, ToolParameter

    autumn = Autumn(_config(tmp_path, BehaviorConfig()))
    autumn.register_terr(Terr("alpha", "Alpha domain", tools=[
        Tool("a_do", "do a", lambda x: x, [ToolParameter("x", "string", "d")])]))
    autumn.register_terr(Terr("beta", "Beta domain", tools=[
        Tool("b_do", "do b", lambda x: x, [ToolParameter("x", "string", "d")])]))
    autumn.plugins.set_terr_enabled("beta", False)

    digest = autumn._capability_digest()
    assert "alpha" in digest
    assert "beta" not in digest


async def test_a3_skill_provider_gates_live(tmp_path):
    # The provider is always wired now; it returns [] when the whitelist is empty
    # and the curated skill once the whitelist names it — a live, master-switch-
    # respecting gate rather than a frozen one.
    autumn = Autumn(_config(tmp_path, BehaviorConfig(a3_lite_skills=[])))
    assert autumn._collect_a3_skills() == []
    autumn.config.behavior.a3_lite_skills = ["recall"]
    autumn.add_memory_skills(area="shared")
    names = {s.name for s in autumn._collect_a3_skills()}
    assert "recall" in names

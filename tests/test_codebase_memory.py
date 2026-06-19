"""Tests for the framework-owned codebase-memory token-saving layer.

Covers the three depths of the integration, all with a faked MCP client (no
uvx/npx, no subprocess):

1. ``CodebaseMemory`` core — index-once + cached architecture brief + tolerance.
2. WP2 injection — the brief reaches the executor's system prompt.
3. ``Autumn.start/stop_codebase_memory`` — connect, register the ``codebase``
   Terr, gate the brief on CODE tasks.
4. The catalog factory + behaviour flag (pure).
"""
import asyncio

import pytest

from autumn import Autumn
from autumn.builtin import mcp_codebase_memory
from autumn.builtin.mcp_catalog import MCP_BY_ID
from autumn.core.codebase import CodebaseMemory
from autumn.core.config import AutumnConfig, BehaviorConfig, ModelConfig, StorageConfig
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.mom2 import Mom2
from autumn.core.memory.shared import SharedZone
from autumn.core.types import Message, Protocol, Role, TaskType
from autumn.core.workspace.wp2 import WP2Tas


# ── fakes ─────────────────────────────────────────────────────────────────────


class _FakeGraphClient:
    """Stands in for a connected codebase-memory-mcp client."""

    def __init__(self, *, arch_text="ARCH: 3 packages · entry main() · 12 routes",
                 reject_project_arg=False):
        self.connected = False
        self.calls: list[tuple[str, dict]] = []
        self._arch_text = arch_text
        self._reject_project_arg = reject_project_arg

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def list_tools(self):
        return [
            {"name": "index_repository", "description": "index", "inputSchema": {}},
            {"name": "get_architecture", "description": "arch", "inputSchema": {}},
            {"name": "search_graph", "description": "search", "inputSchema": {}},
            {"name": "trace_path", "description": "trace", "inputSchema": {}},
        ]

    async def call_tool(self, name, args):
        self.calls.append((name, dict(args)))
        if name == "index_repository":
            return [{"type": "text", "text": "indexed 100 nodes / 240 edges"}]
        if name == "get_architecture":
            if self._reject_project_arg and args.get("project"):
                return []  # mimic a server that only has one default project
            return [{"type": "text", "text": self._arch_text}]
        return []

    def count(self, tool: str) -> int:
        return sum(1 for n, _ in self.calls if n == tool)


class _BoomClient(_FakeGraphClient):
    async def call_tool(self, name, args):
        raise RuntimeError("server down")


# ── 1. CodebaseMemory core ─────────────────────────────────────────────────────


async def test_ensure_indexed_is_idempotent():
    client = _FakeGraphClient()
    cb = CodebaseMemory(client, "/srv/app")
    assert await cb.ensure_indexed() is True
    assert await cb.ensure_indexed() is True
    assert cb.indexed is True
    assert client.count("index_repository") == 1  # indexed exactly once
    # The repo is forwarded as the index target.
    assert client.calls[0] == ("index_repository", {"repo_path": "/srv/app"})


async def test_architecture_brief_indexes_then_caches():
    client = _FakeGraphClient()
    cb = CodebaseMemory(client, "/srv/app")
    brief = await cb.architecture_brief()
    assert "ARCH:" in brief
    again = await cb.architecture_brief()
    assert again == brief
    assert client.count("index_repository") == 1
    assert client.count("get_architecture") == 1  # cached, not re-fetched
    # project arg derived from the repo basename
    arch_call = next(a for n, a in client.calls if n == "get_architecture")
    assert arch_call == {"project": "app"}


async def test_architecture_brief_truncates():
    client = _FakeGraphClient(arch_text="x" * 5000)
    cb = CodebaseMemory(client, "/srv/app")
    brief = await cb.architecture_brief(max_chars=100)
    assert len(brief) <= 102 and brief.endswith("…")


async def test_architecture_brief_falls_back_without_project_arg():
    client = _FakeGraphClient(reject_project_arg=True)
    cb = CodebaseMemory(client, "/srv/app")
    brief = await cb.architecture_brief()
    assert "ARCH:" in brief
    # tried with project, then retried with {}
    arch_calls = [a for n, a in client.calls if n == "get_architecture"]
    assert arch_calls == [{"project": "app"}, {}]


async def test_core_is_failure_tolerant():
    cb = CodebaseMemory(_BoomClient(), "/srv/app")
    assert await cb.ensure_indexed() is False
    assert await cb.architecture_brief() == ""


async def test_refresh_reindexes():
    client = _FakeGraphClient()
    cb = CodebaseMemory(client, "/srv/app")
    await cb.architecture_brief()
    await cb.refresh()
    assert client.count("index_repository") == 2


# ── 2. WP2 injection ───────────────────────────────────────────────────────────


class _ScriptedAPI:
    def __init__(self):
        self.protocol = Protocol.OPENAI
        self.complete_prompts: list[list[Message]] = []

    async def complete(self, messages, **kwargs):
        self.complete_prompts.append(list(messages))
        return "RESULT"


def _make_mom2() -> Mom2:
    return Mom2(DictBackend(), SharedZone(DictBackend()))


def _system_text(api: _ScriptedAPI) -> str:
    return api.complete_prompts[0][0].content


async def test_wp2_injects_brief_into_system_prompt():
    api = _ScriptedAPI()

    async def provider(task_input, task_type):
        return "ARCH-MAP-XYZ"

    wp2 = WP2Tas(api, _make_mom2(), codebase_brief_provider=provider)
    await wp2.process_with_trace("refactor the parser", TaskType.CODE)
    system = _system_text(api)
    assert "ARCH-MAP-XYZ" in system
    assert "Codebase map" in system


async def test_wp2_no_provider_leaves_prompt_unchanged():
    api = _ScriptedAPI()
    wp2 = WP2Tas(api, _make_mom2())
    await wp2.process_with_trace("refactor the parser", TaskType.CODE)
    assert "Codebase map" not in _system_text(api)


async def test_wp2_tolerates_provider_failure():
    api = _ScriptedAPI()

    async def boom(task_input, task_type):
        raise RuntimeError("layer down")

    wp2 = WP2Tas(api, _make_mom2(), codebase_brief_provider=boom)
    out, *_ = await wp2.process_with_trace("do it", TaskType.CODE)
    assert out == "RESULT"  # turn still completes
    assert "Codebase map" not in _system_text(api)


# ── 3. Autumn framework wiring ─────────────────────────────────────────────────


def _config(tmp_path) -> AutumnConfig:
    mc = ModelConfig("k", "http://localhost", "m", Protocol.OPENAI)
    return AutumnConfig(
        a1=mc, a2=mc, a3=mc,
        storage=StorageConfig(db_path=str(tmp_path / "mem.db")),
    )


async def test_start_registers_codebase_terr_and_brief(tmp_path, monkeypatch):
    client = _FakeGraphClient()
    monkeypatch.setattr(
        "autumn.builtin.mcp_catalog.mcp_codebase_memory", lambda repo=None: client,
    )
    autumn = Autumn(_config(tmp_path))
    try:
        assert await autumn.start_codebase_memory("/srv/app") is True
        assert autumn.codebase is not None
        assert client.connected is True
        # The raw graph tools are registered under a native `codebase` Terr.
        assert "codebase" in autumn.plugins.all_terrs()
        assert "search_graph" in autumn.plugins.all()
        assert "trace_path" in autumn.plugins.all()
        # Pre-warm indexing settles.
        assert await autumn.codebase.ensure_indexed() is True

        # Brief gated on CODE tasks only.
        code_brief = await autumn._codebase_brief("fix bug", TaskType.CODE)
        assert "ARCH:" in code_brief
        assert await autumn._codebase_brief("write a poem", TaskType.WRITE) == ""
    finally:
        await autumn.close()


async def test_start_is_idempotent_same_repo(tmp_path, monkeypatch):
    clients = []

    def factory(repo=None):
        c = _FakeGraphClient()
        clients.append(c)
        return c

    monkeypatch.setattr("autumn.builtin.mcp_catalog.mcp_codebase_memory", factory)
    autumn = Autumn(_config(tmp_path))
    try:
        await autumn.start_codebase_memory("/srv/app")
        await autumn.start_codebase_memory("/srv/app")  # same repo → no reconnect
        assert len(clients) == 1
    finally:
        await autumn.close()


async def test_stop_unregisters_everything(tmp_path, monkeypatch):
    client = _FakeGraphClient()
    monkeypatch.setattr(
        "autumn.builtin.mcp_catalog.mcp_codebase_memory", lambda repo=None: client,
    )
    autumn = Autumn(_config(tmp_path))
    try:
        await autumn.start_codebase_memory("/srv/app")
        await autumn.stop_codebase_memory()
        assert autumn.codebase is None
        assert "codebase" not in autumn.plugins.all_terrs()
        assert "search_graph" not in autumn.plugins.all()
        assert client.connected is False
        # Brief provider goes quiet again.
        assert await autumn._codebase_brief("fix bug", TaskType.CODE) == ""
    finally:
        await autumn.close()


async def test_brief_off_before_start(tmp_path):
    autumn = Autumn(_config(tmp_path))
    try:
        assert autumn.codebase is None
        assert await autumn._codebase_brief("fix bug", TaskType.CODE) == ""
    finally:
        await autumn.close()


# ── 4. catalog factory + behaviour flag (pure) ─────────────────────────────────


def test_factory_command_forms():
    c = mcp_codebase_memory("/srv/app")
    assert c.command == ["uvx", "codebase-memory-mcp"]
    assert c.cwd == "/srv/app"
    assert mcp_codebase_memory(binary="npx").command == ["npx", "-y", "codebase-memory-mcp"]
    assert mcp_codebase_memory(binary="/opt/cbm").command == ["/opt/cbm"]
    assert mcp_codebase_memory().cwd is None


def test_not_in_generic_catalog():
    # It's a framework subsystem now, not a generic /mcps catalog entry.
    assert "codebase_memory" not in MCP_BY_ID


def test_behaviour_flag(monkeypatch):
    assert BehaviorConfig().codebase_memory_enabled is False
    monkeypatch.setenv("CODEBASE_MEMORY_ENABLED", "true")
    monkeypatch.setenv("CODEBASE_MEMORY_REPO", "/srv/app")
    b = BehaviorConfig.from_env()
    assert b.codebase_memory_enabled is True
    assert b.codebase_memory_repo == "/srv/app"

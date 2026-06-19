"""Tests for the codebase-memory token-saving layer.

Covers the catalog factory/entry, the behaviour flag, and the
``/config/codebase-memory`` toggle endpoint that connects/disconnects the
code-graph MCP. The MCP subprocess is faked (no uvx/npx, no network) the same
way test_server_mcps does.
"""
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTUMN_SKIP_INIT", "1")

from autumn.builtin import mcp_codebase_memory  # noqa: E402
from autumn.builtin.mcp_catalog import MCP_BY_ID  # noqa: E402
from autumn.core.config import BehaviorConfig  # noqa: E402
from autumn.server import integrations as integrations_mod  # noqa: E402
from autumn.server.app import create_app  # noqa: E402
from autumn.plugins.loader import PluginLoader  # noqa: E402


# ── catalog + factory (pure) ─────────────────────────────────────────────────────


def test_catalog_entry_is_local_with_optional_repo():
    e = MCP_BY_ID["codebase_memory"]
    assert e["category"] == "local"
    assert e["factory"] == "mcp_codebase_memory"
    # A single, *optional* repo field — connectable with no args.
    assert [f["key"] for f in e["fields"]] == ["repo"]
    assert e["fields"][0]["optional"] is True
    assert e["required_args"] == []
    assert e["setup"]["steps"] and e["setup"]["doc_url"]


def test_connectable_but_not_a_platform():
    assert integrations_mod.is_connectable("codebase_memory") is True
    assert integrations_mod.is_known("codebase_memory") is False
    assert integrations_mod.required_field_keys("codebase_memory") == []


def test_factory_command_forms():
    # Default uvx, scoped to repo via cwd.
    c = mcp_codebase_memory("/srv/app")
    assert c.command == ["uvx", "codebase-memory-mcp"]
    assert c.cwd == "/srv/app"
    # npx wrapper.
    assert mcp_codebase_memory(binary="npx").command == ["npx", "-y", "codebase-memory-mcp"]
    # Any other value is treated as a path to the native binary.
    assert mcp_codebase_memory(binary="/opt/cbm").command == ["/opt/cbm"]
    # No repo → inherit cwd.
    assert mcp_codebase_memory().cwd is None


def test_behavior_flag_default_off_and_env_parsing(monkeypatch):
    assert BehaviorConfig().codebase_memory_enabled is False
    assert BehaviorConfig().codebase_memory_repo == ""
    monkeypatch.setenv("CODEBASE_MEMORY_ENABLED", "true")
    monkeypatch.setenv("CODEBASE_MEMORY_REPO", "/srv/app")
    b = BehaviorConfig.from_env()
    assert b.codebase_memory_enabled is True
    assert b.codebase_memory_repo == "/srv/app"


# ── toggle endpoint ──────────────────────────────────────────────────────────────


class _FakeTool:
    def __init__(self, name: str):
        self.name = name
        self.description = ""
        self.parameters = []


class _FakeBehavior:
    codebase_memory_enabled = False
    codebase_memory_repo = ""


class _FakeConfig:
    def __init__(self):
        self.behavior = _FakeBehavior()


class _FakeAutumn:
    def __init__(self):
        self.plugins = PluginLoader()
        self._mcp_clients = []
        self.config = _FakeConfig()

    def register_terr(self, terr):
        for tool in terr.tools:
            self.plugins.register(tool.name, tool)
        self.plugins.register_terr(terr)

    async def close(self):
        pass


@pytest.fixture
def patched(monkeypatch):
    class _FakeClient:
        async def connect(self):
            self.connected = True

        async def disconnect(self):
            self.disconnected = True

    monkeypatch.setattr(integrations_mod, "_build_client", lambda mcp_id, args: _FakeClient())

    async def fake_tools(client):
        return [_FakeTool("search_graph"), _FakeTool("trace_path"), _FakeTool("get_architecture")]

    monkeypatch.setattr(integrations_mod, "mcp_to_tools", fake_tools)


@pytest.fixture
def client_with_autumn(patched):
    app = create_app()
    autumn = _FakeAutumn()
    with TestClient(app) as c:
        app.state.autumn = autumn
        yield c, autumn


def test_status_disabled_by_default(client_with_autumn):
    c, _ = client_with_autumn
    body = c.get("/config/codebase-memory").json()
    assert body == {"enabled": False, "connected": False, "repo": "",
                    "tool_count": 0, "error": None}


def test_enable_connects_and_disable_tears_down(client_with_autumn):
    c, autumn = client_with_autumn

    on = c.post("/config/codebase-memory", json={"enabled": True}).json()
    assert on["enabled"] is True
    assert on["connected"] is True
    assert on["tool_count"] == 3
    assert autumn.config.behavior.codebase_memory_enabled is True
    # The graph tools are live for the agent, registered under a Terr.
    assert "search_graph" in autumn.plugins.all()
    assert "integration:codebase_memory" in autumn.plugins.all_terrs()
    # And it reads as connected on the shared /mcps surface.
    cm = next(e for e in c.get("/mcps/status").json() if e["id"] == "codebase_memory")
    assert cm["connected"] is True

    off = c.post("/config/codebase-memory", json={"enabled": False}).json()
    assert off["enabled"] is False
    assert off["connected"] is False
    assert autumn.config.behavior.codebase_memory_enabled is False
    assert "search_graph" not in autumn.plugins.all()
    assert "integration:codebase_memory" not in autumn.plugins.all_terrs()


def test_enable_with_repo_override(client_with_autumn):
    c, autumn = client_with_autumn
    body = c.post("/config/codebase-memory", json={"enabled": True, "repo": "/srv/app"}).json()
    assert body["repo"] == "/srv/app"
    assert autumn.config.behavior.codebase_memory_repo == "/srv/app"


def test_enable_records_connect_error_but_keeps_flag(monkeypatch, client_with_autumn):
    c, autumn = client_with_autumn

    class _BadClient:
        async def connect(self):
            raise RuntimeError("uvx not found")

        async def disconnect(self):
            pass

    monkeypatch.setattr(integrations_mod, "_build_client", lambda mcp_id, args: _BadClient())
    body = c.post("/config/codebase-memory", json={"enabled": True}).json()
    # Flag flips on (intent persists) but the layer is not live, with a hint.
    assert body["enabled"] is True
    assert body["connected"] is False
    assert body["error"] and "uvx not found" in body["error"]


def test_status_503_without_autumn(patched):
    app = create_app()
    with TestClient(app) as c:
        assert c.get("/config/codebase-memory").status_code == 503

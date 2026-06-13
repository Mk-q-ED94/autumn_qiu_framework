"""Tests for the platform-integration endpoints (/integrations/*).

The MCP subprocess is faked out (no npx, no network): we patch the client
factory and the MCP→tools bridge so the connect/disconnect bookkeeping can be
exercised against a real PluginLoader.
"""
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTUMN_SKIP_INIT", "1")

from autumn.server.app import create_app  # noqa: E402
from autumn.server import integrations as integrations_mod  # noqa: E402
from autumn.plugins.loader import PluginLoader  # noqa: E402


# ── fakes ───────────────────────────────────────────────────────────────────────


class _FakeTool:
    """Minimal tool stand-in: a name plus assignable source_terr attributes."""

    def __init__(self, name: str):
        self.name = name
        self.description = ""
        self.parameters = []


class _FakeClient:
    def __init__(self, *, fail_connect: bool = False):
        self.fail_connect = fail_connect
        self.connected = False
        self.disconnected = False

    async def connect(self):
        if self.fail_connect:
            raise RuntimeError("npx not found")
        self.connected = True

    async def disconnect(self):
        self.disconnected = True


class _FakeAutumn:
    """Autumn-shaped object with a real PluginLoader so register/unregister and
    terr bookkeeping behave exactly as in production."""

    def __init__(self):
        self.plugins = PluginLoader()
        self._mcp_clients = []

    def register_terr(self, terr):
        for tool in terr.tools:
            self.plugins.register(tool.name, tool)
        for skill in terr.skills:
            self.plugins.register(skill.name, skill)
        self.plugins.register_terr(terr)

    async def close(self):
        pass


@pytest.fixture
def patched(monkeypatch):
    """Patch the factory + bridge so connect() spins up fake tools, not npx."""
    created: dict = {}

    def fake_build(integration_id, args):
        client = _FakeClient()
        created["client"] = client
        created["args"] = args
        return client

    async def fake_tools(client):
        return [_FakeTool("tool_a"), _FakeTool("tool_b")]

    monkeypatch.setattr(integrations_mod, "_build_client", fake_build)
    monkeypatch.setattr(integrations_mod, "mcp_to_tools", fake_tools)
    return created


@pytest.fixture
def client_with_autumn(patched):
    app = create_app()
    autumn = _FakeAutumn()
    with TestClient(app) as c:
        app.state.autumn = autumn
        yield c, autumn, patched


# ── catalog ─────────────────────────────────────────────────────────────────────


def test_catalog_lists_platforms_without_autumn():
    # Catalog is static — usable before any model is configured.
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/integrations/catalog")
    assert r.status_code == 200
    ids = [e["id"] for e in r.json()]
    assert "github" in ids
    assert "slack" in ids


def test_catalog_is_secret_free():
    body = integrations_mod.catalog()
    # Each entry exposes only render metadata, never a stored value.
    for entry in body:
        assert set(entry.keys()) == {"id", "name", "description", "fields"}
        for f in entry["fields"]:
            assert "key" in f and "label" in f
            assert "value" not in f


def test_github_field_is_secret():
    gh = next(e for e in integrations_mod.catalog() if e["id"] == "github")
    token_field = gh["fields"][0]
    assert token_field["key"] == "token"
    assert token_field["secret"] is True


# ── status ──────────────────────────────────────────────────────────────────────


def test_status_initially_all_disconnected(client_with_autumn):
    c, _, _ = client_with_autumn
    r = c.get("/integrations/status")
    assert r.status_code == 200
    body = r.json()
    assert all(e["connected"] is False for e in body)
    assert all(e["tool_count"] == 0 for e in body)


# ── connect ─────────────────────────────────────────────────────────────────────


def test_connect_brings_tools_online(client_with_autumn):
    c, autumn, created = client_with_autumn
    r = c.post("/integrations/connect", json={"id": "github", "args": {"token": "ghp_x"}})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "github"
    assert body["connected"] is True
    assert body["tool_count"] == 2

    # Tools are in the plugin registry → the WP2 agent can see them.
    assert "tool_a" in autumn.plugins.all()
    assert "tool_b" in autumn.plugins.all()
    # Registered as a Terr so it shows in the Terrs UI.
    assert "integration:github" in autumn.plugins.all_terrs()
    # The client was actually connected.
    assert created["client"].connected is True


def test_connect_reflected_in_status(client_with_autumn):
    c, _, _ = client_with_autumn
    c.post("/integrations/connect", json={"id": "github", "args": {"token": "ghp_x"}})
    body = c.get("/integrations/status").json()
    gh = next(e for e in body if e["id"] == "github")
    assert gh["connected"] is True
    assert gh["tool_count"] == 2
    assert gh["error"] is None


def test_connect_missing_required_field_400(client_with_autumn):
    c, autumn, _ = client_with_autumn
    r = c.post("/integrations/connect", json={"id": "slack", "args": {"bot_token": "x"}})
    assert r.status_code == 400
    assert "team_id" in r.json()["detail"]
    # Nothing should have been registered.
    assert "integration:slack" not in autumn.plugins.all_terrs()


def test_connect_unknown_id_404(client_with_autumn):
    c, _, _ = client_with_autumn
    r = c.post("/integrations/connect", json={"id": "nope", "args": {}})
    assert r.status_code == 404


def test_connect_failure_records_error(client_with_autumn, monkeypatch):
    c, autumn, _ = client_with_autumn

    def boom_build(integration_id, args):
        return _FakeClient(fail_connect=True)

    monkeypatch.setattr(integrations_mod, "_build_client", boom_build)
    r = c.post("/integrations/connect", json={"id": "github", "args": {"token": "ghp_x"}})
    assert r.status_code == 502

    body = c.get("/integrations/status").json()
    gh = next(e for e in body if e["id"] == "github")
    assert gh["connected"] is False
    assert gh["error"] and "npx" in gh["error"]


def test_connect_optional_field_omitted_ok(client_with_autumn):
    # gitlab's api_url is optional — connecting with just the token must work.
    c, autumn, _ = client_with_autumn
    r = c.post("/integrations/connect", json={"id": "gitlab", "args": {"token": "glpat"}})
    assert r.status_code == 200
    assert r.json()["connected"] is True


# ── reconnect / rotate ──────────────────────────────────────────────────────────


def test_reconnect_tears_down_old_client(client_with_autumn):
    c, autumn, _ = client_with_autumn
    first_clients = []

    # First connect.
    c.post("/integrations/connect", json={"id": "github", "args": {"token": "old"}})
    first_clients.append(autumn._mcp_clients[-1])
    assert len(autumn._mcp_clients) == 1

    # Rotate the token — reconnect.
    c.post("/integrations/connect", json={"id": "github", "args": {"token": "new"}})
    # Old client disconnected, only the new one owned.
    assert first_clients[0].disconnected is True
    assert len(autumn._mcp_clients) == 1


# ── disconnect ──────────────────────────────────────────────────────────────────


def test_disconnect_removes_tools(client_with_autumn):
    c, autumn, created = client_with_autumn
    c.post("/integrations/connect", json={"id": "github", "args": {"token": "ghp_x"}})
    client = created["client"]

    r = c.delete("/integrations/github")
    assert r.status_code == 200
    assert r.json()["connected"] is False

    # Tools + terr gone, client disconnected, ownership released.
    assert "tool_a" not in autumn.plugins.all()
    assert "integration:github" not in autumn.plugins.all_terrs()
    assert client.disconnected is True
    assert autumn._mcp_clients == []

    # Status reflects the removal.
    body = c.get("/integrations/status").json()
    gh = next(e for e in body if e["id"] == "github")
    assert gh["connected"] is False


def test_disconnect_unknown_id_404(client_with_autumn):
    c, _, _ = client_with_autumn
    r = c.delete("/integrations/nope")
    assert r.status_code == 404


# ── 503 when unconfigured ───────────────────────────────────────────────────────


def test_connect_unconfigured_503(patched):
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/integrations/connect", json={"id": "github", "args": {"token": "x"}})
    assert r.status_code == 503

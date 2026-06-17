"""Tests for the generalized MCP connection endpoints (/mcps/*).

These drive the Terr-page surface: the full catalog (keyless utilities + local
resources + platforms), each connectable inline. The MCP subprocess is faked
(no npx/uvx, no network) by patching the client factory and the MCP→tools
bridge, exactly like test_server_integrations.
"""
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTUMN_SKIP_INIT", "1")

from autumn.server.app import create_app  # noqa: E402
from autumn.server import integrations as integrations_mod  # noqa: E402
from autumn.plugins.loader import PluginLoader  # noqa: E402


# ── fakes (shared shape with test_server_integrations) ───────────────────────────


class _FakeTool:
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
    created: dict = {}

    def fake_build(mcp_id, args):
        client = _FakeClient()
        created["id"] = mcp_id
        created["args"] = args
        created["client"] = client
        return client

    async def fake_tools(client):
        return [_FakeTool("read_thing"), _FakeTool("list_things")]

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


# ── catalog enrichment ───────────────────────────────────────────────────────────


def test_catalog_is_enriched_and_static():
    # Usable before any model is configured.
    app = create_app()
    with TestClient(app) as c:
        r = c.get("/mcps/catalog")
    assert r.status_code == 200
    by_id = {e["id"]: e for e in r.json()}

    # Keyless utility — no fields, one-click.
    fetch = by_id["fetch"]
    assert fetch["category"] == "keyless"
    assert fetch["needs_credentials"] is False
    assert fetch["fields"] == []
    assert fetch["setup"]["summary"]

    # Local resource — a single path field + a tutorial.
    fs = by_id["filesystem"]
    assert fs["category"] == "local"
    assert fs["needs_credentials"] is True
    assert fs["fields"][0]["key"] == "root"
    assert fs["setup"]["steps"]

    # Platform — secret field + doc link.
    gh = by_id["github"]
    assert gh["category"] == "platform"
    assert gh["fields"][0]["secret"] is True
    assert gh["setup"]["doc_url"]


def test_every_entry_has_required_shape():
    app = create_app()
    with TestClient(app) as c:
        body = c.get("/mcps/catalog").json()
    for e in body:
        assert {"id", "name", "description", "factory", "category",
                "needs_credentials", "fields", "setup"} <= set(e.keys())
        # needs_credentials is consistent with the presence of fields.
        assert e["needs_credentials"] is bool(e["fields"])


# ── status ───────────────────────────────────────────────────────────────────────


def test_status_lists_whole_catalog_disconnected(client_with_autumn):
    c, _, _ = client_with_autumn
    body = c.get("/mcps/status").json()
    ids = {e["id"] for e in body}
    # Spans keyless + local + platform.
    assert {"fetch", "filesystem", "github"} <= ids
    assert all(e["connected"] is False for e in body)


# ── connect ──────────────────────────────────────────────────────────────────────


def test_connect_keyless_no_args(client_with_autumn):
    c, autumn, created = client_with_autumn
    r = c.post("/mcps/connect", json={"id": "fetch", "args": {}})
    assert r.status_code == 200
    assert r.json()["connected"] is True
    assert created["id"] == "fetch"
    assert "read_thing" in autumn.plugins.all()
    assert "integration:fetch" in autumn.plugins.all_terrs()


def test_connect_local_requires_its_field(client_with_autumn):
    c, autumn, _ = client_with_autumn
    r = c.post("/mcps/connect", json={"id": "filesystem", "args": {}})
    assert r.status_code == 400
    assert "root" in r.json()["detail"]
    assert "integration:filesystem" not in autumn.plugins.all_terrs()


def test_connect_local_with_path(client_with_autumn):
    c, _, created = client_with_autumn
    r = c.post("/mcps/connect", json={"id": "filesystem", "args": {"root": "/tmp/data"}})
    assert r.status_code == 200
    assert r.json()["connected"] is True
    assert created["args"] == {"root": "/tmp/data"}


def test_connect_unknown_id_404(client_with_autumn):
    c, _, _ = client_with_autumn
    r = c.post("/mcps/connect", json={"id": "definitely_not_real", "args": {}})
    assert r.status_code == 404


def test_connect_reflected_in_status(client_with_autumn):
    c, _, _ = client_with_autumn
    c.post("/mcps/connect", json={"id": "fetch", "args": {}})
    fetch = next(e for e in c.get("/mcps/status").json() if e["id"] == "fetch")
    assert fetch["connected"] is True
    assert fetch["tool_count"] == 2


# ── disconnect ───────────────────────────────────────────────────────────────────


def test_disconnect_removes_tools(client_with_autumn):
    c, autumn, created = client_with_autumn
    c.post("/mcps/connect", json={"id": "fetch", "args": {}})
    client = created["client"]

    r = c.delete("/mcps/fetch")
    assert r.status_code == 200
    assert r.json()["connected"] is False
    assert "read_thing" not in autumn.plugins.all()
    assert "integration:fetch" not in autumn.plugins.all_terrs()
    assert client.disconnected is True


def test_disconnect_unknown_id_404(client_with_autumn):
    c, _, _ = client_with_autumn
    r = c.delete("/mcps/definitely_not_real")
    assert r.status_code == 404


# ── shared runtime with /integrations/* ──────────────────────────────────────────


def test_platform_connected_via_mcps_shows_in_integrations(client_with_autumn):
    # github connected through the broader /mcps surface must read as connected
    # on the narrower /integrations surface too — one runtime, one truth.
    c, _, _ = client_with_autumn
    c.post("/mcps/connect", json={"id": "github", "args": {"token": "ghp_x"}})

    gh_mcp = next(e for e in c.get("/mcps/status").json() if e["id"] == "github")
    gh_int = next(e for e in c.get("/integrations/status").json() if e["id"] == "github")
    assert gh_mcp["connected"] is True
    assert gh_int["connected"] is True


def test_connect_unconfigured_503(patched):
    app = create_app()
    with TestClient(app) as c:
        r = c.post("/mcps/connect", json={"id": "fetch", "args": {}})
    assert r.status_code == 503

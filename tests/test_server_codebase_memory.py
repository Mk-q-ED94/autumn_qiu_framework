"""Tests for the ``/config/codebase-memory`` toggle endpoint.

The endpoint drives the framework-owned layer (``Autumn.start/stop_codebase_memory``
and ``autumn.codebase``), so the Autumn here is a light fake that simulates those
methods' observable effects — no MCP subprocess.
"""
import os
import time

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTUMN_SKIP_INIT", "1")

from autumn.server.app import create_app, _autostart_codebase_memory  # noqa: E402


def _poll(c, predicate, attempts: int = 200):
    """Poll GET status until *predicate(body)* — the bring-up is now async."""
    body = c.get("/config/codebase-memory").json()
    for _ in range(attempts):
        if predicate(body):
            return body
        time.sleep(0.01)
        body = c.get("/config/codebase-memory").json()
    return body


# ── fake framework ───────────────────────────────────────────────────────────────


class _FakeCodebase:
    def __init__(self, repo: str):
        self.repo = repo
        self.indexed = True


class _FakeBehavior:
    def __init__(self):
        self.codebase_memory_enabled = False
        self.codebase_memory_repo = ""


class _FakeConfig:
    def __init__(self):
        self.behavior = _FakeBehavior()


class _FakeAutumn:
    def __init__(self, *, fail_start: bool = False):
        self.config = _FakeConfig()
        self.codebase: _FakeCodebase | None = None
        self._codebase_terr_names: list[str] = []
        self._fail_start = fail_start
        self.stopped = False

    async def start_codebase_memory(self, repo=None):
        if self._fail_start:
            raise RuntimeError("uvx not found")
        target = (repo if repo is not None else self.config.behavior.codebase_memory_repo) or ""
        self.codebase = _FakeCodebase(target.strip())
        self._codebase_terr_names = ["search_graph", "trace_path", "get_architecture"]
        return True

    async def stop_codebase_memory(self):
        self.stopped = True
        self.codebase = None
        self._codebase_terr_names = []

    async def close(self):
        pass


@pytest.fixture
def client_with_autumn():
    app = create_app()
    autumn = _FakeAutumn()
    with TestClient(app) as c:
        app.state.autumn = autumn
        yield c, autumn


# ── status ───────────────────────────────────────────────────────────────────────


def test_status_disabled_by_default(client_with_autumn):
    c, _ = client_with_autumn
    body = c.get("/config/codebase-memory").json()
    assert body == {
        "enabled": False, "connected": False, "starting": False, "indexed": False,
        "repo": "", "tool_count": 0, "error": None,
    }


def test_status_503_without_autumn():
    app = create_app()
    with TestClient(app) as c:
        assert c.get("/config/codebase-memory").status_code == 503


# ── toggle ───────────────────────────────────────────────────────────────────────


def test_enable_starts_layer(client_with_autumn):
    c, autumn = client_with_autumn
    # Enable returns immediately (bring-up is off the request path)...
    body = c.post("/config/codebase-memory", json={"enabled": True}).json()
    assert body["enabled"] is True
    assert autumn.config.behavior.codebase_memory_enabled is True
    # ...and the layer comes up asynchronously; the client polls for it.
    body = _poll(c, lambda b: b["connected"] or b["error"])
    assert body["connected"] is True
    assert body["indexed"] is True
    assert body["tool_count"] == 3
    assert autumn.codebase is not None


def test_disable_stops_layer(client_with_autumn):
    c, autumn = client_with_autumn
    c.post("/config/codebase-memory", json={"enabled": True})
    _poll(c, lambda b: b["connected"] or b["error"])
    body = c.post("/config/codebase-memory", json={"enabled": False}).json()
    assert body["enabled"] is False
    assert body["connected"] is False
    assert autumn.stopped is True
    assert autumn.config.behavior.codebase_memory_enabled is False


def test_enable_with_repo_override(client_with_autumn):
    c, autumn = client_with_autumn
    body = c.post("/config/codebase-memory", json={"enabled": True, "repo": "/srv/app"}).json()
    assert body["repo"] == "/srv/app"
    assert autumn.config.behavior.codebase_memory_repo == "/srv/app"
    _poll(c, lambda b: b["connected"] or b["error"])
    assert autumn.codebase.repo == "/srv/app"


def test_enable_records_start_error_but_keeps_flag():
    app = create_app()
    autumn = _FakeAutumn(fail_start=True)
    with TestClient(app) as c:
        app.state.autumn = autumn
        c.post("/config/codebase-memory", json={"enabled": True})
        # The failure surfaces asynchronously via the status endpoint.
        body = _poll(c, lambda b: b["error"] is not None)
    assert body["enabled"] is True       # intent persists
    assert body["connected"] is False    # but the layer isn't live
    assert body["error"] and "uvx not found" in body["error"]


# ── autostart (headless entry) ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_autostart_when_flag_enabled():
    import asyncio

    app = create_app()
    app.state.integration_lock = asyncio.Lock()
    app.state.codebase_memory_error = None
    app.state.codebase_memory_task = None
    autumn = _FakeAutumn()
    autumn.config.behavior.codebase_memory_enabled = True

    await _autostart_codebase_memory(app, autumn)
    # Autostart is backgrounded now — await the launched task to settle it.
    task = app.state.codebase_memory_task
    assert task is not None
    await task
    assert autumn.codebase is not None
    assert app.state.codebase_memory_error is None


@pytest.mark.asyncio
async def test_autostart_skipped_when_flag_off():
    import asyncio

    app = create_app()
    app.state.integration_lock = asyncio.Lock()
    app.state.codebase_memory_error = None
    autumn = _FakeAutumn()  # flag off

    await _autostart_codebase_memory(app, autumn)
    assert autumn.codebase is None

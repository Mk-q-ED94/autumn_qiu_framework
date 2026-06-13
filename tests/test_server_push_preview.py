"""Tests for GET /memory/4d/status and POST /memory/push/preview."""
import asyncio
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTUMN_SKIP_INIT", "1")

from autumn.server.app import create_app  # noqa: E402
from autumn.core.memory.backends import DictBackend  # noqa: E402
from autumn.core.memory.base import MemoryArea  # noqa: E402
from autumn.core.workspace.wp4 import WP4Mem  # noqa: E402


class _Behavior:
    def __init__(self, mem=False, push=False, mom1=True):
        self.fourd_memory_enabled = mem
        self.fourd_push_on_turn = push
        self.mom1_access_enabled = mom1


class _Config:
    def __init__(self, behavior):
        self.behavior = behavior


def _make_autumn(behavior=None):
    mom1 = MemoryArea("mom1", DictBackend())

    class _Autumn:
        def __init__(self):
            self.mom1 = mom1
            self.wp4 = WP4Mem(None, MemoryArea("wp4", DictBackend()), zones={"mom1": mom1})
            if behavior is not None:
                self.config = _Config(behavior)
        async def close(self): pass

    return _Autumn()


@pytest.fixture
def client_factory():
    created = []

    def make(behavior=None):
        app = create_app()
        autumn = _make_autumn(behavior)
        client = TestClient(app)
        client.__enter__()
        app.state.autumn = autumn
        created.append(client)
        return client, autumn

    yield make
    for c in created:
        c.__exit__(None, None, None)


# ── /memory/4d/status ───────────────────────────────────────────────────────────


def test_status_reports_flags(client_factory):
    client, _ = client_factory(_Behavior(mem=True, push=True, mom1=False))
    body = client.get("/memory/4d/status").json()
    assert body == {
        "fourd_memory_enabled": True,
        "fourd_push_on_turn": True,
        "mom1_access_enabled": False,
    }


def test_status_defaults_when_no_config(client_factory):
    client, _ = client_factory(behavior=None)  # no .config attribute
    body = client.get("/memory/4d/status").json()
    assert body["fourd_memory_enabled"] is False
    assert body["fourd_push_on_turn"] is False
    assert body["mom1_access_enabled"] is True


def test_status_unconfigured_503():
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/memory/4d/status").status_code == 503


# ── /memory/push/preview ────────────────────────────────────────────────────────


def test_push_preview_fires_matching_remind(client_factory):
    client, autumn = client_factory(_Behavior(push=True))
    # A REMIND memory with a cue that the query will match.
    e = asyncio.run(autumn.mom1.append_history("remember to water the plants"))
    asyncio.run(autumn.mom1.annotate(e.id, mode="remind", cues=["plants"]))

    r = client.post("/memory/push/preview", json={"area": "mom1", "query": "about plants today"})
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert len(body["fired"]) == 1
    fired = body["fired"][0]
    assert fired["mode"] == "remind"
    assert fired["cues"] == ["plants"]
    assert fired["score"] > 0
    assert "plants" in body["fragment"].lower()


def test_push_preview_ignores_context_mode(client_factory):
    client, autumn = client_factory(_Behavior())
    # Plain CONTEXT entries are never push candidates.
    asyncio.run(autumn.mom1.append_history("just background info"))
    r = client.post("/memory/push/preview", json={"area": "mom1", "query": "background"})
    body = r.json()
    assert body["fired"] == []
    assert body["enabled"] is False  # push off by default


def test_push_preview_does_not_reinforce(client_factory):
    client, autumn = client_factory(_Behavior())
    e = asyncio.run(autumn.mom1.append_history("a constraint"))
    asyncio.run(autumn.mom1.annotate(e.id, mode="constrain"))

    client.post("/memory/push/preview", json={"area": "mom1", "query": "x"})
    stored = asyncio.run(autumn.mom1.get_history())[-1]
    # Preview must not touch the usage ledger.
    assert stored.use.stats.count == 0


def test_push_preview_explicit_cues(client_factory):
    client, autumn = client_factory(_Behavior())
    e = asyncio.run(autumn.mom1.append_history("deploy rule"))
    asyncio.run(autumn.mom1.annotate(e.id, mode="constrain", cues=["deploy"]))

    # No query words, but explicit cues should still match.
    r = client.post("/memory/push/preview",
                    json={"area": "mom1", "query": "", "cues": ["deploy"]})
    body = r.json()
    assert len(body["fired"]) == 1


def test_push_preview_unconfigured_503():
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/memory/push/preview", json={"area": "mom1", "query": "x"})
    assert r.status_code == 503

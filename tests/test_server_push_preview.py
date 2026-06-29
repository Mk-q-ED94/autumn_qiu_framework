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
    def __init__(self, mem=False, push=False, mom1=True, pull=True):
        self.fourd_memory_enabled = mem
        self.fourd_push_on_turn = push
        self.fourd_pull_on_turn = pull
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
    assert body["fourd_memory_enabled"] is True
    assert body["fourd_push_on_turn"] is True
    assert body["fourd_pull_on_turn"] is True
    assert body["mom1_access_enabled"] is False
    # Per-turn lifecycle flags.
    assert body["fourd_auto_annotate"] is True
    assert body["fourd_auto_consolidate"] is True
    assert body["fourd_auto_evolve"] is False  # default off (opt-in)
    assert body["fourd_auto_extract_facts"] is False  # default off (opt-in)
    assert body["fourd_auto_synthesize_profile"] is False  # default off (opt-in)


def test_status_defaults_when_no_config(client_factory):
    client, _ = client_factory(behavior=None)  # no .config attribute
    body = client.get("/memory/4d/status").json()
    assert body["fourd_memory_enabled"] is False
    assert body["fourd_push_on_turn"] is False
    assert body["fourd_pull_on_turn"] is True
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


# ── POST /memory/4d/config (runtime toggle) ─────────────────────────────────────


class _ConfigurableBehavior(_Behavior):
    pass


def _autumn_with_configure():
    """An Autumn-shaped stub exposing configure_4d over a mutable behavior."""
    behavior = _Behavior(mem=False, push=False, mom1=True)

    class _Autumn:
        def __init__(self):
            self.config = _Config(behavior)
            self.calls = []
        def configure_4d(self, *, memory_enabled=None, push_on_turn=None,
                         pull_on_turn=None, auto_annotate=None,
                         auto_consolidate=None, auto_evolve=None,
                         auto_extract_facts=None, auto_synthesize_profile=None,
                         mom1_access_enabled=None):
            self.calls.append(
                (memory_enabled, push_on_turn, pull_on_turn,
                 auto_annotate, auto_consolidate, auto_evolve,
                 auto_extract_facts, auto_synthesize_profile, mom1_access_enabled)
            )
            if memory_enabled is not None:
                behavior.fourd_memory_enabled = memory_enabled
            if push_on_turn is not None:
                behavior.fourd_push_on_turn = push_on_turn
            if pull_on_turn is not None:
                behavior.fourd_pull_on_turn = pull_on_turn
            if mom1_access_enabled is not None:
                behavior.mom1_access_enabled = mom1_access_enabled
            return {
                "fourd_memory_enabled": behavior.fourd_memory_enabled,
                "fourd_push_on_turn": behavior.fourd_push_on_turn,
                "fourd_pull_on_turn": behavior.fourd_pull_on_turn,
                "fourd_auto_annotate": True,
                "fourd_auto_consolidate": True,
                "fourd_auto_evolve": False,
                "fourd_auto_extract_facts": False,
                "fourd_auto_synthesize_profile": False,
                "mom1_access_enabled": behavior.mom1_access_enabled,
            }
        async def close(self): pass

    return _Autumn()


def test_config_applies_and_returns_state():
    app = create_app()
    autumn = _autumn_with_configure()
    with TestClient(app) as client:
        app.state.autumn = autumn
        r = client.post("/memory/4d/config", json={
            "fourd_memory_enabled": True, "fourd_push_on_turn": True,
        })
        assert r.status_code == 200
        body = r.json()
        assert body["fourd_memory_enabled"] is True
        assert body["fourd_push_on_turn"] is True
        assert body["mom1_access_enabled"] is True  # untouched
        assert autumn.calls == [
            (True, True, None, None, None, None, None, None, None)
        ]


def test_config_partial_update():
    app = create_app()
    autumn = _autumn_with_configure()
    with TestClient(app) as client:
        app.state.autumn = autumn
        r = client.post("/memory/4d/config", json={"mom1_access_enabled": False})
        assert r.json()["mom1_access_enabled"] is False
        assert autumn.calls == [
            (None, None, None, None, None, None, None, None, False)
        ]


def test_config_not_supported_501():
    app = create_app()

    class _Old:
        async def close(self): pass

    with TestClient(app) as client:
        app.state.autumn = _Old()  # no configure_4d
        r = client.post("/memory/4d/config", json={"fourd_push_on_turn": True})
    assert r.status_code == 501


def test_config_unconfigured_503():
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/memory/4d/config", json={"fourd_push_on_turn": True})
    assert r.status_code == 503

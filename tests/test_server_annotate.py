"""Tests for POST /memory/{area}/annotate and /auto-annotate."""
import asyncio
import json
import os

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("AUTUMN_SKIP_INIT", "1")

from autumn.server.app import create_app  # noqa: E402
from autumn.core.memory.backends import DictBackend  # noqa: E402
from autumn.core.memory.base import MemoryArea  # noqa: E402
from autumn.core.memory.dimensions import UseMode  # noqa: E402
from autumn.core.workspace.wp4 import WP4Mem  # noqa: E402


class _MockModel:
    def __init__(self, replies=None):
        self._replies = list(replies or [])

    async def complete(self, messages, **kwargs):
        return self._replies.pop(0) if self._replies else ""


def _make_autumn(api=None):
    mom1 = MemoryArea("mom1", DictBackend())

    class _Autumn:
        def __init__(self):
            self.mom1 = mom1
            self.wp4 = WP4Mem(api, MemoryArea("wp4", DictBackend()), zones={"mom1": mom1})
        async def close(self): pass

    return _Autumn()


@pytest.fixture
def client_factory():
    created = []

    def make(api=None):
        app = create_app()
        autumn = _make_autumn(api)
        client = TestClient(app)
        client.__enter__()
        app.state.autumn = autumn
        created.append(client)
        return client, autumn

    yield make
    for c in created:
        c.__exit__(None, None, None)


# ── annotate (explicit) ─────────────────────────────────────────────────────────


def test_annotate_sets_dimensions(client_factory):
    client, autumn = client_factory()
    entry = asyncio.run(autumn.mom1.append_history("never use prod creds"))

    r = client.post("/memory/mom1/annotate", json={
        "entry_id": entry.id, "mode": "constrain",
        "intent": "safety", "cues": ["prod", "creds"],
    })
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "entry_id": entry.id, "found": True}

    stored = asyncio.run(autumn.mom1.get_history())[-1]
    assert stored.use.mode == UseMode.CONSTRAIN
    assert stored.aim.intent == "safety"
    assert stored.trigger.cues == ["prod", "creds"]


def test_annotate_missing_entry_404(client_factory):
    client, _ = client_factory()
    r = client.post("/memory/mom1/annotate", json={"entry_id": "nope", "mode": "remind"})
    assert r.status_code == 404


def test_annotate_unconfigured_503():
    app = create_app()
    with TestClient(app) as client:
        r = client.post("/memory/mom1/annotate", json={"entry_id": "x"})
    assert r.status_code == 503


# ── auto-annotate (A4-inferred) ─────────────────────────────────────────────────


def test_auto_annotate_runs_inference(client_factory):
    entry_holder = {}

    def setup():
        # api reply must reference the real entry id; capture it first
        client, autumn = client_factory(api=_MockModel())
        e = asyncio.run(autumn.mom1.append_history("db password is hunter2"))
        autumn.wp4.api._replies = [json.dumps([
            {"id": e.id, "mode": "constrain", "intent": "secret", "cues": ["password"]},
        ])]
        entry_holder["id"] = e.id
        return client, autumn

    client, autumn = setup()
    r = client.post("/memory/mom1/auto-annotate", json={"n": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["annotated"] == 1
    assert body["scanned"] == 1

    stored = asyncio.run(autumn.mom1.get_history())[-1]
    assert stored.use.mode == UseMode.CONSTRAIN


def test_auto_annotate_no_model_400(client_factory):
    client, autumn = client_factory(api=None)  # WP4 has no A4 model
    asyncio.run(autumn.mom1.append_history("x"))
    r = client.post("/memory/mom1/auto-annotate", json={})
    assert r.status_code == 400


def test_auto_annotate_default_body(client_factory):
    client, autumn = client_factory(api=_MockModel(["[]"]))
    asyncio.run(autumn.mom1.append_history("x"))
    r = client.post("/memory/mom1/auto-annotate")  # no body → defaults
    assert r.status_code == 200
    assert r.json()["scanned"] == 1

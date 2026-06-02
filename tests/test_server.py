"""Tests for the FastAPI server bridge."""
import json
import os

import pytest

pytest.importorskip("fastapi", reason="fastapi not installed (extras 'server' or 'dev')")

from fastapi.testclient import TestClient  # noqa: E402

# Ensure the lifespan does not try to read .env / call from_env at startup.
os.environ["AUTUMN_SKIP_INIT"] = "1"

from autumn.server.app import create_app  # noqa: E402


# ── test doubles ──────────────────────────────────────────────────────────────


class _MockMemory:
    def __init__(self, history):
        self._history = history

    async def get_history(self):
        return self._history


class _MockAutumn:
    def __init__(self):
        self.mom1 = _MockMemory([{"turn": 1, "input": "hi", "output": "ok"}])
        self.mom2 = _MockMemory([])
        self.mom3 = _MockMemory([])
        self.ended = False

    async def process(self, text: str) -> str:
        return f"processed: {text}"

    async def stream(self, text: str):
        for chunk in ["hello ", "world", " ", text]:
            yield chunk

    async def end_session(self):
        self.ended = True

    async def close(self):
        pass


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def configured_client():
    app = create_app()
    with TestClient(app) as client:
        app.state.autumn = _MockAutumn()
        yield client


@pytest.fixture
def unconfigured_client():
    app = create_app()
    with TestClient(app) as client:
        # lifespan already set autumn = None because AUTUMN_SKIP_INIT=1
        yield client


# ── /health ───────────────────────────────────────────────────────────────────


def test_health_unconfigured(unconfigured_client):
    r = unconfigured_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "configured": False}


def test_health_configured(configured_client):
    r = configured_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "configured": True}


# ── /process ──────────────────────────────────────────────────────────────────


def test_process_returns_output(configured_client):
    r = configured_client.post("/process", json={"input": "hi"})
    assert r.status_code == 200
    assert r.json() == {"output": "processed: hi"}


def test_process_requires_input(configured_client):
    r = configured_client.post("/process", json={})
    assert r.status_code == 422


def test_process_503_when_unconfigured(unconfigured_client):
    r = unconfigured_client.post("/process", json={"input": "hi"})
    assert r.status_code == 503


# ── /stream ───────────────────────────────────────────────────────────────────


def test_stream_yields_chunks_then_done(configured_client):
    with configured_client.stream("GET", "/stream", params={"input": "hi"}) as r:
        assert r.status_code == 200
        chunks = []
        for line in r.iter_lines():
            if line.startswith("data: "):
                chunks.append(line[len("data: "):])

    assert chunks[-1] == "[DONE]"
    decoded = [json.loads(c)["chunk"] for c in chunks[:-1]]
    assert "".join(decoded) == "hello world hi"


def test_stream_503_when_unconfigured(unconfigured_client):
    r = unconfigured_client.get("/stream", params={"input": "hi"})
    assert r.status_code == 503


# ── /memory/{area}/history ────────────────────────────────────────────────────


def test_history_returns_list(configured_client):
    r = configured_client.get("/memory/mom1/history")
    assert r.status_code == 200
    assert r.json() == [{"turn": 1, "input": "hi", "output": "ok"}]


def test_history_unknown_area_404(configured_client):
    r = configured_client.get("/memory/bogus/history")
    assert r.status_code == 404


# ── /session/end ──────────────────────────────────────────────────────────────


def test_session_end(configured_client):
    r = configured_client.post("/session/end")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

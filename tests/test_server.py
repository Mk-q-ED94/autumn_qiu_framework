"""Tests for the FastAPI server bridge."""
import importlib
import json
import os

import pytest

from fastapi.testclient import TestClient  # noqa: E402

# Ensure the lifespan does not try to read .env / call from_env at startup.
os.environ["AUTUMN_SKIP_INIT"] = "1"

from autumn.server.app import create_app  # noqa: E402
from autumn.core.types import InputType, MissionRoute, WorkflowRun, WorkflowStage  # noqa: E402

server_app = importlib.import_module("autumn.server.app")


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
        self.closed = False
        self.process_calls = []
        self.stream_calls = []

    async def process(self, text: str, mission_route=None) -> str:
        self.process_calls.append((text, mission_route))
        return f"processed: {text}"

    async def process_with_trace(self, text: str, mission_route=None):
        self.process_calls.append((text, mission_route))
        route = MissionRoute.CONVERT if mission_route == "convert" else MissionRoute.DIRECT
        return WorkflowRun(
            output=f"processed: {text}",
            input_type=InputType.MISSION,
            route=route,
            stages=[
                WorkflowStage(
                    id="wp3.route",
                    title="A3 路由",
                    detail=f"Mission 路由为 {route.value}",
                    workspace="WP3",
                ),
            ],
        )

    async def stream(self, text: str, mission_route=None):
        self.stream_calls.append((text, mission_route))
        for chunk in ["hello ", "world", " ", text]:
            yield chunk

    async def end_session(self):
        self.ended = True

    async def close(self):
        self.closed = True


class _ConfiguredAutumn(_MockAutumn):
    instances = []

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.__class__.instances.append(self)


class _FakeHTTPResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.request = server_app.httpx.Request("GET", "https://example.test/v1/models")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise server_app.httpx.HTTPStatusError(
                "bad response",
                request=self.request,
                response=self,
            )


class _FakeAsyncClient:
    payload = {"data": [{"id": "z-model"}, {"id": "a-model"}, {"id": "a-model"}]}
    status_code = 200
    requests = []

    def __init__(self, headers=None, timeout=None):
        self.headers = headers or {}
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url):
        self.__class__.requests.append((url, self.headers))
        return _FakeHTTPResponse(self.__class__.payload, self.__class__.status_code)


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


# ── /models ───────────────────────────────────────────────────────────────────


def test_models_returns_sorted_unique_names(unconfigured_client, monkeypatch):
    _FakeAsyncClient.requests = []
    _FakeAsyncClient.payload = {"data": [{"id": "z-model"}, {"id": "a-model"}, {"id": "a-model"}]}
    _FakeAsyncClient.status_code = 200
    monkeypatch.setattr(server_app.httpx, "AsyncClient", _FakeAsyncClient)

    r = unconfigured_client.post(
        "/models",
        json={
            "api_key": "sk-test",
            "base_url": "https://api.openai.com",
            "protocol": "openai",
        },
    )

    assert r.status_code == 200
    assert r.json() == {"models": ["a-model", "z-model"]}
    url, headers = _FakeAsyncClient.requests[-1]
    assert url == "https://api.openai.com/v1/models"
    assert headers["Authorization"] == "Bearer sk-test"


def test_models_supports_anthropic_headers(unconfigured_client, monkeypatch):
    _FakeAsyncClient.requests = []
    _FakeAsyncClient.payload = {"data": [{"id": "claude-test"}]}
    _FakeAsyncClient.status_code = 200
    monkeypatch.setattr(server_app.httpx, "AsyncClient", _FakeAsyncClient)

    r = unconfigured_client.post(
        "/models",
        json={
            "api_key": "anthropic-key",
            "base_url": "https://api.anthropic.com",
            "protocol": "anthropic",
        },
    )

    assert r.status_code == 200
    _, headers = _FakeAsyncClient.requests[-1]
    assert headers["x-api-key"] == "anthropic-key"
    assert headers["anthropic-version"] == "2023-06-01"


def test_models_requires_api_key(unconfigured_client):
    r = unconfigured_client.post(
        "/models",
        json={"api_key": "", "base_url": "https://api.openai.com", "protocol": "openai"},
    )
    assert r.status_code == 400


def test_models_provider_error_returns_502(unconfigured_client, monkeypatch):
    _FakeAsyncClient.requests = []
    _FakeAsyncClient.payload = {"error": "nope"}
    _FakeAsyncClient.status_code = 401
    monkeypatch.setattr(server_app.httpx, "AsyncClient", _FakeAsyncClient)

    r = unconfigured_client.post(
        "/models",
        json={
            "api_key": "bad",
            "base_url": "https://api.openai.com",
            "protocol": "openai",
        },
    )

    assert r.status_code == 502


# ── /config/apply ─────────────────────────────────────────────────────────────


def _config_payload():
    return {
        "a1": {
            "api_key": "k1",
            "base_url": "https://api.openai.com",
            "model": "gpt-a",
            "protocol": "openai",
        },
        "a2": {
            "api_key": "k2",
            "base_url": "https://api.anthropic.com",
            "model": "claude-a",
            "protocol": "anthropic",
        },
        "a3": {
            "api_key": "k3",
            "base_url": "https://api.openai.com",
            "model": "gpt-b",
            "protocol": "openai",
        },
    }


def test_apply_config_builds_autumn_and_closes_old(configured_client, monkeypatch):
    _ConfiguredAutumn.instances = []
    old = configured_client.app.state.autumn
    monkeypatch.setattr(server_app, "Autumn", _ConfiguredAutumn)

    r = configured_client.post("/config/apply", json=_config_payload())

    assert r.status_code == 200
    assert r.json() == {"status": "ok", "configured": True}
    assert old.closed is True
    autumn = configured_client.app.state.autumn
    assert autumn is _ConfiguredAutumn.instances[-1]
    assert autumn.config.a1.model == "gpt-a"
    assert autumn.config.a2.protocol == "anthropic"


def test_apply_config_requires_model(configured_client):
    payload = _config_payload()
    payload["a1"]["model"] = ""

    r = configured_client.post("/config/apply", json=payload)

    assert r.status_code == 400


# ── /process ──────────────────────────────────────────────────────────────────


def test_process_returns_output(configured_client):
    r = configured_client.post("/process", json={"input": "hi"})
    assert r.status_code == 200
    assert r.json() == {"output": "processed: hi"}


def test_process_passes_route_override(configured_client):
    r = configured_client.post("/process", json={"input": "hi", "route": "convert"})
    assert r.status_code == 200
    assert configured_client.app.state.autumn.process_calls[-1] == ("hi", "convert")


def test_process_rejects_invalid_route(configured_client):
    r = configured_client.post("/process", json={"input": "hi", "route": "bogus"})
    assert r.status_code == 422


def test_process_requires_input(configured_client):
    r = configured_client.post("/process", json={})
    assert r.status_code == 422


def test_process_503_when_unconfigured(unconfigured_client):
    r = unconfigured_client.post("/process", json={"input": "hi"})
    assert r.status_code == 503


# ── /trace ────────────────────────────────────────────────────────────────────


def test_trace_returns_workflow_run(configured_client):
    r = configured_client.post("/trace", json={"input": "hi", "route": "convert"})

    assert r.status_code == 200
    payload = r.json()
    assert payload["output"] == "processed: hi"
    assert payload["input_type"] == "mission"
    assert payload["route"] == "convert"
    assert payload["stages"][0]["id"] == "wp3.route"
    assert configured_client.app.state.autumn.process_calls[-1] == ("hi", "convert")


def test_trace_503_when_unconfigured(unconfigured_client):
    r = unconfigured_client.post("/trace", json={"input": "hi"})
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


def test_stream_passes_route_override(configured_client):
    with configured_client.stream("GET", "/stream", params={"input": "hi", "route": "direct"}) as r:
        assert r.status_code == 200
        list(r.iter_lines())

    assert configured_client.app.state.autumn.stream_calls[-1] == ("hi", "direct")


def test_stream_rejects_invalid_route(configured_client):
    r = configured_client.get("/stream", params={"input": "hi", "route": "bogus"})
    assert r.status_code == 422


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

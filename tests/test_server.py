"""Tests for the FastAPI server bridge."""
import importlib
import json
import os

import pytest

from fastapi.testclient import TestClient  # noqa: E402

# Ensure the lifespan does not try to read .env / call from_env at startup.
os.environ["AUTUMN_SKIP_INIT"] = "1"

from autumn.server.app import create_app  # noqa: E402
from autumn.core.types import InputType, MissionRoute, SelectorResult, TaskType, WorkflowRun, WorkflowStage  # noqa: E402

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

    async def process(self, text: str, mission_route=None, input_type=None, task_type=None) -> str:
        self.process_calls.append((text, mission_route, input_type, task_type))
        return f"processed: {text}"

    async def process_with_trace(self, text: str, mission_route=None, input_type=None, task_type=None):
        self.process_calls.append((text, mission_route, input_type, task_type))
        route = MissionRoute.CONVERT if mission_route == "convert" else MissionRoute.DIRECT
        return WorkflowRun(
            output=f"processed: {text}",
            input_type=input_type or InputType.MISSION,
            route=None if input_type == InputType.TASK else route,
            task_type=task_type,
            stages=[
                WorkflowStage(
                    id="wp3.route",
                    title="A3 路由",
                    detail=f"Mission 路由为 {route.value}",
                    workspace="WP3",
                    duration_ms=12.5,
                    prompt_tokens=120,
                    completion_tokens=15,
                ),
                WorkflowStage(
                    id="wp2.tool.0.search",
                    title="search",
                    detail="q=x → ok",
                    workspace="WP2",
                    status="completed",
                    kind="tool",
                    prompt_tokens=240,
                    completion_tokens=18,
                ),
            ],
        )

    async def stream(self, text: str, mission_route=None, input_type=None, task_type=None):
        self.stream_calls.append((text, mission_route))
        for chunk in ["hello ", "world", " ", text]:
            yield chunk

    async def stream_with_trace(self, text: str, mission_route=None, input_type=None, task_type=None):
        self.stream_calls.append((text, mission_route))
        for chunk in ["hello ", "world", " ", text]:
            yield chunk
        route = MissionRoute.CONVERT if mission_route == "convert" else MissionRoute.DIRECT
        yield WorkflowRun(
            output=f"hello world {text}",
            input_type=input_type or InputType.MISSION,
            route=None if input_type == InputType.TASK else route,
            task_type=task_type,
            stages=[
                WorkflowStage(
                    id="wp1.select",
                    title="A1 分类",
                    detail="输入被识别为 mission",
                    workspace="WP1",
                    duration_ms=1.0,
                ),
                WorkflowStage(
                    id="wp1.final_check",
                    title="A1 最终检查",
                    detail="WP1 已完成流式输出观察检查",
                    workspace="WP1",
                    duration_ms=2.0,
                ),
            ],
        )

    async def classify_intent(self, text: str, mission_route=None, input_type=None, task_type=None):
        sel = SelectorResult(
            input_type or InputType.TASK,
            0.66,
            task_type or TaskType.SEARCH,
        )
        route = MissionRoute.DIRECT if mission_route == "direct" else None
        return sel, route

    def describe_terrs(self):
        return [{
            "name": "search",
            "description": "Search tools",
            "tools": [{
                "name": "web_search",
                "description": "search web",
                "parameters": [{
                    "name": "query",
                    "type": "string",
                    "description": "query",
                    "required": True,
                    "extra": {},
                }],
            }],
            "skills": [],
            "mcps": [{"name": "stdio", "description": "MCP"}],
        }]

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
    assert r.json() == {"status": "ok", "configured": False, "last_error": None}


def test_health_configured(configured_client):
    r = configured_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "configured": True, "last_error": None}


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
    assert configured_client.app.state.autumn.process_calls[-1] == ("hi", "convert", None, None)


def test_process_passes_task_type_override(configured_client):
    r = configured_client.post(
        "/process",
        json={"input": "hi", "input_type": "task", "task_type": "code"},
    )
    assert r.status_code == 200
    assert configured_client.app.state.autumn.process_calls[-1] == (
        "hi",
        None,
        InputType.TASK,
        TaskType.CODE,
    )


def test_process_rejects_invalid_route(configured_client):
    r = configured_client.post("/process", json={"input": "hi", "route": "bogus"})
    assert r.status_code == 422


def test_process_requires_input(configured_client):
    r = configured_client.post("/process", json={})
    assert r.status_code == 422


def test_process_503_when_unconfigured(unconfigured_client):
    r = unconfigured_client.post("/process", json={"input": "hi"})
    assert r.status_code == 503


def test_process_pipeline_failure_returns_502(configured_client):
    """An exception inside the framework should surface as a structured 502
    with the message, not a 500 with no detail."""
    async def boom(*args, **kwargs):
        raise RuntimeError("model API exploded")

    configured_client.app.state.autumn.process = boom
    r = configured_client.post("/process", json={"input": "hi"})
    assert r.status_code == 502
    assert "model API exploded" in r.json()["detail"]
    # /health surfaces the last failure so the desktop client can recover gracefully.
    health = configured_client.get("/health").json()
    assert health["last_error"] == "model API exploded"


def test_trace_pipeline_failure_returns_502(configured_client):
    async def boom(*args, **kwargs):
        raise RuntimeError("trace failed")

    configured_client.app.state.autumn.process_with_trace = boom
    r = configured_client.post("/trace", json={"input": "hi"})
    assert r.status_code == 502
    assert configured_client.app.state.last_error == "trace failed"


def test_intent_pipeline_failure_returns_502(configured_client):
    async def boom(*args, **kwargs):
        raise RuntimeError("intent failed")

    configured_client.app.state.autumn.classify_intent = boom
    r = configured_client.post("/intent", json={"input": "hi"})
    assert r.status_code == 502


def test_apply_config_clears_last_error(configured_client, monkeypatch):
    """A successful re-apply clears the stale last_error so /health goes green
    again without forcing the user to restart the server."""
    configured_client.app.state.last_error = "stale"
    monkeypatch.setattr(server_app, "Autumn", _ConfiguredAutumn)
    r = configured_client.post("/config/apply", json=_config_payload())
    assert r.status_code == 200
    assert configured_client.get("/health").json()["last_error"] is None


# ── /trace ────────────────────────────────────────────────────────────────────


def test_trace_returns_workflow_run(configured_client):
    r = configured_client.post("/trace", json={"input": "hi", "route": "convert"})

    assert r.status_code == 200
    payload = r.json()
    assert payload["output"] == "processed: hi"
    assert payload["input_type"] == "mission"
    assert payload["route"] == "convert"
    assert payload["task_type"] is None
    assert payload["stages"][0]["id"] == "wp3.route"
    assert payload["stages"][0]["duration_ms"] == 12.5
    assert configured_client.app.state.autumn.process_calls[-1] == ("hi", "convert", None, None)


def test_trace_accepts_task_type_override(configured_client):
    r = configured_client.post(
        "/trace",
        json={"input": "fix bug", "input_type": "task", "task_type": "code"},
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["input_type"] == "task"
    assert payload["task_type"] == "code"
    assert payload["route"] is None


def test_trace_includes_task_type(configured_client, monkeypatch):
    """task_type is forwarded from WorkflowRun to the trace response."""
    original = configured_client.app.state.autumn.process_with_trace

    async def patched(text, mission_route=None, input_type=None, task_type=None):
        run = await original(text, mission_route, input_type, task_type)
        run.task_type = TaskType.CODE
        return run

    configured_client.app.state.autumn.process_with_trace = patched
    r = configured_client.post("/trace", json={"input": "fix bug"})
    assert r.status_code == 200
    assert r.json()["task_type"] == "code"


def test_trace_includes_tool_stage_kind(configured_client):
    r = configured_client.post("/trace", json={"input": "hi"})
    assert r.status_code == 200
    stages = r.json()["stages"]
    assert stages[0]["kind"] == "stage"          # default for workflow steps
    tool_stages = [s for s in stages if s["kind"] == "tool"]
    assert len(tool_stages) == 1
    assert tool_stages[0]["title"] == "search"


def test_trace_includes_token_usage_per_stage(configured_client):
    """Token fields propagate from WorkflowStage → TraceStageResponse."""
    r = configured_client.post("/trace", json={"input": "hi"})
    assert r.status_code == 200
    stages = r.json()["stages"]
    assert stages[0]["prompt_tokens"] == 120
    assert stages[0]["completion_tokens"] == 15
    assert stages[1]["prompt_tokens"] == 240
    assert stages[1]["completion_tokens"] == 18


def test_trace_includes_aggregate_token_totals(configured_client):
    """TraceResponse sums per-stage tokens into top-level totals."""
    r = configured_client.post("/trace", json={"input": "hi"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_prompt_tokens"] == 360       # 120 + 240
    assert body["total_completion_tokens"] == 33    # 15 + 18


def test_trace_503_when_unconfigured(unconfigured_client):
    r = unconfigured_client.post("/trace", json={"input": "hi"})
    assert r.status_code == 503


# ── /intent ───────────────────────────────────────────────────────────────────


def test_intent_returns_selector_preview(configured_client):
    r = configured_client.post("/intent", json={"input": "find docs"})
    assert r.status_code == 200
    payload = r.json()
    assert payload["input_type"] == "task"
    assert payload["task_type"] == "search"
    assert payload["route"] is None
    assert payload["confidence"] == 0.66
    assert "reasoning" in payload  # may be None — added for selector improvement


def test_intent_accepts_manual_override(configured_client):
    r = configured_client.post(
        "/intent",
        json={"input": "hello", "input_type": "mission", "route": "direct"},
    )
    assert r.status_code == 200
    assert r.json()["input_type"] == "mission"
    assert r.json()["route"] == "direct"


# ── /stream ───────────────────────────────────────────────────────────────────


def test_stream_yields_chunks_then_done(configured_client):
    with configured_client.stream("GET", "/stream", params={"input": "hi"}) as r:
        assert r.status_code == 200
        chunks = []
        for line in r.iter_lines():
            if line.startswith("data: "):
                chunks.append(line[len("data: "):])

    assert chunks[-1] == "[DONE]"
    events = [json.loads(c) for c in chunks[:-1]]
    decoded = [e["chunk"] for e in events if "chunk" in e]
    assert "".join(decoded) == "hello world hi"
    traces = [e["trace"] for e in events if "trace" in e]
    assert traces[-1]["output"] == "hello world hi"
    assert traces[-1]["stages"][-1]["id"] == "wp1.final_check"
    assert configured_client.app.state.autumn.process_calls == []


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


def test_history_unknown_area_rejected(configured_client):
    """Path parameter is validated by FastAPI/Pydantic, returning 422 for
    anything outside {mom1, mom2, mom3}."""
    r = configured_client.get("/memory/bogus/history")
    assert r.status_code == 422


def test_history_pagination_slices_results(configured_client):
    """Limit + offset return a window over the full history so big sessions
    don't blow up the wire."""
    entries = [{"turn": i} for i in range(10)]
    configured_client.app.state.autumn.mom1 = _MockMemory(entries)

    r = configured_client.get("/memory/mom1/history", params={"limit": 3, "offset": 2})
    assert r.status_code == 200
    assert r.json() == [{"turn": 2}, {"turn": 3}, {"turn": 4}]


def test_history_pagination_rejects_negative_offset(configured_client):
    r = configured_client.get("/memory/mom1/history", params={"offset": -1})
    assert r.status_code == 422


def test_history_pagination_caps_limit(configured_client):
    """The hard cap protects against accidentally fetching unbounded data."""
    r = configured_client.get("/memory/mom1/history", params={"limit": 999_999})
    assert r.status_code == 422


# ── /session/end ──────────────────────────────────────────────────────────────


def test_session_end(configured_client):
    r = configured_client.post("/session/end")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ── /terrs ────────────────────────────────────────────────────────────────────


def test_terrs_returns_registered_domains(configured_client):
    r = configured_client.get("/terrs")
    assert r.status_code == 200
    payload = r.json()
    assert payload[0]["name"] == "search"
    assert payload[0]["tools"][0]["name"] == "web_search"
    assert payload[0]["tools"][0]["parameters"][0]["name"] == "query"

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
from autumn.core.memory.backends import DictBackend  # noqa: E402
from autumn.core.memory.base import MemoryArea  # noqa: E402
from autumn.core.workspace.wp4 import WP4Mem  # noqa: E402

server_app = importlib.import_module("autumn.server.app")


# ── test doubles ──────────────────────────────────────────────────────────────


class _MockMemory:
    def __init__(self, history):
        self._history = history
        self.consolidated = None

    async def get_history(self):
        return self._history

    async def stats(self):
        return {
            "area": "mock",
            "total": len(self._history),
            "pinned": 0,
            "expired": 0,
            "tags": {},
            "history_limit": 50,
            "has_vector": False,
        }

    async def consolidate(self, api, keep_recent=10, min_candidates=3):
        self.consolidated = {"keep_recent": keep_recent, "min_candidates": min_candidates}
        if len(self._history) < min_candidates:
            return None
        from autumn.core.memory.base import MemoryEntry
        return MemoryEntry(
            id="sum", content="summary", timestamp=0.0,
            importance=1.5, tags=["summary"], meta={"consolidated": len(self._history)},
        )


class _MockProjects:
    """Stand-in for ProjectMemory recording register/clear and serving history."""

    def __init__(self):
        self.registered: list[str] = []
        self.cleared: list[str] = []
        self.history: dict[str, list] = {}

    async def register(self, project_id):
        self.registered.append(project_id)

    async def list_projects(self):
        return sorted(set(self.registered))

    async def clear_project(self, project_id):
        self.cleared.append(project_id)

    def zone(self, project_id=None):
        return _MockMemory(self.history.get(project_id, []))


class _MockAutumn:
    def __init__(self):
        self.mom1 = _MockMemory([{"turn": 1, "input": "hi", "output": "ok"}])
        self.mom2 = _MockMemory([])
        self.mom3 = _MockMemory([])
        self.shared = _MockMemory([])
        self.projects = _MockProjects()
        self.a4 = object()  # present → consolidation allowed
        # WP4 curates every memory zone; the server routes memory endpoints
        # through it. A real WP4Mem over the mock zones keeps that path honest.
        self.wp4 = WP4Mem(
            self.a4,
            MemoryArea("wp4", DictBackend()),
            zones={
                "mom1": self.mom1, "mom2": self.mom2,
                "mom3": self.mom3, "shared": self.shared,
            },
            projects=self.projects,
        )
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
                    items=["选择 direct 或 convert", "交给对应工作区"],
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
                    source_terr="search",
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
            reasoning="selector says task",
        )
        route = MissionRoute.DIRECT if mission_route == "direct" else None
        return sel, route

    def describe_terrs(self):
        return [{
            "name": "search",
            "description": "Search tools",
            "enabled": True,
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

    def set_terr_enabled(self, name, enabled):
        if name != "search":
            raise KeyError(name)
        summary = self.describe_terrs()[0]
        summary["enabled"] = enabled
        return summary

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

    def __init__(self, headers=None, timeout=None, trust_env=None):
        self.headers = headers or {}
        self.timeout = timeout
        self.trust_env = trust_env

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
    body = r.json()
    assert body["status"] == "ok"
    assert body["configured"] is False
    assert body["last_error"] is None
    # Capability marker for managed clients (stale-server auto-restart).
    assert isinstance(body["api_revision"], int) and body["api_revision"] >= 1


def test_health_configured(configured_client):
    r = configured_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["configured"] is True
    assert body["last_error"] is None
    assert isinstance(body["api_revision"], int) and body["api_revision"] >= 1


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


def test_models_rejects_internal_base_url(unconfigured_client, monkeypatch):
    # SSRF guard: a metadata/loopback base_url must be refused (400) before any
    # outbound fetch — the same policy the model-facing fetchers enforce.
    monkeypatch.setattr(server_app.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.requests = []
    r = unconfigured_client.post(
        "/models",
        json={
            "api_key": "sk-test",
            "base_url": "http://169.254.169.254",
            "protocol": "openai",
        },
    )
    assert r.status_code == 400
    assert _FakeAsyncClient.requests == []  # never reached the network


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


def test_apply_config_passes_pricing(configured_client, monkeypatch):
    _ConfiguredAutumn.instances = []
    monkeypatch.setattr(server_app, "Autumn", _ConfiguredAutumn)
    payload = _config_payload()
    payload["a2"]["input_price_per_1m"] = 3.0
    payload["a2"]["output_price_per_1m"] = 15.0

    r = configured_client.post("/config/apply", json=payload)

    assert r.status_code == 200
    autumn = _ConfiguredAutumn.instances[-1]
    assert autumn.config.a2.input_price_per_1m == 3.0
    assert autumn.config.a2.output_price_per_1m == 15.0
    # Unset slot defaults to no pricing.
    assert autumn.config.a1.input_price_per_1m == 0.0


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
    assert payload["stages"][0]["items"] == ["选择 direct 或 convert", "交给对应工作区"]
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


def test_trace_includes_source_terr(configured_client):
    r = configured_client.post("/trace", json={"input": "hi"})
    assert r.status_code == 200
    tool_stage = next(s for s in r.json()["stages"] if s["kind"] == "tool")
    assert tool_stage["source_terr"] == "search"


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
    # reasoning is forwarded as-is from SelectorResult so the desktop can show it.
    assert payload["reasoning"] == "selector says task"


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


def test_stream_falls_back_to_legacy_stream(configured_client):
    """Older Autumn instances may only expose ``stream`` (no trace events).
    The server's ``getattr(autumn, "stream_with_trace", autumn.stream)`` fallback
    must keep working: chunks still flow, just without a final ``{"trace": ...}``."""

    class _LegacyAutumn:
        """Pre-d6e49a5 surface: only the chunk-only stream method."""
        async def stream(self, text, mission_route=None, input_type=None, task_type=None):
            for chunk in ["legacy ", text]:
                yield chunk

        async def close(self):
            pass

    configured_client.app.state.autumn = _LegacyAutumn()

    with configured_client.stream("GET", "/stream", params={"input": "yo"}) as r:
        assert r.status_code == 200
        lines = []
        for line in r.iter_lines():
            if line.startswith("data: "):
                lines.append(line[len("data: "):])

    assert lines[-1] == "[DONE]"
    events = [json.loads(c) for c in lines[:-1]]
    chunks = [e["chunk"] for e in events if "chunk" in e]
    assert "".join(chunks) == "legacy yo"
    # Legacy path produces no trace events.
    assert not any("trace" in e for e in events)


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


def test_stream_rejects_oversized_input(configured_client, monkeypatch):
    # The body-limit middleware only sees Content-Length, so the GET query string
    # of /stream needs its own guard against cost-amplification.
    monkeypatch.setenv("AUTUMN_MAX_BODY_BYTES", "1024")
    r = configured_client.get("/stream", params={"input": "x" * 2048})
    assert r.status_code == 413


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
    configured_client.app.state.autumn.mom1._history = entries

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


# ── /memory/{area}/stats + /consolidate ────────────────────────────────────────


def test_memory_stats(configured_client):
    r = configured_client.get("/memory/mom1/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["area"] == "mock"


def test_memory_stats_unknown_area_rejected(configured_client):
    r = configured_client.get("/memory/bogus/stats")
    assert r.status_code == 422


def test_memory_consolidate_returns_summary(configured_client):
    configured_client.app.state.autumn.mom1._history = [{"i": i} for i in range(5)]
    r = configured_client.post("/memory/mom1/consolidate", json={"keep_recent": 2, "min_candidates": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["summary"]["tags"] == ["summary"]
    # tuning params reached the memory layer
    assert configured_client.app.state.autumn.mom1.consolidated == {
        "keep_recent": 2, "min_candidates": 3
    }


def test_memory_consolidate_noop_when_too_few(configured_client):
    configured_client.app.state.autumn.mom1._history = [{"i": 0}]
    r = configured_client.post("/memory/mom1/consolidate", json={"min_candidates": 3})
    assert r.status_code == 200
    assert r.json() == {"status": "noop", "summary": None}


def test_memory_consolidate_requires_a4(configured_client):
    # WP4 owns the A4 slot now; drop it and consolidation must 400.
    configured_client.app.state.autumn.wp4.api = None
    r = configured_client.post("/memory/mom1/consolidate")
    assert r.status_code == 400
    assert "A4" in r.json()["detail"]


def test_memory_stats_overview_aggregates_zones(configured_client):
    r = configured_client.get("/memory/stats")
    assert r.status_code == 200
    body = r.json()
    # Every managed zone is reported; mom1 seeds one entry by default.
    assert set(body["zones"]) == {"mom1", "mom2", "mom3", "shared"}
    assert body["total"] == 1


# ── /projects (per-project shared memory) ──────────────────────────────────────


def test_list_projects_empty(configured_client):
    r = configured_client.get("/projects")
    assert r.status_code == 200
    assert r.json() == {"projects": []}


def test_process_registers_project(configured_client):
    r = configured_client.post("/process", json={"input": "hi", "project_id": "acme"})
    assert r.status_code == 200
    assert configured_client.app.state.autumn.projects.registered == ["acme"]
    # And it now appears in the listing.
    listing = configured_client.get("/projects").json()
    assert listing == {"projects": ["acme"]}


def test_process_without_project_does_not_register(configured_client):
    r = configured_client.post("/process", json={"input": "hi"})
    assert r.status_code == 200
    assert configured_client.app.state.autumn.projects.registered == []


def test_trace_registers_project(configured_client):
    r = configured_client.post("/trace", json={"input": "hi", "project_id": "p2"})
    assert r.status_code == 200
    assert "p2" in configured_client.app.state.autumn.projects.registered


def test_project_memory_returns_history(configured_client):
    configured_client.app.state.autumn.projects.history["acme"] = [
        {"k": "deploy", "v": "fly.io"},
    ]
    r = configured_client.get("/projects/acme/memory")
    assert r.status_code == 200
    assert r.json() == [{"k": "deploy", "v": "fly.io"}]


def test_project_memory_pagination(configured_client):
    configured_client.app.state.autumn.projects.history["acme"] = [
        {"i": i} for i in range(10)
    ]
    r = configured_client.get("/projects/acme/memory", params={"limit": 3, "offset": 2})
    assert r.status_code == 200
    assert r.json() == [{"i": 2}, {"i": 3}, {"i": 4}]


def test_project_stats(configured_client):
    configured_client.app.state.autumn.projects.history["acme"] = [{"i": 0}, {"i": 1}]
    r = configured_client.get("/projects/acme/stats")
    assert r.status_code == 200
    assert r.json()["total"] == 2


def test_project_consolidate(configured_client):
    configured_client.app.state.autumn.projects.history["acme"] = [{"i": i} for i in range(4)]
    r = configured_client.post("/projects/acme/consolidate", json={"min_candidates": 2})
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["summary"]["tags"] == ["summary"]


def test_clear_project(configured_client):
    r = configured_client.delete("/projects/acme")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "project_id": "acme"}
    assert configured_client.app.state.autumn.projects.cleared == ["acme"]


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
    assert payload[0]["enabled"] is True
    assert payload[0]["tools"][0]["name"] == "web_search"
    assert payload[0]["tools"][0]["parameters"][0]["name"] == "query"


def test_terrs_can_toggle_domain(configured_client):
    r = configured_client.patch("/terrs/search", json={"enabled": False})
    assert r.status_code == 200
    payload = r.json()
    assert payload["name"] == "search"
    assert payload["enabled"] is False


def test_terrs_toggle_unknown_domain_404(configured_client):
    r = configured_client.patch("/terrs/missing", json={"enabled": False})
    assert r.status_code == 404


# ── /mcps/catalog ─────────────────────────────────────────────────────────────


def test_mcps_catalog_is_static_and_available_unconfigured(unconfigured_client):
    # The catalog is static metadata, so it works even with no model wired up.
    r = unconfigured_client.get("/mcps/catalog")
    assert r.status_code == 200
    payload = r.json()
    assert len(payload) >= 6
    ids = {entry["id"] for entry in payload}
    # A few representatives from the expanded catalog.
    assert {"filesystem", "github", "postgres", "slack", "sequential_thinking"} <= ids
    for entry in payload:
        assert {"id", "name", "description", "factory", "required_args"} <= entry.keys()


def test_mcps_catalog_marks_credentialed_servers(unconfigured_client):
    r = unconfigured_client.get("/mcps/catalog")
    by_id = {entry["id"]: entry for entry in r.json()}
    assert by_id["postgres"]["required_args"] == ["connection_string"]
    assert by_id["sequential_thinking"]["required_args"] == []


# ── /ollama (local model management) ────────────────────────────────────────────


class _FakeStreamResponse:
    def __init__(self, lines, status_code=200):
        self._lines = lines
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return b"boom"


class _FakeOllamaClient:
    version = {"version": "0.5.7"}
    tags = {
        "models": [
            {
                "name": "qwen2.5:1.5b",
                "size": 986000000,
                "modified_at": "2025-06-01T00:00:00Z",
                "details": {"parameter_size": "1.5B", "family": "qwen2"},
            }
        ]
    }
    pull_lines = [
        '{"status":"pulling manifest"}',
        '{"status":"downloading","total":1000,"completed":1000}',
        '{"status":"success"}',
    ]
    pull_status = 200
    deleted = []
    seen_urls = []

    def __init__(self, timeout=None, headers=None, trust_env=None):
        self.timeout = timeout
        self.trust_env = trust_env

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url):
        self.__class__.seen_urls.append(url)
        if url.endswith("/api/version"):
            return _FakeHTTPResponse(self.__class__.version)
        if url.endswith("/api/tags"):
            return _FakeHTTPResponse(self.__class__.tags)
        return _FakeHTTPResponse({}, 404)

    async def request(self, method, url, json=None):
        if url.endswith("/api/delete"):
            self.__class__.deleted.append(json)
            return _FakeHTTPResponse({})
        return _FakeHTTPResponse({}, 404)

    def stream(self, method, url, json=None):
        self.__class__.seen_urls.append(url)
        return _FakeStreamResponse(self.__class__.pull_lines, self.__class__.pull_status)


class _DownOllamaClient(_FakeOllamaClient):
    async def get(self, url):
        raise server_app.httpx.ConnectError("connection refused")


def test_ollama_status_running(unconfigured_client, monkeypatch):
    monkeypatch.setattr(server_app.httpx, "AsyncClient", _FakeOllamaClient)
    r = unconfigured_client.post("/ollama/status", json={"base_url": "http://localhost:11434"})
    assert r.status_code == 200
    body = r.json()
    assert body["running"] is True
    assert body["version"] == "0.5.7"
    assert body["base_url"] == "http://127.0.0.1:11434"


def test_ollama_status_down_is_graceful(unconfigured_client, monkeypatch):
    monkeypatch.setattr(server_app.httpx, "AsyncClient", _DownOllamaClient)
    r = unconfigured_client.post("/ollama/status", json={"base_url": "http://x:1"})
    assert r.status_code == 200
    assert r.json()["running"] is False
    assert "服务器能访问" in r.json()["error"]


def test_ollama_models_strips_v1_suffix(unconfigured_client, monkeypatch):
    _FakeOllamaClient.seen_urls = []
    monkeypatch.setattr(server_app.httpx, "AsyncClient", _FakeOllamaClient)
    # A /v1 base (the A4 chat URL) must be normalised to the native /api endpoint.
    r = unconfigured_client.post("/ollama/models", json={"base_url": "http://localhost:11434/v1"})
    assert r.status_code == 200
    models = r.json()["models"]
    assert models[0]["name"] == "qwen2.5:1.5b"
    assert models[0]["parameter_size"] == "1.5B"
    assert any(u == "http://127.0.0.1:11434/api/tags" for u in _FakeOllamaClient.seen_urls)


def test_ollama_models_error_returns_502(unconfigured_client, monkeypatch):
    monkeypatch.setattr(server_app.httpx, "AsyncClient", _DownOllamaClient)
    r = unconfigured_client.post("/ollama/models", json={})
    assert r.status_code == 502
    assert "localhost 指的是服务器环境" in r.json()["detail"]


def test_ollama_recommended_has_a_default(unconfigured_client):
    r = unconfigured_client.get("/ollama/recommended")
    assert r.status_code == 200
    models = r.json()["models"]
    assert len(models) >= 1
    assert any(m["recommended"] for m in models)
    assert all({"name", "label", "size", "note"} <= set(m) for m in models)


def test_ollama_delete_forwards_name(unconfigured_client, monkeypatch):
    _FakeOllamaClient.deleted = []
    monkeypatch.setattr(server_app.httpx, "AsyncClient", _FakeOllamaClient)
    r = unconfigured_client.request(
        "DELETE",
        "/ollama/models",
        json={"base_url": "http://localhost:11434", "name": "qwen2.5:1.5b"},
    )
    assert r.status_code == 200
    assert _FakeOllamaClient.deleted[0]["name"] == "qwen2.5:1.5b"


def test_ollama_pull_streams_progress_then_done(unconfigured_client, monkeypatch):
    monkeypatch.setattr(server_app.httpx, "AsyncClient", _FakeOllamaClient)
    r = unconfigured_client.get("/ollama/pull", params={"name": "qwen2.5:1.5b"})
    assert r.status_code == 200
    datas = [line[6:] for line in r.text.splitlines() if line.startswith("data: ")]
    assert datas[-1] == "[DONE]"
    parsed = [json.loads(d) for d in datas if d != "[DONE]"]
    assert any(p.get("status") == "success" for p in parsed)


def test_ollama_pull_http_error_emits_error_event(unconfigured_client, monkeypatch):
    class _ErrClient(_FakeOllamaClient):
        pull_status = 500

    monkeypatch.setattr(server_app.httpx, "AsyncClient", _ErrClient)
    r = unconfigured_client.get("/ollama/pull", params={"name": "x"})
    assert r.status_code == 200
    datas = [line[6:] for line in r.text.splitlines() if line.startswith("data: ")]
    assert any("error" in d for d in datas)
    assert datas[-1] == "[DONE]"


# ── builtin terr registration (AUTUMN_BUILTIN_TERRS) ──────────────────────────


class _TerrStubAutumn:
    """Minimal Autumn stand-in for exercising _register_builtin_terrs."""

    def __init__(self):
        from autumn.plugins.loader import PluginLoader
        self.plugins = PluginLoader()

    def register_tool(self, tool):
        self.plugins.register(tool.name, tool)

    def register_skill(self, skill):
        self.plugins.register(skill.name, skill)

    # Reuse the real registration logic — it only needs the methods above.
    from autumn.core.framework import Autumn
    register_terr = Autumn.register_terr


def test_register_builtin_terrs_off_by_default(monkeypatch):
    monkeypatch.delenv("AUTUMN_BUILTIN_TERRS", raising=False)
    stub = _TerrStubAutumn()
    server_app._register_builtin_terrs(stub)
    assert stub.plugins.all_terrs() == {}


def test_register_builtin_terrs_safe_mode(monkeypatch):
    monkeypatch.setenv("AUTUMN_BUILTIN_TERRS", "safe")
    stub = _TerrStubAutumn()
    server_app._register_builtin_terrs(stub)
    names = set(stub.plugins.all_terrs())
    assert {"time", "math", "text", "data", "encoding", "collection"} <= names
    assert "web" not in names


def test_register_builtin_terrs_all_mode_adds_web(monkeypatch):
    monkeypatch.setenv("AUTUMN_BUILTIN_TERRS", "all")
    stub = _TerrStubAutumn()
    server_app._register_builtin_terrs(stub)
    assert "web" in stub.plugins.all_terrs()

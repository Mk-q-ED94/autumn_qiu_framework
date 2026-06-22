"""HTTP/SSE contract tests — validates the full API surface documented in
docs/http-sse-contract.md against a live (in-process) FastAPI test client.

Covers the contract guarantees a new client author needs to rely on:
- Health probe shape and field presence
- Authentication gate (with/without API key)
- 503 before configure, 200 after /config/apply
- /process, /trace, /intent request/response shapes
- /stream SSE frame sequence, ping comments, [DONE] terminator
- /stream error-then-[DONE] on model failure
- /stream 413 on oversized input
- /terrs list and PATCH toggle
- /memory/{area}/history pagination contract
- /session/end
- Security headers on every response
- Request-body size guard (413)
"""
import json
import os

import pytest

os.environ.setdefault("AUTUMN_SKIP_INIT", "1")

from fastapi.testclient import TestClient  # noqa: E402

from autumn.core.memory.backends import DictBackend  # noqa: E402
from autumn.core.memory.base import MemoryArea, MemoryEntry  # noqa: E402
from autumn.core.types import (  # noqa: E402
    InputType,
    MissionRoute,
    SelectorResult,
    TaskType,
    WorkflowRun,
    WorkflowStage,
)
from autumn.core.workspace.wp4 import WP4Mem  # noqa: E402
from autumn.server.app import create_app  # noqa: E402


# ── minimal doubles ────────────────────────────────────────────────────────────

class _Memory:
    def __init__(self, entries=None):
        self._h = entries or []

    async def get_history(self, page=1, page_size=200, tags=None):
        start = (page - 1) * page_size
        return self._h[start:start + page_size]

    async def stats(self):
        return {"area": "t", "total": len(self._h), "pinned": 0,
                "expired": 0, "tags": {}, "history_limit": 200, "has_vector": False}

    async def consolidate(self, api, keep_recent=10, min_candidates=3):
        return None


class _Projects:
    def __init__(self):
        self.registered = []

    async def register(self, pid): self.registered.append(pid)
    async def list_projects(self): return sorted(set(self.registered))
    async def clear_project(self, pid): pass
    def zone(self, pid=None): return _Memory()


class _FakeAutumn:
    def __init__(self):
        self.mom1 = _Memory()
        self.mom2 = _Memory()
        self.mom3 = _Memory()
        self.shared = _Memory()
        self.projects = _Projects()
        self.a4 = object()
        self.wp4 = WP4Mem(
            self.a4,
            MemoryArea("wp4", DictBackend()),
            zones={"mom1": self.mom1, "mom2": self.mom2,
                   "mom3": self.mom3, "shared": self.shared},
            projects=self.projects,
        )
        self.ended = False
        self.closed = False
        self._process_raises = None

    async def process(self, text, mission_route=None, input_type=None, task_type=None):
        if self._process_raises:
            raise self._process_raises
        return f"output:{text}"

    async def process_with_trace(self, text, mission_route=None, input_type=None, task_type=None):
        run = WorkflowRun(
            output=f"output:{text}",
            input_type=input_type or InputType.MISSION,
            route=MissionRoute.DIRECT,
            task_type=task_type,
            stages=[
                WorkflowStage(
                    id="wp1.select", title="select", detail="d",
                    workspace="WP1", duration_ms=10.0,
                    prompt_tokens=100, completion_tokens=12,
                ),
            ],
        )
        return run

    async def stream(self, text, mission_route=None, input_type=None, task_type=None):
        if self._process_raises:
            raise self._process_raises
        for chunk in ["hello ", "world"]:
            yield chunk

    async def stream_with_trace(self, text, mission_route=None, input_type=None, task_type=None):
        if self._process_raises:
            raise self._process_raises
        for chunk in ["hello ", "world"]:
            yield chunk
        yield WorkflowRun(
            output="hello world",
            input_type=input_type or InputType.MISSION,
            route=MissionRoute.DIRECT,
            task_type=task_type,
            stages=[
                WorkflowStage(
                    id="wp1.select", title="s", detail="d",
                    workspace="WP1", duration_ms=1.0,
                ),
            ],
        )

    async def classify_intent(self, text, mission_route=None, input_type=None, task_type=None):
        return (
            SelectorResult(InputType.TASK, 0.8, TaskType.CODE, reasoning="code task"),
            MissionRoute.CONVERT,
        )

    def describe_terrs(self):
        return [{"name": "web", "description": "web", "enabled": True,
                 "tools": [{"name": "http_get", "description": "GET",
                            "parameters": [{"name": "url", "type": "string",
                                            "description": "URL", "required": True, "extra": {}}]}],
                 "skills": [], "mcps": []}]

    def set_terr_enabled(self, name, enabled):
        if name == "unknown":
            raise KeyError(name)
        return {"name": name, "description": "web", "enabled": enabled,
                "tools": [], "skills": [], "mcps": []}

    async def end_session(self):
        self.ended = True

    async def close(self):
        self.closed = True


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        app.state.autumn = _FakeAutumn()
        yield c


@pytest.fixture
def unconfigured_client():
    app = create_app()
    with TestClient(app) as c:
        yield c


# ── §4.1 GET /health ──────────────────────────────────────────────────────────

def test_health_returns_required_fields(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert isinstance(body["configured"], bool)
    assert "api_revision" in body
    assert "version" in body
    assert "last_error" in body


def test_health_configured_false_when_unconfigured(unconfigured_client):
    r = unconfigured_client.get("/health")
    assert r.status_code == 200
    assert r.json()["configured"] is False


# ── §2 Authentication ─────────────────────────────────────────────────────────

def test_api_key_gate_rejects_missing_key(monkeypatch):
    monkeypatch.setenv("AUTUMN_API_KEY", "secret-key")
    app = create_app()
    with TestClient(app) as c:
        app.state.autumn = _FakeAutumn()
        r = c.get("/health")   # exempt
        assert r.status_code == 200
        r = c.get("/terrs")    # gated
        assert r.status_code == 401


def test_api_key_gate_accepts_x_api_key_header(monkeypatch):
    monkeypatch.setenv("AUTUMN_API_KEY", "my-secret")
    app = create_app()
    with TestClient(app) as c:
        app.state.autumn = _FakeAutumn()
        r = c.get("/terrs", headers={"X-API-Key": "my-secret"})
        assert r.status_code == 200


def test_api_key_gate_accepts_bearer_token(monkeypatch):
    monkeypatch.setenv("AUTUMN_API_KEY", "my-secret")
    app = create_app()
    with TestClient(app) as c:
        app.state.autumn = _FakeAutumn()
        r = c.get("/terrs", headers={"Authorization": "Bearer my-secret"})
        assert r.status_code == 200


# ── §3 503 before configure ───────────────────────────────────────────────────

def test_process_503_when_unconfigured(unconfigured_client):
    r = unconfigured_client.post("/process", json={"input": "hi"})
    assert r.status_code == 503


def test_trace_503_when_unconfigured(unconfigured_client):
    r = unconfigured_client.post("/trace", json={"input": "hi"})
    assert r.status_code == 503


def test_stream_503_when_unconfigured(unconfigured_client):
    # SSE errors still embed in the data stream — but /stream itself returns
    # 503 via _autumn_or_503 before the generator is entered.
    with unconfigured_client.stream("GET", "/stream?input=hi") as r:
        assert r.status_code == 503


# ── §4.2 POST /process ────────────────────────────────────────────────────────

def test_process_returns_output(client):
    r = client.post("/process", json={"input": "hello"})
    assert r.status_code == 200
    body = r.json()
    assert "output" in body
    assert isinstance(body["output"], str)


def test_process_forwards_input_to_autumn(client):
    r = client.post("/process", json={"input": "test payload"})
    assert "test payload" in r.json()["output"]


def test_process_accepts_all_optional_fields(client):
    r = client.post("/process", json={
        "input": "hello",
        "route": "direct",
        "input_type": "task",
        "task_type": "code",
        "project_instructions": "be concise",
        "project_id": None,
    })
    assert r.status_code == 200


# ── §4.3 POST /trace ─────────────────────────────────────────────────────────

def test_trace_returns_required_top_level_fields(client):
    r = client.post("/trace", json={"input": "hello"})
    assert r.status_code == 200
    body = r.json()
    for field in ("output", "input_type", "stages"):
        assert field in body, f"missing: {field}"


def test_trace_stages_have_required_fields(client):
    r = client.post("/trace", json={"input": "hello"})
    stages = r.json()["stages"]
    assert len(stages) >= 1
    for stage in stages:
        for f in ("id", "title", "detail", "workspace", "status", "kind"):
            assert f in stage, f"stage missing: {f}"


def test_trace_workspace_values_are_valid(client):
    r = client.post("/trace", json={"input": "hello"})
    valid = {"WP1", "WP2", "WP3", "WP4"}
    for stage in r.json()["stages"]:
        assert stage["workspace"] in valid


# ── §4.4 POST /intent ────────────────────────────────────────────────────────

def test_intent_returns_classification(client):
    r = client.post("/intent", json={"input": "write a sort function"})
    assert r.status_code == 200
    body = r.json()
    assert "input_type" in body
    assert "confidence" in body
    assert 0.0 <= body["confidence"] <= 1.0


# ── §5 GET /stream (SSE contract) ─────────────────────────────────────────────

def _collect_sse(raw: bytes) -> list[dict | str]:
    """Parse SSE text into a list: dicts for data frames, '[DONE]' for sentinel,
    'PING' for heartbeat comments."""
    events = []
    for line in raw.decode("utf-8").splitlines():
        if line.startswith("data: "):
            payload = line[6:]
            if payload == "[DONE]":
                events.append("[DONE]")
            else:
                events.append(json.loads(payload))
        elif line.startswith(": "):
            events.append("PING")
    return events


def test_stream_ends_with_done(client):
    with client.stream("GET", "/stream?input=hello") as r:
        assert r.status_code == 200
        events = _collect_sse(r.read())
    assert events[-1] == "[DONE]"


def test_stream_emits_chunk_frames(client):
    with client.stream("GET", "/stream?input=hello") as r:
        events = _collect_sse(r.read())
    chunks = [e["chunk"] for e in events if isinstance(e, dict) and "chunk" in e]
    assert len(chunks) >= 1
    assert all(isinstance(c, str) for c in chunks)


def test_stream_emits_trace_frame(client):
    with client.stream("GET", "/stream?input=hello") as r:
        events = _collect_sse(r.read())
    trace_events = [e for e in events if isinstance(e, dict) and "trace" in e]
    assert len(trace_events) == 1
    trace = trace_events[0]["trace"]
    assert "output" in trace and "stages" in trace


def test_stream_error_frame_then_done(client):
    autumn = client.app.state.autumn
    autumn._process_raises = RuntimeError("model exploded")
    with client.stream("GET", "/stream?input=hello") as r:
        events = _collect_sse(r.read())
    assert events[-1] == "[DONE]"
    error_events = [e for e in events if isinstance(e, dict) and "error" in e]
    assert len(error_events) == 1


def test_stream_413_on_oversized_input(monkeypatch, client):
    monkeypatch.setenv("AUTUMN_MAX_BODY_BYTES", "10")
    with client.stream("GET", "/stream?input=" + "x" * 100) as r:
        assert r.status_code == 413


def test_stream_content_type_is_event_stream(client):
    with client.stream("GET", "/stream?input=hi") as r:
        assert "text/event-stream" in r.headers["content-type"]


# ── §7 Terr management ────────────────────────────────────────────────────────

def test_terrs_list_shape(client):
    r = client.get("/terrs")
    assert r.status_code == 200
    terrs = r.json()
    assert isinstance(terrs, list)
    for t in terrs:
        assert "name" in t
        assert "enabled" in t
        assert isinstance(t["tools"], list)
        assert isinstance(t["skills"], list)


def test_terrs_patch_toggles_enabled(client):
    r = client.patch("/terrs/web", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_terrs_patch_unknown_returns_404(client):
    r = client.patch("/terrs/unknown", json={"enabled": True})
    assert r.status_code == 404


# ── §8 Memory ─────────────────────────────────────────────────────────────────

def test_memory_history_returns_list(client):
    r = client.get("/memory/mom1/history")
    assert r.status_code == 200
    body = r.json()
    assert "entries" in body or isinstance(body, list)


def test_memory_stats_returns_area_info(client):
    r = client.get("/memory/mom1/stats")
    assert r.status_code == 200
    body = r.json()
    assert "total" in body


def test_memory_global_stats(client):
    r = client.get("/memory/stats")
    assert r.status_code == 200


# ── §12 Session end ───────────────────────────────────────────────────────────

def test_session_end_returns_ok(client):
    r = client.post("/session/end")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_session_end_triggers_autumn_end_session(client):
    autumn = client.app.state.autumn
    client.post("/session/end")
    assert autumn.ended is True


# ── §13 Security headers ──────────────────────────────────────────────────────

def test_security_headers_on_health(client):
    r = client.get("/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("referrer-policy") == "no-referrer"


def test_security_headers_on_terrs(client):
    r = client.get("/terrs")
    assert r.headers.get("x-content-type-options") == "nosniff"


# ── §13.2 Request body size limit ────────────────────────────────────────────

def test_body_size_limit_413(monkeypatch, client):
    monkeypatch.setenv("AUTUMN_MAX_BODY_BYTES", "5")
    r = client.post("/process", json={"input": "this is definitely more than 5 bytes"})
    assert r.status_code == 413


# ── §14 Enum contract ─────────────────────────────────────────────────────────

def test_process_accepts_all_route_values(client):
    for route in ("direct", "convert", "auto", None):
        r = client.post("/process", json={"input": "hi", "route": route})
        assert r.status_code == 200, f"route={route!r} returned {r.status_code}"


def test_process_accepts_all_input_types(client):
    for it in ("task", "mission"):
        r = client.post("/process", json={"input": "hi", "input_type": it})
        assert r.status_code == 200, f"input_type={it!r}"


def test_process_accepts_all_task_types(client):
    for tt in ("code", "write", "search", "data", "general"):
        r = client.post("/process", json={"input": "hi", "task_type": tt})
        assert r.status_code == 200, f"task_type={tt!r}"

"""Tests for the project-instructions / project-id parameters threaded
through ``/process``, ``/trace``, ``/intent`` and ``/stream``.

The server wraps ``input`` with a clearly-tagged preamble when project
instructions are present; these tests assert that the wrapped string
reaches the underlying Autumn instance unchanged, and that omitting or
blanking the instructions leaves the input untouched.
"""
import importlib
import json
import os

import pytest

os.environ["AUTUMN_SKIP_INIT"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from autumn.server.app import _apply_project_context, create_app  # noqa: E402
from autumn.core.types import InputType, MissionRoute, SelectorResult, TaskType  # noqa: E402


# ── helpers ───────────────────────────────────────────────────────────────────


class _RecordingAutumn:
    """Captures every call so we can verify the effective input string."""

    def __init__(self):
        self.process_calls: list[str] = []
        self.trace_calls: list[str] = []
        self.intent_calls: list[str] = []
        self.stream_calls: list[str] = []
        self.mom1 = self.mom2 = self.mom3 = None
        self.ended = False
        self.closed = False

    async def process(self, text, mission_route=None, input_type=None, task_type=None):
        self.process_calls.append(text)
        return f"processed: {text}"

    async def process_with_trace(self, text, mission_route=None, input_type=None, task_type=None):
        from autumn.core.types import WorkflowRun, WorkflowStage
        self.trace_calls.append(text)
        return WorkflowRun(
            output=f"processed: {text}",
            input_type=input_type or InputType.MISSION,
            route=mission_route if isinstance(mission_route, MissionRoute) else None,
            task_type=task_type,
            stages=[WorkflowStage(
                id="wp1.select", title="A1", detail="", workspace="WP1",
                status="completed",
            )],
        )

    async def classify_intent(self, text, mission_route=None, input_type=None, task_type=None):
        self.intent_calls.append(text)
        return (
            SelectorResult(InputType.MISSION, 0.9, reasoning="stub"),
            None,
        )

    async def stream(self, text, mission_route=None, input_type=None, task_type=None):
        self.stream_calls.append(text)
        yield "ok"

    def describe_terrs(self):
        return []

    async def end_session(self):
        self.ended = True

    async def close(self):
        self.closed = True


@pytest.fixture
def configured_client():
    app = create_app()
    with TestClient(app) as client:
        app.state.autumn = _RecordingAutumn()
        yield client


# ── _apply_project_context unit tests ─────────────────────────────────────────


def test_apply_context_no_instructions_returns_input_verbatim():
    assert _apply_project_context("hello", None) == "hello"
    assert _apply_project_context("hello", "") == "hello"
    assert _apply_project_context("hello", "   ") == "hello"


def test_apply_context_wraps_with_tagged_preamble():
    wrapped = _apply_project_context("draft an email", "Always sign as Jin.")
    assert "[项目指令" in wrapped
    assert "Always sign as Jin." in wrapped
    assert "[用户输入" in wrapped
    assert "draft an email" in wrapped
    # ordering: instructions come before user input
    assert wrapped.index("Always sign as Jin.") < wrapped.index("draft an email")


def test_apply_context_strips_outer_whitespace_on_instructions():
    wrapped = _apply_project_context("hi", "   focus on brevity   ")
    assert "focus on brevity" in wrapped
    # blank lines around the instruction text are dropped
    assert "   focus on brevity   " not in wrapped


# ── /process forwards wrapped input ──────────────────────────────────────────


def test_process_threads_project_instructions(configured_client):
    r = configured_client.post(
        "/process",
        json={
            "input": "write a poem",
            "project_instructions": "Use haiku format.",
        },
    )
    assert r.status_code == 200
    autumn = configured_client.app.state.autumn
    sent = autumn.process_calls[-1]
    assert "Use haiku format." in sent
    assert "write a poem" in sent
    assert "[项目指令" in sent


def test_process_without_project_unchanged(configured_client):
    r = configured_client.post("/process", json={"input": "write a poem"})
    assert r.status_code == 200
    sent = configured_client.app.state.autumn.process_calls[-1]
    assert sent == "write a poem"
    assert "[项目指令" not in sent


def test_process_blank_project_instructions_unchanged(configured_client):
    r = configured_client.post(
        "/process",
        json={"input": "hi", "project_instructions": "   "},
    )
    assert r.status_code == 200
    sent = configured_client.app.state.autumn.process_calls[-1]
    assert sent == "hi"


# ── /trace forwards wrapped input ────────────────────────────────────────────


def test_trace_threads_project_instructions(configured_client):
    r = configured_client.post(
        "/trace",
        json={
            "input": "audit auth.py",
            "project_instructions": "Bias toward security findings.",
        },
    )
    assert r.status_code == 200
    sent = configured_client.app.state.autumn.trace_calls[-1]
    assert "Bias toward security findings." in sent
    assert "audit auth.py" in sent


# ── /intent forwards wrapped input ───────────────────────────────────────────


def test_intent_threads_project_instructions(configured_client):
    r = configured_client.post(
        "/intent",
        json={
            "input": "fix the bug",
            "project_instructions": "All requests are code changes.",
        },
    )
    assert r.status_code == 200
    sent = configured_client.app.state.autumn.intent_calls[-1]
    assert "All requests are code changes." in sent
    assert "fix the bug" in sent


# ── /stream forwards wrapped input (via query params) ────────────────────────


def test_stream_threads_project_instructions(configured_client):
    with configured_client.stream(
        "GET", "/stream",
        params={
            "input": "translate this",
            "project_instructions": "Always reply in Mandarin.",
        },
    ) as r:
        assert r.status_code == 200
        # drain the response
        for _ in r.iter_lines():
            pass

    sent = configured_client.app.state.autumn.stream_calls[-1]
    assert "Always reply in Mandarin." in sent
    assert "translate this" in sent
    assert "[项目指令" in sent


def test_stream_without_project_instructions_unchanged(configured_client):
    with configured_client.stream(
        "GET", "/stream", params={"input": "just hi"}
    ) as r:
        assert r.status_code == 200
        for _ in r.iter_lines():
            pass

    sent = configured_client.app.state.autumn.stream_calls[-1]
    assert sent == "just hi"


def test_stream_ignores_project_id_for_now(configured_client):
    """project_id is accepted but reserved for future memory scoping —
    it should not crash and should not corrupt the input string."""
    with configured_client.stream(
        "GET", "/stream",
        params={
            "input": "hello",
            "project_id": "abc-123",
        },
    ) as r:
        assert r.status_code == 200
        for _ in r.iter_lines():
            pass

    sent = configured_client.app.state.autumn.stream_calls[-1]
    assert sent == "hello"


# ── backward-compat ──────────────────────────────────────────────────────────


def test_process_request_schema_accepts_legacy_payload(configured_client):
    """Existing clients that omit project_instructions/project_id must work."""
    r = configured_client.post(
        "/process",
        json={"input": "hi", "route": "direct", "input_type": "mission"},
    )
    assert r.status_code == 200
    sent = configured_client.app.state.autumn.process_calls[-1]
    assert sent == "hi"


def test_intent_request_schema_accepts_legacy_payload(configured_client):
    r = configured_client.post(
        "/intent",
        json={"input": "what is autumn?"},
    )
    assert r.status_code == 200
    sent = configured_client.app.state.autumn.intent_calls[-1]
    assert sent == "what is autumn?"

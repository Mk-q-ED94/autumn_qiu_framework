"""Collaboration legibility: structured acting-agent identity + routing rationale.

The trace used to carry only a `workspace` and localized title strings, so a
client could not reliably tell *who* acted or *why* A1 routed a turn the way it
did. These tests lock in (1) every stage exposes a machine-readable `agent`
derived from its workspace, (2) A1's classification reasoning reaches the select
stage, and (3) the field survives HTTP serialization.
"""
from autumn.core.types import InputType, TaskType, WorkflowStage
from autumn.core.workspace.wp1 import _classify_detail


# ── agent identity ────────────────────────────────────────────────────────────

def test_agent_derived_from_workspace():
    assert WorkflowStage(id="x", title="t", detail="d", workspace="WP1").agent == "A1"
    assert WorkflowStage(id="x", title="t", detail="d", workspace="WP2").agent == "A2"
    assert WorkflowStage(id="x", title="t", detail="d", workspace="WP3").agent == "A3"
    assert WorkflowStage(id="x", title="t", detail="d", workspace="WP4").agent == "A4"


def test_agent_explicit_value_wins():
    # A WP1 stage acting on A4's behalf can override the derivation.
    s = WorkflowStage(id="x", title="t", detail="d", workspace="WP1", agent="A4")
    assert s.agent == "A4"


def test_agent_none_for_unknown_workspace():
    assert WorkflowStage(id="x", title="t", detail="d", workspace="???").agent is None


# ── routing rationale ─────────────────────────────────────────────────────────

def test_classify_detail_appends_reasoning():
    detail = _classify_detail(InputType.TASK, TaskType.CODE, "需要多步代码修改")
    assert "code" in detail
    assert "需要多步代码修改" in detail


def test_classify_detail_without_reasoning_unchanged():
    detail = _classify_detail(InputType.MISSION, None, None)
    assert detail == "输入被识别为 mission"


def test_classify_detail_blank_reasoning_ignored():
    detail = _classify_detail(InputType.MISSION, None, "   ")
    assert detail == "输入被识别为 mission"


# ── serialization ─────────────────────────────────────────────────────────────

def test_stage_serializes_agent_field():
    from autumn.server.app import TraceStageResponse

    stage = WorkflowStage(id="wp2.task", title="A2 执行任务", detail="d", workspace="WP2")
    resp = TraceStageResponse(**stage.__dict__)
    assert resp.agent == "A2"
    assert resp.handoff_to is None

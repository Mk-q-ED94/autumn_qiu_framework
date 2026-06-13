"""Tests for the 4D *producer* side: explicit + A4-inferred annotation.

``MemoryArea.annotate`` merges 4D dimensions onto an existing entry in place
(preserving the usage ledger). ``WP4Mem.annotate_recent`` uses A4 to infer those
dimensions for un-annotated recent entries. Together they feed the activation
engine the discriminating signal it previously had to do without.
"""
import json

from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea
from autumn.core.memory.dimensions import UseMode
from autumn.core.workspace.wp4 import WP4Mem, _is_unannotated


class MockModel:
    def __init__(self, replies=None):
        self._replies = list(replies or [])
        self.calls = []

    async def complete(self, messages, **kwargs):
        self.calls.append(messages)
        return self._replies.pop(0) if self._replies else ""


def _wp4(api=None) -> WP4Mem:
    return WP4Mem(
        api,
        MemoryArea("wp4", DictBackend()),
        zones={"mom1": MemoryArea("mom1", DictBackend())},
    )


# ── MemoryArea.annotate ─────────────────────────────────────────────────────────

async def test_annotate_sets_mode_intent_scope_cues():
    area = MemoryArea("t", DictBackend())
    e = await area.append_history("never use prod creds in tests")

    ok = await area.annotate(
        e.id, mode="constrain", intent="safety rule",
        scope=["testing"], cues=["prod", "creds"],
    )
    assert ok is True

    stored = (await area.get_history())[-1]
    assert stored.use.mode == UseMode.CONSTRAIN
    assert stored.aim.intent == "safety rule"
    assert stored.aim.scope == ["testing"]
    assert stored.trigger.cues == ["prod", "creds"]


async def test_annotate_preserves_usage_stats():
    area = MemoryArea("t", DictBackend())
    e = await area.append_history("x")
    await area.reinforce([e.id], reward=0.5)  # count=1
    await area.reinforce([e.id], reward=0.2)  # count=2

    await area.annotate(e.id, mode="remind")
    stored = (await area.get_history())[-1]
    assert stored.use.mode == UseMode.REMIND
    assert stored.use.stats.count == 2  # ledger preserved across annotation


async def test_annotate_unknown_mode_keeps_current():
    area = MemoryArea("t", DictBackend())
    e = await area.append_history("x")
    await area.annotate(e.id, mode="not-a-mode", intent="kept")
    stored = (await area.get_history())[-1]
    assert stored.use.mode == UseMode.CONTEXT  # unchanged
    assert stored.aim.intent == "kept"        # other fields still applied


async def test_annotate_missing_entry_returns_false():
    area = MemoryArea("t", DictBackend())
    assert await area.annotate("nope", mode="remind") is False


async def test_annotate_only_applies_provided_fields():
    area = MemoryArea("t", DictBackend())
    e = await area.append_history("x")
    await area.annotate(e.id, intent="first", scope=["a"])
    await area.annotate(e.id, cues=["b"])  # intent/scope must survive
    stored = (await area.get_history())[-1]
    assert stored.aim.intent == "first"
    assert stored.aim.scope == ["a"]
    assert stored.trigger.cues == ["b"]


# ── consolidate summaries carry SUMMARIZE mode ──────────────────────────────────

async def test_consolidate_summary_is_summarize_mode():
    area = MemoryArea("t", DictBackend())
    for i in range(5):
        await area.append_history(f"entry {i}")
    summary = await area.consolidate(MockModel(["digest"]), keep_recent=0, min_candidates=3)
    assert summary is not None
    assert summary.use.mode == UseMode.SUMMARIZE


# ── _is_unannotated helper ──────────────────────────────────────────────────────

async def test_is_unannotated_true_for_bare_entry():
    area = MemoryArea("t", DictBackend())
    e = await area.append_history("bare")
    assert _is_unannotated(e) is True


async def test_is_unannotated_false_after_annotation():
    area = MemoryArea("t", DictBackend())
    e = await area.append_history("x")
    await area.annotate(e.id, mode="constrain")
    stored = (await area.get_history())[-1]
    assert _is_unannotated(stored) is False


# ── WP4Mem.annotate_recent ──────────────────────────────────────────────────────

async def test_annotate_recent_applies_a4_inference():
    wp4 = _wp4(MockModel([json.dumps([
        {"id": "PLACEHOLDER", "mode": "constrain", "intent": "rule",
         "scope": ["db"], "cues": ["password"]},
    ])]))
    zone = wp4._resolve("mom1")
    e = await zone.append_history("the db password is hunter2")

    # Patch the reply id to the real entry id (test can't know it beforehand).
    wp4.api._replies = [json.dumps([
        {"id": e.id, "mode": "constrain", "intent": "rule",
         "scope": ["db"], "cues": ["password"]},
    ])]

    result = await wp4.annotate_recent("mom1", n=10)
    assert result == {"annotated": 1, "scanned": 1}

    stored = (await zone.get_history())[-1]
    assert stored.use.mode == UseMode.CONSTRAIN
    assert stored.aim.intent == "rule"
    assert stored.trigger.cues == ["password"]


async def test_annotate_recent_skips_already_annotated():
    wp4 = _wp4(MockModel([json.dumps([])]))
    zone = wp4._resolve("mom1")
    e = await zone.append_history("x")
    await zone.annotate(e.id, mode="remind")  # already annotated

    result = await wp4.annotate_recent("mom1", n=10)
    assert result == {"annotated": 0, "scanned": 0}
    # A4 should not even be consulted when nothing is un-annotated.
    assert wp4.api.calls == []


async def test_annotate_recent_handles_bad_json():
    wp4 = _wp4(MockModel(["not json at all"]))
    zone = wp4._resolve("mom1")
    await zone.append_history("x")
    result = await wp4.annotate_recent("mom1", n=10)
    assert result == {"annotated": 0, "scanned": 1}  # scanned but none applied


async def test_annotate_recent_no_model_raises():
    wp4 = _wp4(None)
    import pytest
    with pytest.raises(RuntimeError, match="annotation"):
        await wp4.annotate_recent("mom1")


async def test_annotate_recent_logs_to_audit():
    wp4 = _wp4(MockModel([json.dumps([])]))
    zone = wp4._resolve("mom1")
    await zone.append_history("x")
    await wp4.annotate_recent("mom1", n=10)
    log = await wp4.memory.get_history()
    assert any("annotate" in e.tags for e in log)

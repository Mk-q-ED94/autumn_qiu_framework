"""Tests for the agent-facing request_mom1_access skill.

The skill (autumn.core.memory.skills.make_mom1_access_skill) is the trigger
that turns the Mom1 access broker from plumbing into something a WP2/WP3 agent
can actually call. These tests drive the skill handler end-to-end against a
real broker + in-memory zones, plus the no-broker fallback.
"""
from __future__ import annotations

import json

import pytest

from autumn.core.memory.access import Mom1AccessBroker, Mom1Requester
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea
from autumn.core.memory.skills import make_mom1_access_skill


class MockModel:
    def __init__(self, replies: list[str] | None = None):
        self._replies = list(replies or [])
        self.calls: list[list] = []

    async def complete(self, messages, max_tokens: int = 1000) -> str:
        self.calls.append(messages)
        return self._replies.pop(0) if self._replies else ""


class FakeZone(Mom1Requester):
    """Minimal Mom1Requester standing in for Mom2/Mom3."""

    def __init__(self, name: str):
        self.name = name
        self._mom1_broker = None


def make_area(name: str) -> MemoryArea:
    return MemoryArea(name, DictBackend())


def approve(scope=None, redact=False) -> str:
    return json.dumps(
        {"approved": True, "reason": "ok", "allowed_scope": scope or [], "redact": redact},
    )


# ── schema ────────────────────────────────────────────────────────────────────

def test_skill_shape():
    skill = make_mom1_access_skill(FakeZone("mom2"))
    assert skill.name == "request_mom1_access"
    names = [p.name for p in skill.parameters]
    assert names == ["query", "reason", "scope", "max_entries"]
    # query/reason required; scope/max_entries optional
    required = {p.name: p.required for p in skill.parameters}
    assert required["query"] and required["reason"]
    assert not required["scope"] and not required["max_entries"]


# ── no broker attached ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skill_without_broker_returns_unavailable():
    skill = make_mom1_access_skill(FakeZone("mom2"))
    out = await skill.execute(query="db host", reason="connect")
    assert "unavailable" in out.lower()


# ── granted ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skill_granted_returns_mediated_content():
    mom1 = make_area("mom1")
    await mom1.append_history({"content": "prod db is at db.internal"})

    a1 = MockModel([approve()])
    a4 = MockModel(["The production database is db.internal."])
    broker = Mom1AccessBroker(mom1=mom1, adjudicator=a1, mediator=a4)

    zone = FakeZone("mom2")
    zone.attach_mom1_broker(broker)
    skill = make_mom1_access_skill(zone)

    out = await skill.execute(query="db host", reason="task must connect")
    assert "granted" in out
    assert "db.internal" in out
    assert "via a4" in out


# ── denied ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skill_denied_returns_reason():
    mom1 = make_area("mom1")
    await mom1.append_history({"content": "classified"})

    a1 = MockModel([json.dumps({"approved": False, "reason": "not need-to-know"})])
    broker = Mom1AccessBroker(mom1=mom1, adjudicator=a1)

    zone = FakeZone("mom3")
    zone.attach_mom1_broker(broker)
    skill = make_mom1_access_skill(zone)

    out = await skill.execute(query="secrets", reason="curiosity")
    assert "denied" in out
    assert "need-to-know" in out


# ── disabled broker ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skill_disabled_broker_denies():
    mom1 = make_area("mom1")
    await mom1.append_history({"content": "anything"})
    broker = Mom1AccessBroker(mom1=mom1, adjudicator=MockModel([approve()]), enabled=False)

    zone = FakeZone("mom2")
    zone.attach_mom1_broker(broker)
    skill = make_mom1_access_skill(zone)

    out = await skill.execute(query="x", reason="y")
    assert "denied" in out


# ── scope + max_entries parsing ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_skill_parses_scope_csv_and_caps_entries():
    mom1 = make_area("mom1")
    await mom1.append_history({"content": "alpha"})
    await mom1.append_history({"content": "beta"})
    history = await mom1.get_history()
    id1 = history[-2].id

    a1 = MockModel([approve(scope=[id1])])
    broker = Mom1AccessBroker(mom1=mom1, adjudicator=a1, mediator=None)

    zone = FakeZone("mom2")
    zone.attach_mom1_broker(broker)
    skill = make_mom1_access_skill(zone)

    # scope passed as comma-separated; max_entries as a string the handler coerces
    out = await skill.execute(
        query="alpha", reason="need alpha", scope=f" {id1} , ", max_entries="3",
    )
    assert "granted" in out
    assert "1 entry" in out  # singular, exactly one entry in scope


@pytest.mark.asyncio
async def test_skill_bad_max_entries_falls_back_to_default():
    mom1 = make_area("mom1")
    await mom1.append_history({"content": "fact"})
    a1 = MockModel([approve()])
    broker = Mom1AccessBroker(mom1=mom1, adjudicator=a1, mediator=None)

    zone = FakeZone("mom2")
    zone.attach_mom1_broker(broker)
    skill = make_mom1_access_skill(zone)

    out = await skill.execute(query="fact", reason="need it", max_entries="not-a-number")
    assert "granted" in out  # did not raise on bad input

"""Unit tests for the Mom1 access-broker (autumn.core.memory.access).

The broker is a multi-actor pipeline:
  1. Gather — pull candidate Mom1 entries
  2. Adjudicate — A1 decides allow/deny and may narrow scope
  3. Mediate — A4 synthesises a restricted answer (or fallback when A4 absent)
  4. Audit — record the decision in an audit log

These tests cover each leg in isolation and the full happy/sad paths.
They use in-memory MemoryArea instances and mock model interfaces so they
run without any live API calls.
"""
from __future__ import annotations

import json
import pytest

from autumn.core.memory.access import (
    AccessDecision,
    AccessGrant,
    AccessRequest,
    Mom1AccessBroker,
    Mom1Requester,
    _extract_json,
)
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea


# ── helpers ───────────────────────────────────────────────────────────────────

def make_area(name: str) -> MemoryArea:
    return MemoryArea(name, DictBackend())


class MockModel:
    """Controlled model stub; returns a pre-set response on each call."""

    def __init__(self, replies: list[str] | None = None):
        self._replies = list(replies or [])
        self.calls: list[list] = []

    async def complete(self, messages, max_tokens: int = 1000) -> str:
        self.calls.append(messages)
        if self._replies:
            return self._replies.pop(0)
        return ""


async def _seed(area: MemoryArea, *texts: str) -> list[str]:
    """Append entries to an area; return their ids."""
    ids = []
    for text in texts:
        entry = await area.append_history({"content": text})
        ids.append(entry["id"] if isinstance(entry, dict) else "")
    # fall back: read back from history
    history = await area.get_history()
    return [e.id for e in history[-len(texts):]]


def make_broker(
    mom1: MemoryArea,
    a1: MockModel | None = None,
    a4: MockModel | None = None,
    audit: MemoryArea | None = None,
    enabled: bool = True,
) -> Mom1AccessBroker:
    return Mom1AccessBroker(
        mom1=mom1,
        adjudicator=a1,
        mediator=a4,
        audit=audit,
        enabled=enabled,
    )


# ── _extract_json ─────────────────────────────────────────────────────────────

def test_extract_json_plain():
    raw = '{"approved": true, "reason": "ok", "allowed_scope": [], "redact": false}'
    assert json.loads(_extract_json(raw)) == {
        "approved": True, "reason": "ok", "allowed_scope": [], "redact": False,
    }


def test_extract_json_fenced():
    raw = '```json\n{"approved": false, "reason": "no"}\n```'
    assert json.loads(_extract_json(raw))["approved"] is False


def test_extract_json_fenced_no_lang():
    raw = '```\n{"approved": true}\n```'
    assert json.loads(_extract_json(raw))["approved"] is True


# ── disabled channel ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_broker_disabled_denies_without_consulting_a1():
    mom1 = make_area("mom1")
    a1 = MockModel([json.dumps({"approved": True, "reason": "yes"})])
    broker = make_broker(mom1, a1=a1, enabled=False)

    grant = await broker.request("mom2", "secret", "need it")

    assert not grant.approved
    assert "disabled" in grant.decision.reason.lower()
    assert a1.calls == []  # A1 was never consulted


# ── bad requester ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_broker_rejects_unknown_requester():
    broker = make_broker(make_area("mom1"))
    with pytest.raises(ValueError, match="Only"):
        await broker.request("mom9", "query", "reason")


# ── no A1 configured ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_adjudicator_denies():
    mom1 = make_area("mom1")
    await mom1.append_history({"content": "secret fact"})
    broker = make_broker(mom1, a1=None)

    grant = await broker.request("mom2", "fact", "need it")

    assert not grant.approved


# ── no candidates ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_mom1_denies_without_calling_a1():
    mom1 = make_area("mom1")
    a1 = MockModel([json.dumps({"approved": True, "reason": "yes"})])
    broker = make_broker(mom1, a1=a1)

    grant = await broker.request("mom2", "anything", "reason")

    assert not grant.approved
    assert a1.calls == []


# ── adjudication ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a1_approves_with_full_scope():
    mom1 = make_area("mom1")
    await mom1.append_history({"content": "the database host is prod.example.com"})

    verdict = json.dumps({"approved": True, "reason": "relevant", "allowed_scope": [], "redact": False})
    a1 = MockModel([verdict])
    broker = make_broker(mom1, a1=a1)

    grant = await broker.request("mom2", "database host", "need to connect")

    assert grant.approved
    assert grant.entries  # got entries back


@pytest.mark.asyncio
async def test_a1_denies():
    mom1 = make_area("mom1")
    await mom1.append_history({"content": "classified info"})

    verdict = json.dumps({"approved": False, "reason": "not relevant"})
    a1 = MockModel([verdict])
    broker = make_broker(mom1, a1=a1)

    grant = await broker.request("mom3", "classified", "i want it")

    assert not grant.approved
    assert grant.content is None
    assert grant.entries == []


@pytest.mark.asyncio
async def test_a1_unparseable_verdict_denies():
    mom1 = make_area("mom1")
    await mom1.append_history({"content": "some entry"})

    a1 = MockModel(["not json at all"])
    broker = make_broker(mom1, a1=a1)

    grant = await broker.request("mom2", "query", "reason")
    assert not grant.approved


# ── mediation ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approved_returns_a4_synthesis():
    mom1 = make_area("mom1")
    await mom1.append_history({"content": "prod host: db.internal"})

    verdict = json.dumps({"approved": True, "reason": "ok", "allowed_scope": [], "redact": False})
    a1 = MockModel([verdict])
    a4 = MockModel(["The production database is at db.internal."])
    broker = make_broker(mom1, a1=a1, a4=a4)

    grant = await broker.request("mom2", "db host", "need to connect")

    assert grant.approved
    assert "db.internal" in grant.content
    assert grant.mediated_by == "a4"


@pytest.mark.asyncio
async def test_fallback_when_no_a4():
    mom1 = make_area("mom1")
    await mom1.append_history({"content": "fact number one"})

    verdict = json.dumps({"approved": True, "reason": "ok", "allowed_scope": [], "redact": False})
    a1 = MockModel([verdict])
    broker = make_broker(mom1, a1=a1, a4=None)

    grant = await broker.request("mom2", "fact", "need it")

    assert grant.approved
    assert grant.content
    assert grant.mediated_by == "fallback"


@pytest.mark.asyncio
async def test_redact_without_a4_returns_metadata_only():
    mom1 = make_area("mom1")
    await mom1.append_history({"content": "password=s3cr3t"})

    verdict = json.dumps({"approved": True, "reason": "yes", "allowed_scope": [], "redact": True})
    a1 = MockModel([verdict])
    broker = make_broker(mom1, a1=a1, a4=None)

    grant = await broker.request("mom2", "password", "need credential")

    # Fallback + redact → id/tag lines only, no raw content
    assert grant.approved
    assert "password" not in (grant.content or "")
    assert "[id=" in (grant.content or "")


# ── scope narrowing ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scope_restriction_limits_entries():
    mom1 = make_area("mom1")
    # Seed two entries; we'll allow only one by scope
    await mom1.append_history({"content": "alpha datum"})
    await mom1.append_history({"content": "beta datum"})

    # Get their ids
    history = await mom1.get_history()
    id1, id2 = history[-2].id, history[-1].id

    verdict = json.dumps({
        "approved": True, "reason": "scoped", "allowed_scope": [id1], "redact": False,
    })
    a1 = MockModel([verdict])
    broker = make_broker(mom1, a1=a1, a4=None)

    grant = await broker.request("mom2", "alpha", "need alpha only")

    assert grant.approved
    assert all(e.id == id1 for e in grant.entries)
    assert id2 not in [e.id for e in grant.entries]


# ── audit log ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_log_records_grant():
    mom1 = make_area("mom1")
    audit = make_area("audit")
    await mom1.append_history({"content": "some fact"})

    verdict = json.dumps({"approved": True, "reason": "ok", "allowed_scope": [], "redact": False})
    a1 = MockModel([verdict])
    broker = make_broker(mom1, a1=a1, audit=audit)

    await broker.request("mom2", "fact", "need it")

    history = await audit.get_history()
    assert len(history) == 1
    assert history[0].tags  # tagged audit entry


@pytest.mark.asyncio
async def test_audit_log_records_denial():
    mom1 = make_area("mom1")
    audit = make_area("audit")
    await mom1.append_history({"content": "classified"})

    verdict = json.dumps({"approved": False, "reason": "denied"})
    a1 = MockModel([verdict])
    broker = make_broker(mom1, a1=a1, audit=audit)

    await broker.request("mom3", "classified", "i want it")

    history = await audit.get_history()
    assert len(history) == 1


# ── Mom1Requester mixin ───────────────────────────────────────────────────────

class FakeZone(Mom1Requester):
    def __init__(self, name: str):
        self.name = name
        self._mom1_broker = None


@pytest.mark.asyncio
async def test_requester_no_broker_raises():
    zone = FakeZone("mom2")
    assert not zone.can_request_mom1
    with pytest.raises(RuntimeError, match="broker is not configured"):
        await zone.request_mom1("q", "r")


@pytest.mark.asyncio
async def test_requester_can_request_after_attach():
    mom1 = make_area("mom1")
    await mom1.append_history({"content": "answer"})

    verdict = json.dumps({"approved": True, "reason": "ok", "allowed_scope": [], "redact": False})
    a1 = MockModel([verdict])
    broker = make_broker(mom1, a1=a1)

    zone = FakeZone("mom2")
    zone.attach_mom1_broker(broker)

    assert zone.can_request_mom1
    grant = await zone.request_mom1("question", "reason")
    assert grant.approved

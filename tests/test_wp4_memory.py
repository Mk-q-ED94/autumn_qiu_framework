"""Tests for WP4 — the memory-management workspace.

WP4 owns the A4 slot and curates every memory zone: recall, remember,
consolidate, forget, pin and stats, plus an audit log of its own actions.
"""
import pytest

from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea
from autumn.core.memory.project import ProjectMemory, project_context
from autumn.core.memory.shared import SharedZone
from autumn.core.workspace.wp4 import WP4Mem


# ── doubles ───────────────────────────────────────────────────────────────────

class _StubAPI:
    """Records prompts and returns a canned completion."""

    def __init__(self, reply: str = "digest"):
        self.reply = reply
        self.calls: list[list] = []

    async def complete(self, messages, **kwargs):
        self.calls.append(messages)
        return self.reply


def _wp4(api=None, projects=None) -> WP4Mem:
    backend = DictBackend()
    shared = SharedZone(backend)
    return WP4Mem(
        api,
        MemoryArea("wp4", backend),
        zones={
            "mom1": MemoryArea("mom1", backend),
            "mom2": MemoryArea("mom2", backend),
            "mom3": MemoryArea("mom3", backend),
            "shared": shared,
        },
        projects=projects,
    )


# ── model availability + zone resolution ──────────────────────────────────────

def test_has_model_reflects_api():
    assert _wp4(api=None).has_model is False
    assert _wp4(api=_StubAPI()).has_model is True


def test_zone_names_includes_project_when_configured():
    wp4 = _wp4(projects=ProjectMemory(DictBackend()))
    assert set(wp4.zone_names()) == {"mom1", "mom2", "mom3", "shared", "project"}


def test_zone_names_excludes_project_when_absent():
    assert "project" not in _wp4().zone_names()


def test_resolve_unknown_area_raises():
    with pytest.raises(ValueError, match="Unknown memory area"):
        _wp4()._resolve("bogus")


def test_resolve_project_without_manager_raises():
    with pytest.raises(ValueError, match="Project memory is not configured"):
        _wp4()._resolve("project")


async def test_resolve_project_uses_context_active_zone():
    pm = ProjectMemory(DictBackend())
    wp4 = _wp4(projects=pm)
    with project_context("acme"):
        assert wp4._resolve("project").project_id == "acme"


# ── recall / remember ──────────────────────────────────────────────────────────

async def test_remember_then_recall_roundtrip():
    wp4 = _wp4()
    await wp4.remember("target", "fly.io", area="shared")
    entries = await wp4.recall("target", area="shared")
    assert entries and entries[0].content == "fly.io"


async def test_remember_logs_to_audit():
    wp4 = _wp4()
    await wp4.remember("k", "v")
    log = await wp4.audit_log()
    assert any(e.content.get("action") == "remember" for e in log)


async def test_remember_routes_to_named_zone():
    wp4 = _wp4()
    await wp4.remember("k", "in-mom2", area="mom2")
    assert await wp4._resolve("mom2").get("k") == "in-mom2"
    assert await wp4._resolve("shared").get("k") is None


# ── skills ─────────────────────────────────────────────────────────────────────

def test_skills_returns_named_skills():
    names = {s.name for s in _wp4().skills("shared")}
    assert names == {"recall", "remember", "list_recent", "pin_memory", "annotate_memory"}


async def test_skills_bound_to_requested_zone():
    wp4 = _wp4()
    skills = {s.name: s for s in wp4.skills("mom1")}
    await skills["remember"].execute(key="k", value="v")
    assert await wp4._resolve("mom1").get("k") == "v"


def test_project_skills_require_manager():
    with pytest.raises(ValueError, match="Project memory is not configured"):
        _wp4().skills("project")


async def test_project_skills_resolve_active_project():
    pm = ProjectMemory(DictBackend())
    wp4 = _wp4(projects=pm)
    skills = {s.name: s for s in wp4.skills("project")}
    with project_context("alpha"):
        await skills["remember"].execute(key="env", value="prod")
    assert await pm.zone("alpha").get("env") == "prod"


# ── consolidate ────────────────────────────────────────────────────────────────

async def test_consolidate_requires_model():
    with pytest.raises(RuntimeError, match="A4 model slot"):
        await _wp4(api=None).consolidate("shared")


async def test_consolidate_summarises_and_audits():
    api = _StubAPI("summary text")
    wp4 = _wp4(api=api)
    for i in range(5):
        await wp4._resolve("shared").append_history({"i": i})
    summary = await wp4.consolidate("shared", keep_recent=1, min_candidates=2)
    assert summary is not None and summary.content == "summary text"
    assert api.calls  # A4 was invoked
    log = await wp4.audit_log()
    assert any(e.content.get("action") == "consolidate" for e in log)


async def test_consolidate_all_sweeps_every_zone():
    api = _StubAPI("z")
    wp4 = _wp4(api=api)
    for name in ("mom1", "mom2", "mom3", "shared"):
        for i in range(4):
            await wp4._resolve(name).append_history({"i": i})
    results = await wp4.consolidate_all(keep_recent=1, min_candidates=2)
    assert set(results) == {"mom1", "mom2", "mom3", "shared"}
    assert all(v is not None for v in results.values())


# ── forget ─────────────────────────────────────────────────────────────────────

async def test_forget_removes_and_audits():
    wp4 = _wp4()
    await wp4._resolve("shared").append_history("a", tags=["temp"])
    await wp4._resolve("shared").append_history("b")
    removed = await wp4.forget("shared", tags=["temp"])
    assert removed == 1
    log = await wp4.audit_log()
    assert any(e.content.get("action") == "forget" for e in log)


async def test_forget_nothing_skips_audit():
    wp4 = _wp4()
    await wp4._resolve("shared").append_history("a")
    removed = await wp4.forget("shared", tags=["absent"])
    assert removed == 0
    assert await wp4.audit_log() == []


# ── pin / unpin ────────────────────────────────────────────────────────────────

async def test_pin_and_unpin():
    wp4 = _wp4()
    entry = await wp4._resolve("shared").append_history("keep me")
    assert await wp4.pin(entry.id, area="shared") is True
    pinned = (await wp4._resolve("shared").get_history())[0]
    assert pinned.is_pinned
    assert await wp4.unpin(entry.id, area="shared") is True


# ── stats ──────────────────────────────────────────────────────────────────────

async def test_stats_single_area():
    wp4 = _wp4()
    await wp4._resolve("mom1").append_history("a", tags=["t"])
    stats = await wp4.stats("mom1")
    assert stats["area"] == "mom1"
    assert stats["total"] == 1
    assert stats["tags"] == {"t": 1}


async def test_stats_overview_aggregates_all_zones():
    wp4 = _wp4()
    await wp4._resolve("mom1").append_history("a")
    await wp4._resolve("shared").append_history("b")
    overview = await wp4.stats()
    assert set(overview["zones"]) == {"mom1", "mom2", "mom3", "shared"}
    assert overview["total"] == 2
    assert "shared" in overview["areas"]


# ── process (WorkspaceBase compliance) ─────────────────────────────────────────

async def test_process_synthesises_with_model():
    api = _StubAPI("the deploy target is fly.io")
    wp4 = _wp4(api=api)
    await wp4.remember("target", "fly.io", area="shared")
    answer = await wp4.process("target")
    assert answer == "the deploy target is fly.io"
    assert api.calls


async def test_process_without_model_returns_snippets():
    wp4 = _wp4(api=None)
    await wp4.remember("target", "fly.io", area="shared")
    answer = await wp4.process("target")
    assert "fly.io" in answer


async def test_process_empty_memory():
    answer = await _wp4(api=_StubAPI()).process("nothing-here")
    assert "no memory found" in answer


# ── extract_facts / evolve / profile (P2-A, P3-A, P3-B) ─────────────────────────

async def test_extract_facts_requires_model():
    with pytest.raises(RuntimeError, match="A4 model slot"):
        await _wp4(api=None).extract_facts("shared")


async def test_extract_facts_creates_and_audits():
    wp4 = _wp4(api=_StubAPI('["Jin prefers dark mode"]'))
    await wp4._resolve("shared").append_history("Jin likes dark mode a lot")
    facts = await wp4.extract_facts("shared")
    assert facts and facts[0].content == "Jin prefers dark mode"
    log = await wp4.audit_log()
    assert any(e.content.get("action") == "extract_facts" for e in log)


async def test_evolve_requires_model():
    with pytest.raises(RuntimeError, match="A4 model slot"):
        await _wp4(api=None).evolve("shared")


async def test_evolve_distils_and_audits():
    wp4 = _wp4(api=_StubAPI("Always use a read replica for prod reads."))
    zone = wp4._resolve("shared")
    ids = []
    for t in ("used replica once", "used replica again"):
        e = await zone.append_history(t)
        await zone.annotate(e.id, intent="db_access")
        ids.append(e.id)
    await zone.reinforce(ids)
    await zone.reinforce(ids)
    skills = await wp4.evolve("shared", min_count=2, min_cluster=2)
    assert skills and skills[0].aim.intent == "db_access"
    log = await wp4.audit_log()
    assert any(e.content.get("action") == "evolve" for e in log)


async def test_synthesize_profile_requires_model():
    with pytest.raises(RuntimeError, match="A4 model slot"):
        await _wp4(api=None).synthesize_profile("shared")


async def test_profile_synthesise_get_and_audit():
    wp4 = _wp4(api=_StubAPI("Prefers terse answers."))
    await wp4._resolve("shared").append_history("user asked for shorter replies")
    updated = await wp4.synthesize_profile("shared", scope="jin")
    assert updated == "Prefers terse answers."
    assert await wp4.get_profile("shared", scope="jin") == "Prefers terse answers."
    log = await wp4.audit_log()
    assert any(e.content.get("action") == "synthesize_profile" for e in log)


async def test_get_profile_without_model_ok():
    # Reading a profile is mechanical — no A4 needed.
    wp4 = _wp4(api=None)
    assert await wp4.get_profile("shared", scope="nobody") is None

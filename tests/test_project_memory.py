"""Tests for per-project shared memory zones."""
import pytest

from autumn.core.memory.backends import DictBackend
from autumn.core.memory.project import (
    ProjectMemory,
    ProjectZone,
    _sanitize,
    get_current_project,
    project_context,
    reset_current_project,
    set_current_project,
)
from autumn.core.memory.skills import make_project_memory_skills


# ── _sanitize ─────────────────────────────────────────────────────────────────

def test_sanitize_keeps_safe_ids():
    assert _sanitize("acme-app_1.0") == "acme-app_1.0"


def test_sanitize_replaces_unsafe_runs():
    assert _sanitize("a/b c:d") == "a_b_c_d"


def test_sanitize_empty_becomes_default():
    assert _sanitize("") == "default"
    assert _sanitize("   ") == "default"


# ── ProjectZone ───────────────────────────────────────────────────────────────

async def test_project_zone_namespaced():
    zone = ProjectZone("acme", DictBackend())
    assert zone.name == "project:acme"
    assert zone.project_id == "acme"


async def test_project_zones_isolate_over_one_backend():
    backend = DictBackend()
    a = ProjectZone("a", backend)
    b = ProjectZone("b", backend)
    await a.set("key", "value-a")
    await b.set("key", "value-b")
    assert await a.get("key") == "value-a"
    assert await b.get("key") == "value-b"


# ── contextvar helpers ──────────────────────────────────────────────────────────

def test_context_helpers_default_none():
    assert get_current_project() is None


def test_set_and_reset_current_project():
    token = set_current_project("p1")
    try:
        assert get_current_project() == "p1"
    finally:
        reset_current_project(token)
    assert get_current_project() is None


def test_project_context_restores_prior():
    with project_context("outer"):
        assert get_current_project() == "outer"
        with project_context("inner"):
            assert get_current_project() == "inner"
        assert get_current_project() == "outer"
    assert get_current_project() is None


# ── ProjectMemory ───────────────────────────────────────────────────────────────

def test_zone_caches_instances():
    pm = ProjectMemory(DictBackend())
    z1 = pm.zone("x")
    z2 = pm.zone("x")
    assert z1 is z2


def test_zone_none_uses_default():
    pm = ProjectMemory(DictBackend())
    assert pm.zone(None).project_id == "default"
    assert pm.zone("").project_id == "default"


def test_current_follows_contextvar():
    pm = ProjectMemory(DictBackend())
    with project_context("ctx-proj"):
        assert pm.current().project_id == "ctx-proj"
    # Outside the context → default
    assert pm.current().project_id == "default"


async def test_register_and_list_projects_uses_original_ids():
    pm = ProjectMemory(DictBackend())
    await pm.register("Acme/App")   # unsafe char, but registry stores original
    await pm.register("other")
    listed = await pm.list_projects()
    assert listed == ["Acme/App", "other"]


async def test_list_projects_fallback_scans_keys():
    """Zones used without register() are still discoverable via key scan."""
    pm = ProjectMemory(DictBackend())
    await pm.zone("ghost").set("k", "v")  # write without register()
    listed = await pm.list_projects()
    assert "ghost" in listed


async def test_clear_project_erases_and_deregisters():
    pm = ProjectMemory(DictBackend())
    await pm.register("doomed")
    await pm.zone("doomed").set("k", "v")
    await pm.clear_project("doomed")
    assert await pm.zone("doomed").get("k") is None
    assert await pm.list_projects() == []


async def test_clear_project_isolated():
    pm = ProjectMemory(DictBackend())
    await pm.zone("keep").set("k", "kept")
    await pm.zone("drop").set("k", "dropped")
    await pm.clear_project("drop")
    assert await pm.zone("keep").get("k") == "kept"
    assert await pm.zone("drop").get("k") is None


# ── project-scoped skills ────────────────────────────────────────────────────────

async def test_project_skills_resolve_active_project():
    pm = ProjectMemory(DictBackend())
    skills = make_project_memory_skills(pm)
    recall, remember = skills[0], skills[1]

    with project_context("proj-a"):
        await remember.execute(key="secret", value="alpha")
    with project_context("proj-b"):
        await remember.execute(key="secret", value="beta")
        assert await recall.execute(query="secret") == "beta"
    with project_context("proj-a"):
        assert await recall.execute(query="secret") == "alpha"


async def test_project_skills_default_when_no_context():
    pm = ProjectMemory(DictBackend())
    skills = make_project_memory_skills(pm)
    recall, remember = skills[0], skills[1]
    await remember.execute(key="k", value="v")        # no context → default
    assert await recall.execute(query="k") == "v"
    assert pm.zone("default").project_id == "default"


def test_project_skills_have_expected_names():
    pm = ProjectMemory(DictBackend())
    names = {s.name for s in make_project_memory_skills(pm)}
    assert names == {"recall", "remember", "list_recent", "pin_memory", "annotate_memory"}


# ── lifecycle on project zones ───────────────────────────────────────────────────

class _SummaryAPI:
    async def complete(self, messages, **kwargs):
        return "project digest"


async def test_project_zone_consolidate_isolated():
    pm = ProjectMemory(DictBackend())
    for i in range(5):
        await pm.zone("alpha").append_history({"i": i})
    await pm.zone("beta").append_history({"i": 99})

    summary = await pm.zone("alpha").consolidate(_SummaryAPI(), keep_recent=1, min_candidates=2)
    assert summary is not None and summary.content == "project digest"
    # beta untouched
    beta = await pm.zone("beta").get_history()
    assert [e.content for e in beta] == [{"i": 99}]


async def test_project_zone_stats():
    pm = ProjectMemory(DictBackend())
    await pm.zone("alpha").append_history("a", tags=["t"])
    await pm.zone("alpha").append_history("b")
    stats = await pm.zone("alpha").stats()
    assert stats["area"] == "project:alpha"
    assert stats["total"] == 2
    assert stats["tags"] == {"t": 1}


async def test_project_decay_half_life_threads_to_zones():
    pm = ProjectMemory(DictBackend(), decay_half_life=120)
    assert pm.zone("x")._decay_half_life == 120

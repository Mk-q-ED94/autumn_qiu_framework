"""P4a tests: the push side of the activation engine.

``WP4.activate_push`` scans a zone (query-less) and fires CONSTRAIN/REMIND
memories whose trigger/aim gates open against a turn context; ``render_push_context``
renders them into a prompt fragment; ``Autumn.active_context`` is the public,
flag-gated seam. The live wiring (``Autumn._compute_push`` → the four entry
points → WP1/WP2/WP3) is exercised end-to-end in ``test_push_end_to_end.py``.
"""
from autumn import Autumn
from autumn.core.config import AutumnConfig, BehaviorConfig, ModelConfig
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea
from autumn.core.memory.dimensions import ActivationContext, Aim, Trigger, Use, UseMode
from autumn.core.memory.project import ProjectMemory
from autumn.core.memory.shared import SharedZone
from autumn.core.types import Protocol
from autumn.core.workspace.wp4 import WP4Mem, render_push_context


def _wp4() -> WP4Mem:
    backend = DictBackend()
    return WP4Mem(
        None,
        MemoryArea("wp4", backend),
        zones={"mom1": MemoryArea("mom1", backend), "shared": SharedZone(backend)},
        projects=ProjectMemory(DictBackend()),
    )


# ── render_push_context ────────────────────────────────────────────────────────

def test_render_empty_when_no_entries():
    assert render_push_context([]) == ""


def test_render_groups_constraints_and_reminders():
    class _E:  # minimal stand-in carrying the fields render reads
        def __init__(self, text, mode, template=None):
            self.text = text
            self.use = Use(mode=mode, template=template)

    out = render_push_context([
        _E("no direct prod writes", UseMode.CONSTRAIN),
        _E("user prefers metric units", UseMode.REMIND),
    ])
    assert "Active constraints (must follow):" in out
    assert "- no direct prod writes" in out
    assert "Active reminders:" in out
    assert "- user prefers metric units" in out


def test_render_applies_template():
    class _E:
        def __init__(self):
            self.text = "v2"
            self.use = Use(mode=UseMode.REMIND, template="target release = {content}")
    assert "target release = v2" in render_push_context([_E()])


# ── activate_push: candidate filtering ──────────────────────────────────────────

async def test_push_ignores_non_push_modes():
    wp4 = _wp4()
    mom1 = wp4._resolve("mom1")
    await mom1.append_history("plain context", use=Use(mode=UseMode.CONTEXT))
    await mom1.append_history("a summary", use=Use(mode=UseMode.SUMMARIZE))
    fired = await wp4.activate_push(area="mom1")
    assert fired == []  # only CONSTRAIN/REMIND are push candidates


async def test_push_fires_unconditional_constraint():
    wp4 = _wp4()
    mom1 = wp4._resolve("mom1")
    # No trigger/aim config → always-on constraint.
    await mom1.append_history("always enforce X", use=Use(mode=UseMode.CONSTRAIN))
    fired = await wp4.activate_push(area="mom1")
    assert [e.content for e in fired] == ["always enforce X"]


# ── activate_push: trigger / aim gating ─────────────────────────────────────────

async def test_push_trigger_cue_boosts_ranking():
    wp4 = _wp4()
    mom1 = wp4._resolve("mom1")
    await mom1.append_history("cued rule", use=Use(mode=UseMode.CONSTRAIN),
                              trigger=Trigger(cues=["deploy"]))
    await mom1.append_history("plain rule", use=Use(mode=UseMode.CONSTRAIN))  # newer
    fired = await wp4.activate_push(area="mom1", ctx=ActivationContext(cues=["deploy"]))
    assert fired[0].content == "cued rule"  # cue boost beats recency tiebreak


async def test_push_not_before_gates_out():
    wp4 = _wp4()
    mom1 = wp4._resolve("mom1")
    await mom1.append_history("scheduled rule", use=Use(mode=UseMode.CONSTRAIN),
                              trigger=Trigger(not_before=10_000_000_000.0))  # far future
    fired = await wp4.activate_push(area="mom1", ctx=ActivationContext(now=1000.0))
    assert fired == []  # not_before in the future → trigger weight 0 → no fire


async def test_push_aim_gate_vetoes_on_goal_mismatch():
    wp4 = _wp4()
    mom1 = wp4._resolve("mom1")
    await mom1.append_history("goal-scoped rule", use=Use(mode=UseMode.CONSTRAIN),
                              aim=Aim(goal_ref="goal:v2", scope=["x"]))
    # ctx has a different goal and no matching cue → align 0 → vetoed.
    out = await wp4.activate_push(area="mom1", ctx=ActivationContext(goal="goal:other"))
    assert out == []
    # ctx matches the goal → fires.
    ok = await wp4.activate_push(area="mom1", ctx=ActivationContext(goal="goal:v2"))
    assert [e.content for e in ok] == ["goal-scoped rule"]


async def test_push_does_not_reinforce_by_default():
    wp4 = _wp4()
    mom1 = wp4._resolve("mom1")
    await mom1.append_history("rule", use=Use(mode=UseMode.CONSTRAIN))
    await wp4.activate_push(area="mom1")
    [stored] = await mom1.get_history()
    assert stored.use.stats.count == 0  # auto-surfaced ≠ deliberately used


async def test_push_is_audited():
    wp4 = _wp4()
    mom1 = wp4._resolve("mom1")
    await mom1.append_history("rule", use=Use(mode=UseMode.CONSTRAIN))
    await wp4.activate_push(area="mom1")
    log = await wp4.audit_log()
    assert any(
        isinstance(e.content, dict) and e.content.get("action") == "activate_push"
        for e in log
    )


# ── Autumn.active_context (framework seam) ──────────────────────────────────────

def _cfg(push: bool) -> AutumnConfig:
    m = ModelConfig(api_key="k", base_url="http://x", model="m", protocol=Protocol("openai"))
    return AutumnConfig(a1=m, a2=m, a3=m,
                        behavior=BehaviorConfig(fourd_push_on_turn=push))


async def test_active_context_disabled_returns_empty(tmp_path):
    cfg = _cfg(push=False)
    cfg.storage.db_path = str(tmp_path / "mem.db")
    async with Autumn(cfg) as autumn:
        await autumn.mom1.append_history("rule", use=Use(mode=UseMode.CONSTRAIN))
        assert await autumn.active_context(text="anything") == ""  # push off


async def test_active_context_enabled_renders_fragment(tmp_path):
    cfg = _cfg(push=True)
    cfg.storage.db_path = str(tmp_path / "mem.db")
    async with Autumn(cfg) as autumn:
        await autumn.mom1.append_history(
            "no direct prod writes", use=Use(mode=UseMode.CONSTRAIN)
        )
        frag = await autumn.active_context(text="deploy now", area="mom1")
        assert "Active constraints (must follow):" in frag
        assert "no direct prod writes" in frag


async def test_compute_push_goal_gate_fires_from_active_project(tmp_path):
    """A goal_ref-tagged constraint stays vetoed until the turn supplies a
    matching goal — which _compute_push now derives from the active project,
    making the RFC's flagship goal-gated activation reachable on a real turn."""
    from autumn.core.memory.dimensions import Aim
    from autumn.core.memory.project import project_context

    cfg = _cfg(push=True)
    cfg.storage.db_path = str(tmp_path / "mem.db")
    async with Autumn(cfg) as autumn:
        await autumn.mom1.append_history(
            "freeze the schema",
            use=Use(mode=UseMode.CONSTRAIN),
            aim=Aim(goal_ref="ship-v2"),
        )
        # No goal in context → the goal-gated aim vetoes (align 0), nothing fires.
        _frag, count_no_goal, _ = await autumn._compute_push("do work")
        assert count_no_goal == 0

        # Scope the turn to a project whose master goal matches goal_ref → fires.
        await autumn.projects.update_metadata("proj", goals={"master": "ship-v2"})
        with project_context("proj"):
            frag, count, _ = await autumn._compute_push("do work")
    assert count == 1
    assert "freeze the schema" in frag


def test_behavior_config_push_flag_default_and_env(monkeypatch):
    assert BehaviorConfig().fourd_push_on_turn is True  # on by default (no-op until a CONSTRAIN/REMIND memory exists)
    monkeypatch.setenv("FOURD_PUSH_ON_TURN", "off")
    assert BehaviorConfig.from_env().fourd_push_on_turn is False

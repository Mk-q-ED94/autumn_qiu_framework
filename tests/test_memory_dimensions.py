"""Tests for the 4D memory primitives (P0).

Pure data + pure functions: aim (relevance gate), use (protocol + usage ledger),
time (weighted trigger), and the activation combiner. No I/O, no recall — see
docs/rfc-4d-memory.md.
"""
import math

from autumn.core.memory.dimensions import (
    ActivationContext,
    Aim,
    Trigger,
    Use,
    UseMode,
    UseStats,
    activation_score,
)


# ── aim 维: align gate ─────────────────────────────────────────────────────────

def test_empty_aim_aligns_with_everything():
    assert Aim().is_empty()
    assert Aim().align(ActivationContext()) == 1.0


def test_aim_goal_ref_exact_match():
    aim = Aim(intent="deploy", goal_ref="goal:ship-v2")
    assert aim.align(ActivationContext(goal="goal:ship-v2")) == 1.0
    # Different goal, no scope/cues → veto.
    assert aim.align(ActivationContext(goal="goal:other")) == 0.0


def test_aim_scope_jaccard_against_cues():
    aim = Aim(scope=["deploy", "db"])
    # overlap {db} / union {deploy, db, config} = 1/3
    score = aim.align(ActivationContext(cues=["db", "config"]))
    assert math.isclose(score, 1 / 3)


def test_aim_scope_is_case_insensitive():
    aim = Aim(scope=["Deploy", "DB"])
    assert aim.align(ActivationContext(cues=["deploy"])) == 0.5  # {deploy}/{deploy,db}


def test_aim_with_purpose_but_no_matching_context_vetoes():
    aim = Aim(goal_ref="goal:x", scope=["a"])
    assert aim.align(ActivationContext()) == 0.0


# ── use 维: stats ledger ───────────────────────────────────────────────────────

def test_usestats_touch_accumulates():
    s = UseStats()
    s.touch(now=100.0, reward=0.5)
    s.touch(now=200.0, reward=0.25)
    assert s.count == 2
    assert s.last_used == 200.0
    assert math.isclose(s.reward, 0.75)


def test_use_touch_delegates_to_stats():
    u = Use()
    u.touch(now=10.0, reward=1.0)
    assert u.stats.count == 1
    assert u.stats.last_used == 10.0
    assert u.stats.reward == 1.0


def test_unused_memory_has_zero_utility():
    assert Use().utility() == 0.0


def test_utility_grows_with_use_count():
    a, b = Use(), Use()
    a.touch(now=1.0)
    for _ in range(5):
        b.touch(now=1.0)
    assert b.utility() > a.utility() > 0.0


def test_utility_reward_factor_is_bounded():
    # Cumulative reward is clamped to [-0.5, 1.0] → multiplier in [0.5, 2.0].
    high = Use()
    high.touch(now=1.0, reward=100.0)   # clamps to +1.0 → ×2.0
    low = Use()
    low.touch(now=1.0, reward=-100.0)   # clamps to -0.5 → ×0.5
    base = math.log1p(1)
    assert math.isclose(high.utility(), base * 2.0)
    assert math.isclose(low.utility(), base * 0.5)


def test_use_mode_default_is_context():
    assert Use().mode is UseMode.CONTEXT
    assert UseMode.CONSTRAIN.value == "constrain"


# ── time 维: trigger weight ────────────────────────────────────────────────────

def test_trigger_default_weight_is_base():
    t = Trigger()
    assert t.weight(created_at=0.0, now=1000.0, ctx=ActivationContext()) == 1.0


def test_trigger_half_life_decays_with_age():
    t = Trigger(half_life=100.0)
    # one half-life of age → 0.5
    w = t.weight(created_at=0.0, now=100.0, ctx=ActivationContext(now=100.0))
    assert math.isclose(w, 0.5)


def test_trigger_not_before_gates_to_zero():
    t = Trigger(not_before=500.0)
    assert t.weight(created_at=0.0, now=499.0, ctx=ActivationContext()) == 0.0
    assert t.weight(created_at=0.0, now=500.0, ctx=ActivationContext()) == 1.0


def test_trigger_expiry_gates_to_zero():
    t = Trigger(expires_at=100.0)
    assert not t.is_expired(99.0)
    assert t.is_expired(100.0)
    assert t.weight(created_at=0.0, now=100.0, ctx=ActivationContext()) == 0.0


def test_trigger_every_cooldown_blocks_then_allows():
    t = Trigger(every=60.0)
    # last used 30s ago → still cooling down
    assert t.weight(created_at=0.0, now=1000.0, ctx=ActivationContext(), last_used=970.0) == 0.0
    # last used 90s ago → cooled down
    assert t.weight(created_at=0.0, now=1000.0, ctx=ActivationContext(), last_used=910.0) == 1.0
    # never used → not throttled
    assert t.weight(created_at=0.0, now=1000.0, ctx=ActivationContext(), last_used=None) == 1.0


def test_trigger_cues_boost_weight():
    t = Trigger(cues=["deploy", "db"])
    plain = t.weight(created_at=0.0, now=1.0, ctx=ActivationContext())
    boosted = t.weight(created_at=0.0, now=1.0, ctx=ActivationContext(cues=["deploy", "db"]))
    assert plain == 1.0
    assert boosted == 2.0  # full overlap → ×(1 + 1.0)


# ── activation combiner ────────────────────────────────────────────────────────

def test_activation_align_zero_vetoes():
    assert activation_score(w_time=5.0, align=0.0, utility=10.0) == 0.0


def test_activation_fresh_entry_scores_without_utility():
    # utility 0 → score is w_time × align × 1
    assert activation_score(w_time=2.0, align=0.5, utility=0.0) == 1.0


def test_activation_utility_is_a_boost():
    base = activation_score(w_time=1.0, align=1.0, utility=0.0)
    boosted = activation_score(w_time=1.0, align=1.0, utility=1.0)
    assert base == 1.0
    assert boosted == 2.0


def test_activation_floors_negative_inputs():
    assert activation_score(w_time=-1.0, align=1.0, utility=0.0) == 0.0
    assert activation_score(w_time=1.0, align=1.0, utility=-5.0) == 1.0


# ── activation context defaults ────────────────────────────────────────────────

def test_activation_context_defaults_now_to_walltime():
    import time
    ctx = ActivationContext()
    assert abs(ctx.now - time.time()) < 5.0
    assert ctx.query is None and ctx.goal is None and ctx.cues == []

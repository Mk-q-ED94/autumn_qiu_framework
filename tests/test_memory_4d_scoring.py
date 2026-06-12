"""P2 tests: recall/evict ranked by the 4D activation/retention score, gated by
the ``fourd_enabled`` flag.

The contract: with the flag OFF, behavior is byte-identical to today; with the
flag ON but no entry annotated, scoring collapses to importance×decay so nothing
visibly changes. Only annotated entries (aim/use/trigger) reorder.
"""
from autumn.core.config import BehaviorConfig
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea
from autumn.core.memory.dimensions import Aim, Trigger, Use, UseStats


# ── config flag ────────────────────────────────────────────────────────────────

def test_behavior_config_fourd_flag_default_is_off():
    assert BehaviorConfig().fourd_memory_enabled is False


def test_behavior_config_fourd_flag_from_env(monkeypatch):
    monkeypatch.setenv("FOURD_MEMORY_ENABLED", "true")
    assert BehaviorConfig.from_env().fourd_memory_enabled is True
    monkeypatch.setenv("FOURD_MEMORY_ENABLED", "off")
    assert BehaviorConfig.from_env().fourd_memory_enabled is False


# ── recall: degradation invariant ──────────────────────────────────────────────

async def test_recall_fourd_empty_dims_preserves_importance_order():
    # Flag on, but entries carry no dimensions → ranked by importance, as today.
    area = MemoryArea("t", DictBackend(), fourd_enabled=True)
    await area.append_history("low", tags=["t"], importance=1.0)
    await area.append_history("high", tags=["t"], importance=1.4)
    res = await area.recall("t", tags=["t"])
    assert res[0].content == "high"


# ── recall: each dimension reorders ─────────────────────────────────────────────

async def test_recall_fourd_utility_beats_recency():
    area = MemoryArea("t", DictBackend(), fourd_enabled=True)
    # 'useful' is older but heavily used; 'plain' is newer but unused.
    await area.append_history("useful", tags=["topic"],
                              use=Use(stats=UseStats(count=20, reward=1.0)))
    await area.append_history("plain", tags=["topic"])
    res = await area.recall("topic", tags=["topic"])
    assert res[0].content == "useful"  # utility boost beats recency tiebreak


async def test_recall_fourd_aim_veto_sinks_entry():
    area = MemoryArea("t", DictBackend(), fourd_enabled=True)
    # 'gated' has a purpose the recall context matches neither by goal nor cue.
    await area.append_history("gated", tags=["x"],
                              aim=Aim(goal_ref="goal:none", scope=["unrelated"]))
    await area.append_history("open", tags=["x"])
    res = await area.recall("x", tags=["x"])
    assert res[0].content == "open"
    assert res[-1].content == "gated"  # align 0 → activation 0 → sinks


async def test_recall_fourd_trigger_cue_boost():
    area = MemoryArea("t", DictBackend(), fourd_enabled=True)
    await area.append_history("cued", tags=["deploy"], trigger=Trigger(cues=["deploy"]))
    await area.append_history("plain", tags=["deploy"])  # newer, no cues
    res = await area.recall("deploy", tags=["deploy"])
    assert res[0].content == "cued"  # cue overlap boosts trigger weight


async def test_recall_flag_off_ignores_dimensions():
    # Same setup as the utility test, but flag off → recency wins, dims ignored.
    area = MemoryArea("t", DictBackend(), fourd_enabled=False)
    await area.append_history("useful", tags=["topic"],
                              use=Use(stats=UseStats(count=20, reward=1.0)))
    await area.append_history("plain", tags=["topic"])  # newer
    res = await area.recall("topic", tags=["topic"])
    assert res[0].content == "plain"  # newest first, utility ignored


# ── evict: retention by use utility ─────────────────────────────────────────────

async def test_evict_fourd_retains_high_utility_over_recency():
    area = MemoryArea("t", DictBackend(), history_limit=2, fourd_enabled=True)
    # A is oldest but heavily used; B, C are plain. Limit 2 forces one eviction.
    await area.append_history("A", use=Use(stats=UseStats(count=50, reward=1.0)))
    await area.append_history("B")
    await area.append_history("C")  # triggers eviction
    contents = {e.content for e in await area.get_history()}
    assert "A" in contents          # retained by utility despite being oldest
    assert len(contents) == 2


async def test_evict_flag_off_drops_oldest_regardless_of_use():
    area = MemoryArea("t", DictBackend(), history_limit=2, fourd_enabled=False)
    await area.append_history("A", use=Use(stats=UseStats(count=50, reward=1.0)))
    await area.append_history("B")
    await area.append_history("C")
    contents = {e.content for e in await area.get_history()}
    assert "A" not in contents      # flag off → utility ignored, oldest A evicted


async def test_evict_fourd_empty_dims_matches_importance():
    # Flag on, no use annotation → retention == effective_importance, so the
    # lowest-importance entry is evicted exactly as today.
    area = MemoryArea("t", DictBackend(), history_limit=2, fourd_enabled=True)
    await area.append_history("weak", importance=0.5)
    await area.append_history("mid", importance=1.0)
    await area.append_history("strong", importance=1.2)  # triggers eviction
    contents = {e.content for e in await area.get_history()}
    assert "weak" not in contents
    assert contents == {"mid", "strong"}

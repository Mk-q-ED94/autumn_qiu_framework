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

def test_behavior_config_fourd_flag_default_is_on():
    # 0.3.x activates the 4D memory layer by default (degrades safely to
    # importance×timestamp for un-annotated entries).
    assert BehaviorConfig().fourd_memory_enabled is True


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


async def test_recall_semantic_hit_survives_time_decay(tmp_path):
    # Regression: vector synthetic entries were stamped timestamp=0.0, so when a
    # zone had BOTH 4D and a decay half-life on, the huge synthetic age decayed
    # their activation to 0 — silently sorting every semantic hit dead last and
    # effectively disabling semantic recall. A relevant hit must still rank.
    from autumn.core.memory.backends.vector_backend import SQLiteVectorStore

    class _Emb:
        # query "needle" → [1,0]; the doc → [0.8,0.6] (cosine 0.8, an *unpinned*
        # 1.2 importance, so time-decay actually applies to it).
        _vecs = {"needle": [1.0, 0.0], "the needle we want": [0.8, 0.6]}

        async def embed(self, text):
            return list(self._vecs.get(text, [0.0, 1.0]))

        async def embed_batch(self, texts):
            return [await self.embed(t) for t in texts]

    area = MemoryArea("t", DictBackend(), decay_half_life=86400.0, fourd_enabled=True)
    area.enable_vector(_Emb(), SQLiteVectorStore(str(tmp_path / "v.db")), auto_index=True)
    await area.index("n1", "the needle we want")
    # Two recent unrelated entries it must out-rank (it would sink below them
    # when decayed to activation 0).
    for i in range(2):
        await area.append_history(f"recent note {i}", tags=["topic"], importance=1.0)

    res = await area.recall("needle", tags=["topic"], k=5)
    assert "needle" in str(res[0].content)  # relevance wins; not decayed to the bottom


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

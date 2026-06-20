import os
import tempfile
import time
import pytest

from autumn.core.memory.base import MemoryArea, MemoryEntry, _evict
from autumn.core.memory.backends import DictBackend, SQLiteBackend, HybridBackend
from autumn.core.memory.shared import SharedZone
from autumn.core.memory.mom1 import Mom1
from autumn.core.memory.mom2 import Mom2
from autumn.core.memory.mom3 import Mom3


# ── MemoryEntry ───────────────────────────────────────────────────────────────

def test_memory_entry_defaults():
    e = MemoryEntry(id="x", content="hello", timestamp=1.0)
    assert e.importance == 1.0
    assert e.tags == []
    assert e.meta == {}
    assert not e.is_pinned


def test_memory_entry_pinned_threshold():
    e = MemoryEntry(id="x", content="hi", timestamp=0.0, importance=1.5)
    assert e.is_pinned
    e2 = MemoryEntry(id="y", content="hi", timestamp=0.0, importance=1.49)
    assert not e2.is_pinned


def test_memory_entry_text_str():
    e = MemoryEntry(id="a", content="plain text", timestamp=0.0)
    assert e.text == "plain text"


def test_memory_entry_text_dict():
    e = MemoryEntry(id="a", content={"key": "val"}, timestamp=0.0)
    assert '"key"' in e.text
    assert '"val"' in e.text


def test_memory_entry_to_dict_round_trip():
    e = MemoryEntry(id="abc", content={"x": 1}, timestamp=42.0, importance=1.5, tags=["t1"], meta={"m": 1})
    d = e.to_dict()
    assert d["_m"] is True
    e2 = MemoryEntry.from_dict(d)
    assert e2.id == "abc"
    assert e2.content == {"x": 1}
    assert e2.timestamp == 42.0
    assert e2.importance == 1.5
    assert e2.tags == ["t1"]
    assert e2.meta == {"m": 1}


def test_memory_entry_from_dict_legacy():
    """Plain dicts from old code are transparently upgraded."""
    raw = {"ts": 100.0, "input": "hello", "output": "world"}
    e = MemoryEntry.from_dict(raw)
    assert e.content == raw
    assert e.timestamp == 100.0
    assert e.importance == 1.0
    assert e.id  # auto-generated


# ── _evict ────────────────────────────────────────────────────────────────────

def _make_entry(importance: float, ts: float, pinned: bool = False) -> MemoryEntry:
    imp = 1.5 if pinned else importance
    return MemoryEntry(id=f"{importance}-{ts}", content="x", timestamp=ts, importance=imp)


def test_evict_no_op_when_under_limit():
    h = [_make_entry(1.0, i) for i in range(5)]
    assert _evict(h, 10) == h


def test_evict_fifo_equal_importance():
    h = [_make_entry(1.0, i) for i in range(10)]
    result = _evict(h, 5)
    assert len(result) == 5
    assert [e.timestamp for e in result] == [5, 6, 7, 8, 9]


def test_evict_prefers_high_importance():
    low = [_make_entry(0.5, i) for i in range(5)]
    high = [_make_entry(1.0, i + 5) for i in range(5)]
    result = _evict(low + high, 5)
    assert len(result) == 5
    # All high-importance entries survive
    assert all(e.importance == 1.0 for e in result)


def test_evict_preserves_pinned():
    normal = [_make_entry(0.9, i) for i in range(9)]
    pinned = _make_entry(1.5, 99, pinned=True)
    result = _evict(normal + [pinned], 5)
    assert any(e.is_pinned for e in result)


def test_evict_result_chronological_order():
    h = [_make_entry(1.0, 10 - i) for i in range(5)]
    result = _evict(h, 3)
    timestamps = [e.timestamp for e in result]
    assert timestamps == sorted(timestamps)


# ── Backend basics ────────────────────────────────────────────────────────────

async def test_dict_backend_basic():
    backend = DictBackend()
    await backend.set("k", {"v": 1})
    assert await backend.get("k") == {"v": 1}
    assert await backend.keys() == ["k"]
    await backend.delete("k")
    assert await backend.get("k") is None


async def test_memory_area_namespacing():
    backend = DictBackend()
    a = MemoryArea("a", backend)
    b = MemoryArea("b", backend)
    await a.set("x", 1)
    await b.set("x", 2)
    assert await a.get("x") == 1
    assert await b.get("x") == 2
    assert await a.keys() == ["x"]
    assert await b.keys() == ["x"]


async def test_sqlite_backend_persistence():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test.db")
        b1 = SQLiteBackend(path)
        await b1.set("k", [1, 2, 3])
        b2 = SQLiteBackend(path)
        assert await b2.get("k") == [1, 2, 3]


async def test_hybrid_backend_short_term_wins():
    long_term = DictBackend()
    await long_term.set("k", "long")
    hybrid = HybridBackend(long_term)
    await hybrid.set("k", "short", persist=False)
    assert await hybrid.get("k") == "short"


async def test_hybrid_clear_session_preserves_long_term():
    long_term = DictBackend()
    hybrid = HybridBackend(long_term)
    await hybrid.set("k", "v")
    await hybrid.clear_session()
    assert await long_term.get("k") == "v"
    assert await hybrid.get("k") == "v"


async def test_hybrid_warms_cache_on_miss():
    long_term = DictBackend()
    await long_term.set("k", "v")
    hybrid = HybridBackend(long_term)
    assert await hybrid.get("k") == "v"
    assert await hybrid._short.get("k") == "v"


# ── History API ───────────────────────────────────────────────────────────────

async def test_append_history_returns_entry():
    area = MemoryArea("ws", DictBackend())
    entry = await area.append_history({"turn": 1})
    assert isinstance(entry, MemoryEntry)
    assert entry.content == {"turn": 1}


async def test_append_history_wraps_legacy_dict():
    area = MemoryArea("ws", DictBackend())
    await area.append_history({"turn": 1})
    await area.append_history({"turn": 2})
    history = await area.get_history()
    assert len(history) == 2
    assert history[0].content == {"turn": 1}
    assert history[1].content == {"turn": 2}


async def test_append_history_importance_and_tags():
    area = MemoryArea("ws", DictBackend())
    e = await area.append_history("important note", importance=1.8, tags=["key", "session"])
    assert e.importance == 1.8
    assert "key" in e.tags
    assert e.is_pinned


async def test_history_capped_count_based():
    area = MemoryArea("ws", DictBackend())
    for i in range(60):
        await area.append_history({"turn": i}, max_entries=10)
    history = await area.get_history()
    assert len(history) == 10
    assert history[0].content["turn"] == 50
    assert history[-1].content["turn"] == 59


async def test_get_history_empty_tags_is_not_a_filter():
    # tags=[] must mean "no tag filter" (return everything), not "match the empty
    # set" — set().issubset() is always True, so filtering on it returns all and
    # the explicit-empty case would be a confusing silent no-op either way.
    area = MemoryArea("ws", DictBackend())
    await area.append_history("tagged", tags=["x"])
    await area.append_history("untagged")
    assert len(await area.get_history(tags=[])) == 2
    assert len(await area.get_history(tags=["x"])) == 1


async def test_recall_never_raises_on_backend_error():
    # recall()'s contract is "never raises" — a backend that throws on get must
    # degrade to empty, not propagate into the access broker / recall skill.
    class _BoomBackend(DictBackend):
        async def get(self, key):
            raise RuntimeError("backend down")

    area = MemoryArea("ws", _BoomBackend())
    assert await area.recall("anything") == []


async def test_history_importance_weighted_eviction():
    area = MemoryArea("ws", DictBackend(), history_limit=3)
    e1 = await area.append_history("low A", importance=0.5)
    await area.append_history("normal B", importance=1.0)
    e3 = await area.append_history("high C", importance=1.8)
    # History is exactly at limit (3) — adding one more should evict e1 (lowest)
    await area.append_history("new D", importance=1.0)
    history = await area.get_history()
    ids = {e.id for e in history}
    assert e1.id not in ids, "low-importance entry should have been evicted"
    assert e3.id in ids, "high-importance (pinned) entry must survive"


async def test_history_pinned_never_evicted():
    area = MemoryArea("ws", DictBackend(), history_limit=2)
    pinned = await area.append_history("critical", importance=2.0)
    await area.append_history("a", importance=1.0)
    await area.append_history("b", importance=1.0)
    history = await area.get_history()
    assert any(e.id == pinned.id for e in history)


async def test_get_history_filter_by_tags():
    area = MemoryArea("ws", DictBackend())
    await area.append_history("session note", tags=["session"])
    await area.append_history("task note", tags=["task"])
    await area.append_history("both", tags=["session", "task"])
    results = await area.get_history(tags=["session"])
    assert all("session" in e.tags for e in results)
    assert len(results) == 2


async def test_get_history_filter_since():
    area = MemoryArea("ws", DictBackend())
    now = time.time()
    await area.append_history(MemoryEntry(id="old", content="old", timestamp=now - 100))
    await area.append_history(MemoryEntry(id="new", content="new", timestamp=now + 1))
    results = await area.get_history(since=now)
    assert len(results) == 1
    assert results[0].id == "new"


async def test_recent_returns_last_n():
    area = MemoryArea("ws", DictBackend())
    for i in range(10):
        await area.append_history({"i": i})
    recent = await area.recent(3)
    assert len(recent) == 3
    assert recent[-1].content["i"] == 9


# ── pin / unpin ───────────────────────────────────────────────────────────────

async def test_pin_protects_from_eviction():
    area = MemoryArea("ws", DictBackend(), history_limit=2)
    e1 = await area.append_history("first")
    await area.pin(e1.id)
    await area.append_history("second")
    await area.append_history("third")  # triggers eviction
    history = await area.get_history()
    assert any(e.id == e1.id for e in history), "pinned entry should survive"


async def test_pin_returns_true_on_found():
    area = MemoryArea("ws", DictBackend())
    e = await area.append_history("data")
    assert await area.pin(e.id) is True


async def test_pin_returns_false_on_missing():
    area = MemoryArea("ws", DictBackend())
    assert await area.pin("nonexistent-id") is False


async def test_unpin_resets_importance():
    area = MemoryArea("ws", DictBackend())
    e = await area.append_history("data", importance=2.0)
    await area.unpin(e.id)
    history = await area.get_history()
    unpinned = next(x for x in history if x.id == e.id)
    assert unpinned.importance == 1.0
    assert not unpinned.is_pinned


# ── recall ────────────────────────────────────────────────────────────────────

async def test_recall_exact_kv_hit():
    area = MemoryArea("ws", DictBackend())
    await area.set("lang", "Python")
    results = await area.recall("lang")
    assert len(results) == 1
    assert results[0].content == "Python"
    assert "kv" in results[0].tags


async def test_recall_no_match_returns_empty():
    area = MemoryArea("ws", DictBackend())
    results = await area.recall("nothing")
    assert results == []


async def test_recall_tag_filter():
    area = MemoryArea("ws", DictBackend())
    await area.append_history("task A", tags=["task"])
    await area.append_history("session B", tags=["session"])
    results = await area.recall("anything", tags=["task"])
    assert all("task" in e.tags for e in results)


# ── Mom hierarchy ─────────────────────────────────────────────────────────────

async def test_mom_hierarchy_isolation():
    """Mom2 and Mom3 have no API to read Mom1's data."""
    shared = SharedZone(DictBackend())
    mom2 = Mom2(DictBackend(), shared)
    mom3 = Mom3(DictBackend(), shared)
    mom1 = Mom1(DictBackend(), mom2, mom3)

    await mom1.set("secret", "1")
    await mom2.set("data", "2")
    await mom3.set("data", "3")

    assert await mom1.read_mom2("data") == "2"
    assert await mom1.read_mom3("data") == "3"
    assert not hasattr(mom2, "mom1")
    assert not hasattr(mom3, "mom1")


async def test_shared_zone_read_write_from_both():
    shared = SharedZone(DictBackend())
    mom2 = Mom2(DictBackend(), shared)
    mom3 = Mom3(DictBackend(), shared)

    await mom2.shared.set("handoff", "x")
    assert await mom3.shared.get("handoff") == "x"


async def test_mom1_broadcast_reaches_shared_zone():
    shared = SharedZone(DictBackend())
    mom2 = Mom2(DictBackend(), shared)
    mom3 = Mom3(DictBackend(), shared)
    mom1 = Mom1(DictBackend(), mom2, mom3)

    await mom1.broadcast("user_lang", "zh-CN")

    # Both WP2 and WP3 can read it via their shared zone
    assert await mom2.shared.get("user_lang") == "zh-CN"
    assert await mom3.shared.get("user_lang") == "zh-CN"


# ── TTL / expiration ──────────────────────────────────────────────────────────

def test_entry_is_expired():
    now = time.time()
    assert MemoryEntry("a", "x", now, expires_at=now - 1).is_expired(now)
    assert not MemoryEntry("a", "x", now, expires_at=now + 100).is_expired(now)
    assert not MemoryEntry("a", "x", now).is_expired(now)  # no TTL → never


def test_entry_ttl_round_trips():
    e = MemoryEntry("a", "x", 1.0, expires_at=42.0)
    assert MemoryEntry.from_dict(e.to_dict()).expires_at == 42.0


async def test_append_ttl_sets_expiry():
    area = MemoryArea("ws", DictBackend())
    e = await area.append_history("ephemeral", ttl=100)
    assert e.expires_at is not None
    assert e.expires_at > time.time()


async def test_expired_entries_filtered_from_get_history():
    area = MemoryArea("ws", DictBackend())
    now = time.time()
    await area.append_history(MemoryEntry("live", "here", now))
    await area.append_history(MemoryEntry("dead", "gone", now, expires_at=now - 1))
    live = await area.get_history()
    assert [e.id for e in live] == ["live"]
    # include_expired surfaces it again
    allh = await area.get_history(include_expired=True)
    assert {e.id for e in allh} == {"live", "dead"}


async def test_expired_entries_purged_on_append():
    area = MemoryArea("ws", DictBackend())
    now = time.time()
    await area.append_history(MemoryEntry("dead", "gone", now, expires_at=now - 1))
    await area.append_history("fresh")
    stored = await area.get_history(include_expired=True)
    assert all(e.id != "dead" for e in stored)  # purged during append


async def test_recall_skips_expired_tagged_history():
    area = MemoryArea("ws", DictBackend())
    now = time.time()
    await area.append_history(MemoryEntry("d", "secret", now, tags=["k"], expires_at=now - 1))
    results = await area.recall("anything", tags=["k"])
    assert results == []


# ── time-decayed importance ───────────────────────────────────────────────────

def test_effective_importance_no_halflife_is_raw():
    e = MemoryEntry("a", "x", time.time(), importance=1.0)
    assert e.effective_importance() == 1.0


def test_effective_importance_halves_per_halflife():
    now = 1000.0
    e = MemoryEntry("a", "x", timestamp=now - 10, importance=1.0)
    # age == half_life → importance halves
    assert e.effective_importance(now=now, half_life=10) == pytest.approx(0.5)
    # two half-lives → quarter
    assert e.effective_importance(now=now, half_life=5) == pytest.approx(0.25)


def test_effective_importance_pinned_never_decays():
    now = 1000.0
    e = MemoryEntry("a", "x", timestamp=0.0, importance=2.0)  # pinned
    assert e.effective_importance(now=now, half_life=1) == 2.0


async def test_decay_changes_eviction_priority():
    """With decay, a fresh low-importance entry beats a stale higher one."""
    area = MemoryArea("ws", DictBackend(), history_limit=1, decay_half_life=1.0)
    now = time.time()
    # Old, higher raw importance — but ancient, so it decays to ~0.
    await area.append_history(MemoryEntry("old", "stale", now - 10_000, importance=1.2))
    # Fresh, lower raw importance.
    await area.append_history(MemoryEntry("new", "fresh", now, importance=1.0))
    survivors = {e.id for e in await area.get_history()}
    assert survivors == {"new"}


async def test_no_decay_keeps_higher_raw_importance():
    """Control: without decay the higher-importance (older) entry wins."""
    area = MemoryArea("ws", DictBackend(), history_limit=1)  # decay off
    now = time.time()
    await area.append_history(MemoryEntry("old", "stale", now - 10_000, importance=1.2))
    await area.append_history(MemoryEntry("new", "fresh", now, importance=1.0))
    survivors = {e.id for e in await area.get_history()}
    assert survivors == {"old"}


# ── forget ────────────────────────────────────────────────────────────────────

async def test_forget_no_criteria_removes_nothing():
    area = MemoryArea("ws", DictBackend())
    await area.append_history("a")
    assert await area.forget() == 0
    assert len(await area.get_history()) == 1


async def test_forget_by_tags():
    area = MemoryArea("ws", DictBackend())
    await area.append_history("keep", tags=["good"])
    await area.append_history("drop1", tags=["bad"])
    await area.append_history("drop2", tags=["bad"])
    removed = await area.forget(tags=["bad"])
    assert removed == 2
    remaining = await area.get_history()
    assert [e.content for e in remaining] == ["keep"]


async def test_forget_before_timestamp():
    area = MemoryArea("ws", DictBackend())
    now = time.time()
    await area.append_history(MemoryEntry("old", "x", now - 100))
    await area.append_history(MemoryEntry("new", "y", now))
    removed = await area.forget(before=now - 50)
    assert removed == 1
    assert [e.id for e in await area.get_history()] == ["new"]


async def test_forget_expired_only():
    area = MemoryArea("ws", DictBackend())
    now = time.time()
    await area.append_history(MemoryEntry("live", "x", now))
    # Bypass append's auto-purge by writing directly via the backend.
    hist = await area.get_history(include_expired=True)
    hist.append(MemoryEntry("dead", "y", now, expires_at=now - 1))
    await area.set("history", [e.to_dict() for e in hist])
    removed = await area.forget(expired=True)
    assert removed == 1


# ── consolidation ─────────────────────────────────────────────────────────────

class _SummaryAPI:
    def __init__(self, text="SUMMARY"):
        self.text = text
        self.calls = 0

    async def complete(self, messages, **kwargs):
        self.calls += 1
        return self.text


async def test_consolidate_summarises_old_entries():
    area = MemoryArea("ws", DictBackend())
    for i in range(6):
        await area.append_history({"i": i})
    api = _SummaryAPI("digest")
    summary = await area.consolidate(api, keep_recent=2, min_candidates=3)
    assert summary is not None
    assert summary.content == "digest"
    assert "summary" in summary.tags
    assert summary.is_pinned
    assert summary.meta["consolidated"] == 4
    assert api.calls == 1
    # History now: summary + 2 recent = 3 entries
    history = await area.get_history()
    assert len(history) == 3
    assert sum(1 for e in history if "summary" in e.tags) == 1


async def test_consolidate_noop_when_too_few():
    area = MemoryArea("ws", DictBackend())
    await area.append_history("only one")
    api = _SummaryAPI()
    summary = await area.consolidate(api, keep_recent=2, min_candidates=3)
    assert summary is None
    assert api.calls == 0


async def test_consolidate_preserves_pinned_and_recent():
    area = MemoryArea("ws", DictBackend())
    pinned = await area.append_history("critical", importance=2.0)
    for i in range(5):
        await area.append_history({"i": i})
    api = _SummaryAPI()
    await area.consolidate(api, keep_recent=2, min_candidates=2)
    ids = {e.id for e in await area.get_history()}
    assert pinned.id in ids  # pinned survives consolidation


# ── stats ─────────────────────────────────────────────────────────────────────

async def test_stats_reports_counts_and_tags():
    area = MemoryArea("ws", DictBackend(), history_limit=99)
    await area.append_history("a", tags=["x"])
    await area.append_history("b", tags=["x", "y"])
    await area.append_history("c", importance=2.0)  # pinned
    stats = await area.stats()
    assert stats["area"] == "ws"
    assert stats["total"] == 3
    assert stats["pinned"] == 1
    assert stats["tags"] == {"x": 2, "y": 1}
    assert stats["history_limit"] == 99
    assert stats["has_vector"] is False


async def test_stats_counts_expired_separately():
    area = MemoryArea("ws", DictBackend())
    now = time.time()
    await area.append_history(MemoryEntry("live", "x", now))
    hist = await area.get_history(include_expired=True)
    hist.append(MemoryEntry("dead", "y", now, expires_at=now - 1))
    await area.set("history", [e.to_dict() for e in hist])
    stats = await area.stats()
    assert stats["total"] == 1
    assert stats["expired"] == 1

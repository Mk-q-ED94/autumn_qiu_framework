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


async def test_history_importance_weighted_eviction():
    area = MemoryArea("ws", DictBackend(), history_limit=3)
    e1 = await area.append_history("low A", importance=0.5)
    e2 = await area.append_history("normal B", importance=1.0)
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

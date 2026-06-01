import os
import tempfile
import pytest

from autumn.core.memory.base import MemoryArea
from autumn.core.memory.backends import DictBackend, SQLiteBackend, HybridBackend
from autumn.core.memory.shared import SharedZone
from autumn.core.memory.mom1 import Mom1
from autumn.core.memory.mom2 import Mom2
from autumn.core.memory.mom3 import Mom3


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


async def test_memory_area_history():
    area = MemoryArea("ws", DictBackend())
    await area.append_history({"turn": 1})
    await area.append_history({"turn": 2})
    history = await area.get_history()
    assert history == [{"turn": 1}, {"turn": 2}]


async def test_memory_area_history_capped():
    area = MemoryArea("ws", DictBackend())
    for i in range(60):
        await area.append_history({"turn": i}, max_entries=10)
    history = await area.get_history()
    assert len(history) == 10
    assert history[0]["turn"] == 50
    assert history[-1]["turn"] == 59


async def test_sqlite_backend_persistence():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "test.db")
        b1 = SQLiteBackend(path)
        await b1.set("k", [1, 2, 3])

        # Reopen
        b2 = SQLiteBackend(path)
        assert await b2.get("k") == [1, 2, 3]


async def test_hybrid_backend_short_term_wins():
    long_term = DictBackend()
    await long_term.set("k", "long")
    hybrid = HybridBackend(long_term)
    # Direct short-term write bypasses long-term
    await hybrid.set("k", "short", persist=False)
    assert await hybrid.get("k") == "short"


async def test_hybrid_clear_session_preserves_long_term():
    long_term = DictBackend()
    hybrid = HybridBackend(long_term)
    await hybrid.set("k", "v")
    await hybrid.clear_session()
    # Long-term still has it
    assert await long_term.get("k") == "v"
    # Hybrid falls back to long-term and re-caches
    assert await hybrid.get("k") == "v"


async def test_hybrid_warms_cache_on_miss():
    long_term = DictBackend()
    await long_term.set("k", "v")
    hybrid = HybridBackend(long_term)
    assert await hybrid.get("k") == "v"
    # Now in short-term too
    assert await hybrid._short.get("k") == "v"


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
    # Mom2 has no public method or reference to read mom1
    assert not hasattr(mom2, "mom1")
    assert not hasattr(mom3, "mom1")


async def test_shared_zone_read_write_from_both():
    shared = SharedZone(DictBackend())
    mom2 = Mom2(DictBackend(), shared)
    mom3 = Mom3(DictBackend(), shared)

    await mom2.shared.set("handoff", "x")
    assert await mom3.shared.get("handoff") == "x"

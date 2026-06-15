"""P1-A tests: the markdown-as-source-of-truth memory backend.

Covers the raw MemoryBackend KV contract (round-trip, keys, delete, clear),
the per-entry 4D-frontmatter history format, eviction file-sync, human
readability, and that a full MemoryArea works unchanged over it.
"""
from autumn.core.memory.backends import MarkdownBackend
from autumn.core.memory.base import MemoryArea, MemoryEntry
from autumn.core.memory.dimensions import Aim, Trigger, Use, UseMode


# ── raw KV contract ─────────────────────────────────────────────────────────────

async def test_kv_string_round_trip(tmp_path):
    b = MarkdownBackend(tmp_path)
    await b.set("mom1:name", "autumn")
    assert await b.get("mom1:name") == "autumn"


async def test_kv_json_round_trip(tmp_path):
    b = MarkdownBackend(tmp_path)
    value = {"a": 1, "b": [1, 2, 3], "c": None}
    await b.set("shared:cfg", value)
    assert await b.get("shared:cfg") == value


async def test_get_missing_returns_none(tmp_path):
    b = MarkdownBackend(tmp_path)
    assert await b.get("mom1:nope") is None
    assert await b.get("mom1:history") is None


async def test_delete_kv(tmp_path):
    b = MarkdownBackend(tmp_path)
    await b.set("mom1:k", "v")
    await b.delete("mom1:k")
    assert await b.get("mom1:k") is None


async def test_keys_lists_history_and_kv(tmp_path):
    b = MarkdownBackend(tmp_path)
    await b.set("mom1:name", "autumn")
    await b.set("mom1:history", [
        MemoryEntry(id="e1", content="hi", timestamp=1.0).to_dict(),
    ])
    keys = set(await b.keys())
    assert "mom1:name" in keys
    assert "mom1:history" in keys


async def test_clear_wipes_everything(tmp_path):
    b = MarkdownBackend(tmp_path)
    await b.set("mom1:k", "v")
    await b.set("mom1:history", [MemoryEntry(id="e1", content="x", timestamp=1.0).to_dict()])
    await b.clear()
    assert await b.keys() == []


# ── history: 4D round-trip + readability ────────────────────────────────────────

async def test_history_round_trip_preserves_4d_dimensions(tmp_path):
    b = MarkdownBackend(tmp_path)
    entry = MemoryEntry(
        id="deploy1",
        content="生产库必须走只读副本",
        timestamp=1718412345.0,
        importance=1.0,
        tags=["deploy", "db"],
        aim=Aim(intent="deploy_guardrail", goal_ref="goal:ship-v2", scope=["deploy"]),
        use=Use(mode=UseMode.CONSTRAIN, weight=2.0),
        trigger=Trigger(cues=["部署"], base_weight=1.0),
    )
    await b.set("mom1:history", [entry.to_dict()])

    loaded = await b.get("mom1:history")
    assert len(loaded) == 1
    rt = MemoryEntry.from_dict(loaded[0])
    assert rt.id == "deploy1"
    assert rt.content == "生产库必须走只读副本"
    assert rt.tags == ["deploy", "db"]
    assert rt.aim.intent == "deploy_guardrail"
    assert rt.aim.goal_ref == "goal:ship-v2"
    assert rt.use.mode is UseMode.CONSTRAIN
    assert rt.use.weight == 2.0
    assert rt.trigger.cues == ["部署"]


async def test_history_file_is_human_readable(tmp_path):
    b = MarkdownBackend(tmp_path)
    await b.set("mom1:history", [
        MemoryEntry(id="r1", content="readable body text", timestamp=1.0,
                    tags=["x"]).to_dict(),
    ])
    md = (tmp_path / "mom1" / "r1.md").read_text(encoding="utf-8")
    assert md.startswith("---")
    assert 'id: "r1"' in md
    assert 'tags: ["x"]' in md
    assert md.rstrip().endswith("readable body text")  # content is the body


async def test_history_set_syncs_deletions(tmp_path):
    b = MarkdownBackend(tmp_path)
    three = [
        MemoryEntry(id=f"e{i}", content=str(i), timestamp=float(i)).to_dict()
        for i in range(3)
    ]
    await b.set("mom1:history", three)
    assert {p.stem for p in (tmp_path / "mom1").glob("*.md")} == {"e0", "e1", "e2"}
    # Re-write with one fewer → the dropped entry's file is removed.
    await b.set("mom1:history", three[:2])
    assert {p.stem for p in (tmp_path / "mom1").glob("*.md")} == {"e0", "e1"}


async def test_history_returns_entries_in_timestamp_order(tmp_path):
    b = MarkdownBackend(tmp_path)
    await b.set("mom1:history", [
        MemoryEntry(id="late", content="late", timestamp=9.0).to_dict(),
        MemoryEntry(id="early", content="early", timestamp=1.0).to_dict(),
    ])
    loaded = await b.get("mom1:history")
    assert [e["id"] for e in loaded] == ["early", "late"]


# ── integration: a full MemoryArea over the markdown backend ────────────────────

async def test_memory_area_append_and_recent(tmp_path):
    area = MemoryArea("mom1", MarkdownBackend(tmp_path))
    await area.append_history("first", tags=["t"])
    await area.append_history("second", tags=["t"])
    recent = await area.recent(2)
    assert [e.text for e in recent] == ["first", "second"]


async def test_memory_area_kv_and_recall(tmp_path):
    area = MemoryArea("mom1", MarkdownBackend(tmp_path))
    await area.set("city", "Hangzhou")
    res = await area.recall("city")
    assert res and res[0].content == "Hangzhou"


async def test_memory_area_persists_across_instances(tmp_path):
    area1 = MemoryArea("mom1", MarkdownBackend(tmp_path))
    await area1.append_history("durable fact", tags=["keep"])
    # A fresh backend over the same dir sees the persisted entry.
    area2 = MemoryArea("mom1", MarkdownBackend(tmp_path))
    hist = await area2.get_history(tags=["keep"])
    assert len(hist) == 1
    assert hist[0].text == "durable fact"


async def test_memory_area_eviction_persists(tmp_path):
    area = MemoryArea("mom1", MarkdownBackend(tmp_path), history_limit=2)
    for i in range(5):
        await area.append_history(f"m{i}", importance=1.0)
    files = list((tmp_path / "mom1").glob("*.md"))
    assert len(files) == 2  # capacity enforced on disk, not just in memory

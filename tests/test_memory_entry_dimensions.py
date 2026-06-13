"""P1 tests: MemoryEntry carries the 4D dimensions through construction,
serialization (schema v2), backward-compatible loading of v1/legacy records,
and a round-trip through a MemoryArea's history. No activation logic runs yet —
this phase only proves the dimensions are stored and restored intact.
"""
import json

from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea, MemoryEntry
from autumn.core.memory.dimensions import Aim, Trigger, Use, UseMode


def _entry(**kw) -> MemoryEntry:
    base = dict(id="e1", content="hello", timestamp=42.0)
    base.update(kw)
    return MemoryEntry(**base)


# ── defaults & backward-compatible construction ───────────────────────────────

def test_new_entry_has_empty_dimension_defaults():
    e = _entry()
    assert e.aim.is_empty()
    assert e.use.mode is UseMode.CONTEXT and e.use.stats.count == 0
    assert e.trigger.half_life is None and e.trigger.base_weight == 1.0


def test_two_default_entries_are_equal():
    # Dataclass equality must still hold with the added fields, or callers that
    # compare entries would break.
    assert _entry() == _entry()


def test_existing_behavior_unchanged():
    # importance/expiry helpers must be untouched by the new fields.
    e = _entry(importance=1.5, expires_at=100.0)
    assert e.is_pinned is True
    assert e.is_expired(now=100.0) is True
    assert e.is_expired(now=99.0) is False


# ── serialization (schema v2) ─────────────────────────────────────────────────

def test_to_dict_is_versioned_and_carries_dimensions():
    e = _entry(
        aim=Aim(intent="deploy", goal_ref="goal:v2", scope=["db"]),
        use=Use(mode=UseMode.CONSTRAIN, weight=2.0),
        trigger=Trigger(half_life=30.0, cues=["deploy"]),
    )
    d = e.to_dict()
    assert d["_m"] is True and d["_v"] == 2
    assert d["aim"]["goal_ref"] == "goal:v2"
    assert d["use"]["mode"] == "constrain"
    assert d["trigger"]["half_life"] == 30.0


def test_round_trip_preserves_dimensions():
    e = _entry(
        aim=Aim(intent="pref", scope=["ui", "theme"]),
        use=Use(mode=UseMode.REMIND, weight=1.5, template="note: {x}"),
        trigger=Trigger(not_before=10.0, every=60.0, cues=["a"], base_weight=2.0),
    )
    e.use.touch(now=5.0, reward=0.5)
    back = MemoryEntry.from_dict(e.to_dict())
    assert back.aim == e.aim
    assert back.use == e.use            # includes UseStats (count/last_used/reward)
    assert back.trigger == e.trigger


def test_json_serialization_is_safe():
    # The SQLite backend persists to_dict() via json.dumps — ensure the Enum and
    # nested dataclasses survive a real JSON round-trip.
    e = _entry(use=Use(mode=UseMode.SUMMARIZE), trigger=Trigger(half_life=12.0))
    back = MemoryEntry.from_dict(json.loads(json.dumps(e.to_dict())))
    assert back.use.mode is UseMode.SUMMARIZE
    assert back.trigger.half_life == 12.0


# ── loading v1 / legacy records ───────────────────────────────────────────────

def test_v1_record_without_dimensions_loads_with_defaults():
    # A pre-4D serialized entry (no _v, no aim/use/trigger keys).
    v1 = {"_m": True, "id": "old", "content": "x", "timestamp": 1.0, "importance": 1.0}
    e = MemoryEntry.from_dict(v1)
    assert e.id == "old"
    assert e.aim.is_empty()
    assert e.use.mode is UseMode.CONTEXT
    assert e.trigger == Trigger()


def test_legacy_raw_dict_still_upgrades():
    # A bare workspace dict with no _m marker (oldest format).
    e = MemoryEntry.from_dict({"ts": 7.0, "input": "hi", "output": "there"})
    assert e.timestamp == 7.0
    assert e.aim.is_empty() and e.trigger == Trigger()


def test_unknown_use_mode_falls_back_to_context():
    raw = {
        "_m": True, "_v": 2, "id": "u", "content": "c", "timestamp": 1.0,
        "use": {"mode": "telepathy", "weight": 1.0, "stats": {}},
    }
    e = MemoryEntry.from_dict(raw)
    assert e.use.mode is UseMode.CONTEXT


# ── round-trip through a MemoryArea's history ─────────────────────────────────

async def test_append_history_with_dimensions_persists():
    area = MemoryArea("t", DictBackend())
    await area.append_history(
        "remember the db host",
        aim=Aim(intent="deploy_fact", goal_ref="goal:v2"),
        use=Use(mode=UseMode.CONSTRAIN),
        trigger=Trigger(cues=["deploy", "db"], half_life=None),
    )
    [e] = await area.get_history()
    assert e.aim.goal_ref == "goal:v2"
    assert e.use.mode is UseMode.CONSTRAIN
    assert e.trigger.cues == ["deploy", "db"]


async def test_append_history_without_dimensions_is_unchanged():
    area = MemoryArea("t", DictBackend())
    await area.append_history("plain entry")
    [e] = await area.get_history()
    assert e.aim.is_empty()
    assert e.use.stats.count == 0
    assert e.trigger == Trigger()

"""P3-A tests: self-evolution — recurring, proven-useful memories → pinned skills.

Contract: evolve clusters non-derived history by aim.intent, keeps clusters whose
members were reinforced (use.count >= min_count) and number >= min_cluster, and
distils each into one pinned CASE entry with CONSTRAIN mode + the shared intent.
Idempotent across re-runs; never feeds on its own output.
"""
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea
from autumn.core.memory.dimensions import UseMode
from autumn.core.memory.kinds import KIND_CASE


class _RuleAPI:
    def __init__(self, rule: str):
        self.rule = rule
        self.calls = 0

    async def complete(self, messages):
        self.calls += 1
        return self.rule


async def _seed_used_cluster(area, intent, texts, count):
    """Append entries, annotate them with *intent*, and reinforce *count* times."""
    ids = []
    for t in texts:
        e = await area.append_history(t)
        await area.annotate(e.id, intent=intent)
        ids.append(e.id)
    for _ in range(count):
        await area.reinforce(ids)
    return ids


# ── happy path ──────────────────────────────────────────────────────────────────

async def test_evolve_distils_recurring_cluster_into_pinned_skill():
    area = MemoryArea("mom1", DictBackend())
    await _seed_used_cluster(
        area, "db_access",
        ["used read replica for prod reads", "again routed reads to the replica"],
        count=2,
    )
    api = _RuleAPI("Always route production DB reads through a read replica.")
    skills = await area.evolve(api, min_count=2, min_cluster=2)

    assert len(skills) == 1
    s = skills[0]
    assert s.content == "Always route production DB reads through a read replica."
    assert KIND_CASE in s.tags
    assert s.aim.intent == "db_access"
    assert s.use.mode is UseMode.CONSTRAIN
    assert s.is_pinned
    assert s.meta.get("evolved") is True


# ── thresholds ──────────────────────────────────────────────────────────────────

async def test_evolve_skips_under_used_cluster():
    area = MemoryArea("mom1", DictBackend())
    await _seed_used_cluster(area, "x", ["a", "b"], count=1)  # count=1 < min_count=2
    assert await area.evolve(_RuleAPI("rule"), min_count=2, min_cluster=2) == []


async def test_evolve_skips_small_cluster():
    area = MemoryArea("mom1", DictBackend())
    await _seed_used_cluster(area, "solo", ["only one"], count=3)  # 1 member < min_cluster=2
    assert await area.evolve(_RuleAPI("rule"), min_count=2, min_cluster=2) == []


async def test_evolve_ignores_unannotated_entries():
    area = MemoryArea("mom1", DictBackend())
    e1 = await area.append_history("no intent here")
    e2 = await area.append_history("also no intent")
    await area.reinforce([e1.id, e2.id])
    await area.reinforce([e1.id, e2.id])
    assert await area.evolve(_RuleAPI("rule"), min_count=2, min_cluster=2) == []


# ── idempotence + no self-feeding ───────────────────────────────────────────────

async def test_evolve_is_idempotent_per_intent():
    area = MemoryArea("mom1", DictBackend())
    await _seed_used_cluster(area, "dup", ["x1", "x2"], count=2)
    api = _RuleAPI("the rule")
    first = await area.evolve(api, min_count=2, min_cluster=2)
    assert len(first) == 1
    # Second run: the intent already has a CASE skill → nothing new.
    second = await area.evolve(api, min_count=2, min_cluster=2)
    assert second == []


async def test_evolve_no_candidates_is_noop():
    area = MemoryArea("mom1", DictBackend())
    api = _RuleAPI("rule")
    assert await area.evolve(api) == []
    assert api.calls == 0

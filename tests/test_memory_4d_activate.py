"""P3 tests: the use-dimension feedback loop.

``MemoryArea.reinforce`` records that entries were used; ``WP4.activate`` is the
pull entry point that recalls and reinforces. Together they close the loop:
repeatedly-used memories gain utility and rank higher on later recall.
"""
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea
from autumn.core.memory.project import ProjectMemory
from autumn.core.memory.shared import SharedZone
from autumn.core.workspace.wp4 import WP4Mem


class _StubAPI:
    async def complete(self, messages, **kwargs):
        return "digest"


def _wp4(api=None) -> WP4Mem:
    backend = DictBackend()
    return WP4Mem(
        api,
        MemoryArea("wp4", backend),
        zones={
            "mom1": MemoryArea("mom1", backend),
            "mom2": MemoryArea("mom2", backend),
            "mom3": MemoryArea("mom3", backend),
            "shared": SharedZone(backend),
        },
        projects=ProjectMemory(DictBackend()),
    )


# ── reinforce primitive ────────────────────────────────────────────────────────

async def test_reinforce_increments_use_stats_and_persists():
    area = MemoryArea("t", DictBackend())
    e = await area.append_history("x")
    n = await area.reinforce([e.id], reward=0.3)
    assert n == 1
    [stored] = await area.get_history()
    assert stored.use.stats.count == 1
    assert stored.use.stats.reward == 0.3
    assert stored.use.stats.last_used is not None


async def test_reinforce_accumulates_across_calls():
    area = MemoryArea("t", DictBackend())
    e = await area.append_history("x")
    await area.reinforce([e.id], reward=0.5)
    await area.reinforce([e.id], reward=0.25)
    [stored] = await area.get_history()
    assert stored.use.stats.count == 2
    assert stored.use.stats.reward == 0.75


async def test_reinforce_ignores_unknown_and_empty_ids():
    area = MemoryArea("t", DictBackend())
    await area.append_history("x")
    assert await area.reinforce([]) == 0
    assert await area.reinforce(["nope", "kv:foo"]) == 0
    [stored] = await area.get_history()
    assert stored.use.stats.count == 0  # untouched


# ── end-to-end feedback loop ────────────────────────────────────────────────────

async def test_reinforcement_raises_future_recall_rank():
    area = MemoryArea("t", DictBackend(), fourd_enabled=True)
    alpha = await area.append_history("alpha", tags=["q"])
    await area.append_history("beta", tags=["q"])  # newer → wins ties by recency

    # Before any reinforcement, recency puts 'beta' first.
    before = await area.recall("q", tags=["q"])
    assert before[0].content == "beta"

    # Reinforce 'alpha' repeatedly → its utility climbs.
    for _ in range(15):
        await area.reinforce([alpha.id], reward=0.5)

    after = await area.recall("q", tags=["q"])
    assert after[0].content == "alpha"  # utility now beats recency


async def test_reinforcement_inert_when_flag_off():
    # Same loop, flag off → recall ignores utility, recency still wins.
    area = MemoryArea("t", DictBackend(), fourd_enabled=False)
    alpha = await area.append_history("alpha", tags=["q"])
    await area.append_history("beta", tags=["q"])
    for _ in range(15):
        await area.reinforce([alpha.id], reward=0.5)
    res = await area.recall("q", tags=["q"])
    assert res[0].content == "beta"


# ── WP4.activate ────────────────────────────────────────────────────────────────

async def test_activate_returns_hits_and_reinforces():
    wp4 = _wp4()
    shared = wp4._resolve("shared")
    await shared.append_history("fact", tags=["topic"])
    out = await wp4.activate("topic", area="shared", tags=["topic"])
    assert any(e.content == "fact" for e in out)
    [stored] = await shared.get_history()
    assert stored.use.stats.count == 1  # hit was reinforced


async def test_activate_reward_propagates():
    wp4 = _wp4()
    shared = wp4._resolve("shared")
    await shared.append_history("fact", tags=["topic"])
    await wp4.activate("topic", area="shared", tags=["topic"], reward=0.8)
    [stored] = await shared.get_history()
    assert stored.use.stats.reward == 0.8


async def test_activate_can_skip_reinforcement():
    wp4 = _wp4()
    shared = wp4._resolve("shared")
    await shared.append_history("fact", tags=["topic"])
    await wp4.activate("topic", area="shared", tags=["topic"], reinforce=False)
    [stored] = await shared.get_history()
    assert stored.use.stats.count == 0


async def test_activate_is_audited():
    wp4 = _wp4()
    shared = wp4._resolve("shared")
    await shared.append_history("fact", tags=["topic"])
    await wp4.activate("topic", area="shared", tags=["topic"])
    log = await wp4.audit_log()
    assert any(
        isinstance(e.content, dict) and e.content.get("action") == "activate"
        for e in log
    )


async def test_activate_without_model_works():
    # activate is pure retrieval + reinforcement; no A4 needed.
    wp4 = _wp4(api=None)
    assert wp4.has_model is False
    shared = wp4._resolve("shared")
    await shared.append_history("fact", tags=["topic"])
    out = await wp4.activate("topic", area="shared", tags=["topic"])
    assert len(out) == 1

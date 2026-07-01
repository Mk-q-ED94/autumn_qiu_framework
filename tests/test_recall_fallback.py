"""Recall must retrieve on the default (search-less) backend.

Before the in-process keyword fallback, MemoryArea.recall skipped its
semantic/lexical step whenever no vector or lexical layer was attached — which
is the default — so a natural-language query returned nothing even when the fact
was stored verbatim. These tests lock in that recall now surfaces relevant
entries with zero external dependencies, in both Chinese and English.
"""
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea, _query_terms


# ── tokenizer ───────────────────────────────────────────────────────────────

def test_query_terms_latin():
    terms = _query_terms("Dark Mode 2")
    assert "dark" in terms and "mode" in terms and "2" in terms


def test_query_terms_cjk_bigrams():
    terms = _query_terms("乌龙茶")
    assert {"乌", "龙", "茶", "乌龙", "龙茶"} <= terms


# ── recall fallback (no vector, no lexical) ───────────────────────────────────

async def test_recall_finds_chinese_fact_without_backend():
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("用户说他喜欢喝乌龙茶")
    await area.append_history("今天天气不错")  # distractor

    hits = await area.recall("我喜欢喝什么茶", k=3)
    assert any("乌龙茶" in h.text for h in hits), [h.text for h in hits]


async def test_recall_finds_english_fact_without_backend():
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("The user prefers dark mode in the editor")
    await area.append_history("Deploy runs on Fridays")  # distractor

    hits = await area.recall("what mode does the user like", k=3)
    assert any("dark mode" in h.text.lower() for h in hits), [h.text for h in hits]


async def test_recall_ranks_more_overlap_first():
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("apple banana cherry date")   # 3 overlaps
    await area.append_history("apple orange")               # 1 overlap
    hits = await area.recall("apple banana cherry", k=2)
    assert hits[0].text.startswith("apple banana cherry")


async def test_recall_no_overlap_returns_empty():
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("completely unrelated content")
    hits = await area.recall("xyzzy plugh", k=3)
    assert hits == []


async def test_recall_returns_real_entries_that_reinforce():
    """Fallback hits are real history entries, so reinforce() can touch them."""
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("the deploy target is fly.io")
    hits = await area.recall("where do we deploy", k=3)
    assert hits
    updated = await area.reinforce([h.id for h in hits])
    assert updated >= 1  # real ids, not synthetic kv:/vector ids

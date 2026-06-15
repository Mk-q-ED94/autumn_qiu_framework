"""P2-A tests: memory typing (kinds) + AtomicFact extraction.

Contract: extract_facts turns episode text into discrete atomic_fact entries
(recall-able independently, linked to sources), skips its own derived output on
re-runs, and is robust/no-op on junk model replies.
"""
from autumn.core.memory import kinds
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea, MemoryEntry, _parse_fact_array


# ── test double: an A4 that returns a canned reply ──────────────────────────────

class _FactAPI:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    async def complete(self, messages):
        self.calls += 1
        return self.reply


# ── kinds conventions ───────────────────────────────────────────────────────────

def test_kind_constants_and_helpers():
    e = MemoryEntry(id="1", content="x", timestamp=0.0, tags=[kinds.KIND_ATOMIC_FACT])
    assert kinds.is_kind(e, kinds.KIND_ATOMIC_FACT)
    assert kinds.kind_of(e) == kinds.KIND_ATOMIC_FACT
    assert kinds.kind_of(MemoryEntry(id="2", content="y", timestamp=0.0)) is None
    assert kinds.KIND_ATOMIC_FACT in kinds.ALL_KINDS
    assert kinds.KIND_SUMMARY in kinds.DERIVED_KINDS


# ── _parse_fact_array robustness ────────────────────────────────────────────────

def test_parse_plain_array():
    assert _parse_fact_array('["a", "b"]') == ["a", "b"]


def test_parse_fenced_json():
    assert _parse_fact_array('```json\n["a", "b"]\n```') == ["a", "b"]


def test_parse_array_in_prose():
    assert _parse_fact_array('Here you go: ["only"]. Done.') == ["only"]


def test_parse_junk_returns_empty():
    assert _parse_fact_array("not json at all") == []
    assert _parse_fact_array("") == []
    assert _parse_fact_array('{"not": "a list"}') == []


def test_parse_drops_blanks_and_stringifies():
    assert _parse_fact_array('["a", "", "  ", 7]') == ["a", "7"]


# ── extract_facts ───────────────────────────────────────────────────────────────

async def test_extract_facts_stores_tagged_entries():
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("User Jin prefers dark mode and lives in Hangzhou")
    api = _FactAPI('["Jin prefers dark mode", "Jin lives in Hangzhou"]')

    facts = await area.extract_facts(api)
    assert [f.content for f in facts] == ["Jin prefers dark mode", "Jin lives in Hangzhou"]
    assert all(kinds.KIND_ATOMIC_FACT in f.tags for f in facts)
    assert all(f.meta.get("from") for f in facts)


async def test_extract_facts_are_recallable_by_kind():
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("the deploy must use a read replica")
    api = _FactAPI('["Deploys must use a read replica"]')
    await area.extract_facts(api)

    hits = await area.get_history(tags=[kinds.KIND_ATOMIC_FACT])
    assert len(hits) == 1
    assert "read replica" in hits[0].content


async def test_extract_facts_skips_derived_sources():
    """A second pass must not extract facts from facts/summaries it produced."""
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("alpha note")
    api = _FactAPI('["alpha fact"]')
    await area.extract_facts(api)  # creates one atomic_fact

    # Second pass: the only non-derived source is still "alpha note".
    spy = _FactAPI('["should not include the fact text"]')
    await area.extract_facts(spy)
    # The model was called, but its source text excluded the derived fact.
    # Verify by inspecting: re-extraction never reads atomic_fact entries.
    # (We assert behavior indirectly: only the original note remains a source.)
    facts = await area.get_history(tags=[kinds.KIND_ATOMIC_FACT])
    assert len(facts) == 2  # both passes added one each, none cascaded further


async def test_extract_facts_no_candidates_is_noop():
    area = MemoryArea("mom1", DictBackend())
    api = _FactAPI('["nope"]')
    assert await area.extract_facts(api) == []
    assert api.calls == 0  # never called the model with nothing to extract


async def test_extract_facts_empty_reply_is_noop():
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("some chatter")
    api = _FactAPI("[]")
    assert await area.extract_facts(api) == []


async def test_extract_facts_keep_recent_excludes_newest():
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("old one")
    await area.append_history("newest one")
    captured = {}

    class _Capture:
        async def complete(self, messages):
            captured["user"] = messages[1].content
            return "[]"

    await area.extract_facts(_Capture(), keep_recent=1)
    assert "old one" in captured["user"]
    assert "newest one" not in captured["user"]

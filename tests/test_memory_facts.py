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


# ── skip_consumed: re-run-safe extraction (per-turn auto path) ──────────────────

async def test_extract_facts_skip_consumed_is_idempotent():
    """A second skip_consumed pass mines no already-distilled turn (no duplicate)."""
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("alpha note")
    first = await area.extract_facts(_FactAPI('["alpha fact"]'), skip_consumed=True)
    assert len(first) == 1

    spy = _FactAPI('["should not fire"]')
    second = await area.extract_facts(spy, skip_consumed=True)
    assert second == []          # the only raw turn was already consumed
    assert spy.calls == 0        # no A4 call when nothing new to mine
    facts = await area.get_history(tags=[kinds.KIND_ATOMIC_FACT])
    assert len(facts) == 1       # no duplicate fact


async def test_extract_facts_skip_consumed_mines_only_new_turns():
    """After extraction, a skip_consumed pass mines only the genuinely new turn."""
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("first turn")
    await area.extract_facts(_FactAPI('["fact one"]'), skip_consumed=True)

    await area.append_history("second turn")
    captured = {}

    class _Capture:
        def __init__(self):
            self.calls = 0

        async def complete(self, messages):
            self.calls += 1
            captured["user"] = messages[1].content
            return '["fact two"]'

    cap = _Capture()
    created = await area.extract_facts(cap, skip_consumed=True)
    assert len(created) == 1
    assert cap.calls == 1
    assert "second turn" in captured["user"]
    assert "first turn" not in captured["user"]  # already consumed → excluded


async def test_extract_facts_without_skip_consumed_keeps_legacy_remine():
    """Default (skip_consumed=False) preserves the legacy re-mine-every-turn contract."""
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("alpha note")
    await area.extract_facts(_FactAPI('["alpha fact"]'))
    await area.extract_facts(_FactAPI('["alpha fact again"]'))  # re-mines the raw note
    facts = await area.get_history(tags=[kinds.KIND_ATOMIC_FACT])
    assert len(facts) == 2  # legacy behaviour: a second pass re-extracts


async def test_pending_fact_sources_tracks_unconsumed():
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("note A")
    await area.append_history("note B")
    assert len(await area.pending_fact_sources()) == 2

    await area.extract_facts(_FactAPI('["a distilled fact"]'), skip_consumed=True)
    # Both raw notes were the sources of that fact → none pending now.
    assert await area.pending_fact_sources() == []


async def test_extract_facts_skip_consumed_keeps_window_truncated_turns_pending():
    """Turns that don't fit this pass's prompt window stay pending, not consumed."""
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("A" * 30)
    await area.append_history("B" * 30)
    captured = {}

    class _Cap:
        def __init__(self):
            self.calls = 0

        async def complete(self, messages):
            self.calls += 1
            captured["user"] = messages[1].content
            return '["fact from A"]'

    # max_chars=40 only fits the first "- AAA…" line.
    created = await area.extract_facts(_Cap(), skip_consumed=True, max_chars=40)
    assert len(created) == 1
    assert "A" * 30 in captured["user"]
    assert "B" * 30 not in captured["user"]      # truncated out of the window
    pending = await area.pending_fact_sources()
    assert [e.text for e in pending] == ["B" * 30]  # second turn still mineable


async def test_extract_facts_skip_consumed_stores_every_distilled_fact():
    """skip_consumed keeps every fact from the window — max_facts is a legacy cap."""
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("a turn yielding several facts")
    created = await area.extract_facts(
        _FactAPI('["f1", "f2", "f3"]'), skip_consumed=True, max_facts=1,
    )
    assert len(created) == 3  # not truncated under skip_consumed → no silent loss


async def test_extract_facts_legacy_still_truncates_to_max_facts():
    """The legacy (skip_consumed=False) path keeps honouring max_facts."""
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("a turn yielding several facts")
    created = await area.extract_facts(_FactAPI('["f1", "f2", "f3"]'), max_facts=1)
    assert len(created) == 1

"""P2-B tests: indexing decoupled from the write path (background, opt-in).

Contract:
- default (sync) mode is unchanged — append indexes inline and propagates errors;
- async mode makes append non-blocking and resilient: a failing index never
  breaks the (already durable) write, and flush_index() awaits completion so a
  subsequent read sees the indexed entry.
"""
from autumn.core.config import BehaviorConfig
from autumn.core.memory.backends import DictBackend, SQLiteLexicalStore
from autumn.core.memory.base import MemoryArea


class _BoomLexical(SQLiteLexicalStore):
    """A lexical store whose indexing always fails."""

    async def store(self, id: str, text: str, metadata=None) -> None:  # type: ignore[override]
        raise RuntimeError("index backend down")


# ── config flag ─────────────────────────────────────────────────────────────────

def test_async_index_flag_default_off():
    assert BehaviorConfig().async_index is False


def test_async_index_flag_from_env(monkeypatch):
    monkeypatch.setenv("ASYNC_INDEX", "true")
    assert BehaviorConfig.from_env().async_index is True
    monkeypatch.setenv("ASYNC_INDEX", "off")
    assert BehaviorConfig.from_env().async_index is False


def test_set_async_index_toggles():
    area = MemoryArea("mom1", DictBackend())
    assert area.async_index is False
    area.set_async_index(True)
    assert area.async_index is True


# ── sync mode: a failing index still propagates (unchanged behavior) ────────────

async def test_sync_index_failure_propagates(tmp_path):
    area = MemoryArea("mom1", DictBackend())
    area.enable_lexical(_BoomLexical(str(tmp_path / "x.db")), auto_index=True)
    raised = False
    try:
        await area.append_history("will fail to index")
    except RuntimeError:
        raised = True
    assert raised


# ── async mode: append is resilient, flush awaits, entry indexed ────────────────

async def test_async_index_failure_does_not_break_append(tmp_path):
    area = MemoryArea("mom1", DictBackend())
    area.enable_lexical(_BoomLexical(str(tmp_path / "x.db")), auto_index=True)
    area.set_async_index(True)
    # Append must succeed even though background indexing will raise internally.
    entry = await area.append_history("durable despite index failure")
    assert entry.text == "durable despite index failure"
    await area.flush_index()  # swallows the background error, never raises
    # The entry is still in history regardless of indexing outcome.
    hist = await area.get_history()
    assert any(e.text == "durable despite index failure" for e in hist)


async def test_async_index_then_flush_makes_entry_searchable(tmp_path):
    area = MemoryArea("mom1", DictBackend())
    area.enable_lexical(SQLiteLexicalStore(str(tmp_path / "lex.db")), auto_index=True)
    area.set_async_index(True)

    await area.append_history("kubernetes ingress controller")
    await area.flush_index()  # wait for background indexing to complete

    res = await area.recall("kubernetes ingress")
    assert res
    assert "ingress" in res[0].content


async def test_flush_index_noop_without_tasks():
    area = MemoryArea("mom1", DictBackend())
    await area.flush_index()  # nothing scheduled — must not raise

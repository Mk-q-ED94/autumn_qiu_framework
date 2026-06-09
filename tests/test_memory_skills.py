"""Tests for the memory-backed recall/remember/list_recent/pin_memory Skills."""
import pytest

from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea
from autumn.core.memory.skills import make_memory_skills


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_memory(name: str = "test") -> MemoryArea:
    return MemoryArea(name, DictBackend())


def _skills(mem, api=None):
    skills = make_memory_skills(mem, api=api)
    return skills[0], skills[1], skills[2], skills[3]  # recall, remember, list_recent, pin_memory


class _FakeAPI:
    def __init__(self, answer: str):
        self._answer = answer

    async def complete(self, messages, **kwargs) -> str:
        return self._answer


# ── basic recall/remember ─────────────────────────────────────────────────────


async def test_remember_stores_string():
    mem = _make_memory()
    recall, remember, _, _ = _skills(mem)
    result = await remember.execute(key="city", value="Beijing")
    assert "[remembered 'city']" == result
    assert await mem.get("city") == "Beijing"


async def test_recall_exact_key_hit():
    mem = _make_memory()
    await mem.set("lang", "Python")
    recall, _, _, _ = _skills(mem)
    result = await recall.execute(query="lang")
    assert result == "Python"


async def test_recall_missing_returns_message():
    mem = _make_memory()
    recall, _, _, _ = _skills(mem)
    result = await recall.execute(query="nonexistent")
    assert "no memory found" in result


async def test_recall_after_remember():
    mem = _make_memory()
    recall, remember, _, _ = _skills(mem)
    await remember.execute(key="project", value="Autumn")
    result = await recall.execute(query="project")
    assert result == "Autumn"


async def test_recall_dict_value_as_json():
    mem = _make_memory()
    await mem.set("config", {"a": 1, "b": 2})
    recall, _, _, _ = _skills(mem)
    result = await recall.execute(query="config")
    import json
    assert json.loads(result) == {"a": 1, "b": 2}


async def test_recall_list_value_as_json():
    mem = _make_memory()
    await mem.set("tags", ["fast", "reliable"])
    recall, _, _, _ = _skills(mem)
    result = await recall.execute(query="tags")
    import json
    assert json.loads(result) == ["fast", "reliable"]


# ── skill schema ──────────────────────────────────────────────────────────────


def test_skill_names():
    mem = _make_memory()
    skills = make_memory_skills(mem)
    assert skills[0].name == "recall"
    assert skills[1].name == "remember"
    assert skills[2].name == "list_recent"
    assert skills[3].name == "pin_memory"


def test_recall_schema_has_query_param():
    mem = _make_memory()
    recall, _, _, _ = _skills(mem)
    assert any(p.name == "query" for p in recall.parameters)


def test_remember_schema_has_key_and_value():
    mem = _make_memory()
    _, remember, _, _ = _skills(mem)
    names = {p.name for p in remember.parameters}
    assert names == {"key", "value"}


def test_openai_schema_structure():
    mem = _make_memory()
    recall, _, _, _ = _skills(mem)
    schema = recall.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "recall"
    assert "query" in schema["function"]["parameters"]["properties"]


def test_anthropic_schema_structure():
    mem = _make_memory()
    recall, _, _, _ = _skills(mem)
    schema = recall.to_anthropic_schema()
    assert schema["name"] == "recall"
    assert "query" in schema["input_schema"]["properties"]


# ── A4 synthesis path ─────────────────────────────────────────────────────────


async def test_recall_no_vector_skips_api():
    mem = _make_memory()
    api = _FakeAPI("should not appear")
    recall, _, _, _ = _skills(mem, api=api)
    result = await recall.execute(query="unknown")
    assert "no memory found" in result
    assert "should not appear" not in result


async def test_recall_with_api_none_returns_snippets(monkeypatch):
    from autumn.core.memory.base import MemoryArea, _VectorLayer

    class _FakeResult:
        score = 0.95
        text = "Berlin is the capital"
        id = "x1"

    class _FakeStore:
        async def search(self, vec, k): return [_FakeResult()]

    class _FakeEmbedding:
        async def embed(self, text): return [0.1]

    mem = _make_memory()
    mem._vector = _VectorLayer(_FakeEmbedding(), _FakeStore())
    recall, _, _, _ = _skills(mem, api=None)
    result = await recall.execute(query="capital of Germany")
    assert "Berlin is the capital" in result
    assert "relevance=" in result


async def test_recall_with_api_synthesises_results(monkeypatch):
    from autumn.core.memory.base import MemoryArea, _VectorLayer

    class _FakeResult:
        score = 0.9
        text = "Paris is the capital of France"
        id = "y1"

    class _FakeStore:
        async def search(self, vec, k): return [_FakeResult()]

    class _FakeEmbedding:
        async def embed(self, text): return [0.1]

    mem = _make_memory()
    mem._vector = _VectorLayer(_FakeEmbedding(), _FakeStore())
    api = _FakeAPI("Paris")
    recall, _, _, _ = _skills(mem, api=api)
    result = await recall.execute(query="capital of France")
    assert result == "Paris"


# ── remember + vector auto-index ─────────────────────────────────────────────


async def test_remember_indexes_when_vector_enabled(monkeypatch):
    from autumn.core.memory.base import MemoryArea, _VectorLayer

    indexed: list[tuple] = []

    class _FakeStore:
        async def store(self, id, text, vector, metadata): indexed.append((id, text))

    class _FakeEmbedding:
        async def embed(self, text): return [0.5]

    mem = _make_memory()
    mem._vector = _VectorLayer(_FakeEmbedding(), _FakeStore())
    _, remember, _, _ = _skills(mem)
    await remember.execute(key="fact", value="The sky is blue")
    assert any("fact" in idx[0] for idx in indexed)


# ── list_recent skill ─────────────────────────────────────────────────────────


async def test_list_recent_empty():
    mem = _make_memory()
    _, _, list_recent, _ = _skills(mem)
    result = await list_recent.execute(n="5")
    assert "no history" in result


async def test_list_recent_shows_entries():
    mem = _make_memory()
    await mem.append_history({"msg": "hello"})
    await mem.append_history({"msg": "world"})
    _, _, list_recent, _ = _skills(mem)
    result = await list_recent.execute(n="5")
    assert "hello" in result or "world" in result  # content appears in text


async def test_list_recent_respects_n():
    mem = _make_memory()
    for i in range(10):
        await mem.append_history({"i": i})
    _, _, list_recent, _ = _skills(mem)
    result = await list_recent.execute(n="3")
    lines = [l for l in result.strip().split("\n") if l]
    assert len(lines) == 3


# ── pin_memory skill ──────────────────────────────────────────────────────────


async def test_pin_memory_found():
    mem = _make_memory()
    entry = await mem.append_history("important")
    _, _, _, pin_memory = _skills(mem)
    result = await pin_memory.execute(entry_id=entry.id)
    assert "pinned" in result


async def test_pin_memory_not_found():
    mem = _make_memory()
    _, _, _, pin_memory = _skills(mem)
    result = await pin_memory.execute(entry_id="does-not-exist")
    assert "not found" in result


async def test_pin_memory_survives_eviction():
    mem = MemoryArea("ws", DictBackend(), history_limit=2)
    entry = await mem.append_history("keep this")
    _, _, _, pin_memory = _skills(mem)
    await pin_memory.execute(entry_id=entry.id)
    await mem.append_history("fill 1")
    await mem.append_history("fill 2")
    history = await mem.get_history()
    assert any(e.id == entry.id for e in history)

"""Tests for the memory-backed recall/remember Skills."""
import pytest

from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea
from autumn.core.memory.skills import make_memory_skills


# ── helpers ───────────────────────────────────────────────────────────────────


def _make_memory(name: str = "test") -> MemoryArea:
    return MemoryArea(name, DictBackend())


class _FakeAPI:
    """Minimal async API stub for A4 synthesis tests."""

    def __init__(self, answer: str):
        self._answer = answer

    async def complete(self, messages, **kwargs) -> str:
        return self._answer


# ── basic recall/remember ─────────────────────────────────────────────────────


async def test_remember_stores_string():
    mem = _make_memory()
    recall, remember = make_memory_skills(mem)
    result = await remember.execute(key="city", value="Beijing")
    assert "[remembered 'city']" == result
    assert await mem.get("city") == "Beijing"


async def test_recall_exact_key_hit():
    mem = _make_memory()
    await mem.set("lang", "Python")
    recall, _ = make_memory_skills(mem)
    result = await recall.execute(query="lang")
    assert result == "Python"


async def test_recall_missing_returns_message():
    mem = _make_memory()
    recall, _ = make_memory_skills(mem)
    result = await recall.execute(query="nonexistent")
    assert "no memory found" in result


async def test_recall_after_remember():
    mem = _make_memory()
    recall, remember = make_memory_skills(mem)
    await remember.execute(key="project", value="Autumn")
    result = await recall.execute(query="project")
    assert result == "Autumn"


async def test_recall_dict_value_as_json():
    mem = _make_memory()
    await mem.set("config", {"a": 1, "b": 2})
    recall, _ = make_memory_skills(mem)
    result = await recall.execute(query="config")
    import json
    assert json.loads(result) == {"a": 1, "b": 2}


async def test_recall_list_value_as_json():
    mem = _make_memory()
    await mem.set("tags", ["fast", "reliable"])
    recall, _ = make_memory_skills(mem)
    result = await recall.execute(query="tags")
    import json
    assert json.loads(result) == ["fast", "reliable"]


# ── skill schema ──────────────────────────────────────────────────────────────


def test_skill_names():
    mem = _make_memory()
    skills = make_memory_skills(mem)
    assert skills[0].name == "recall"
    assert skills[1].name == "remember"


def test_recall_schema_has_query_param():
    mem = _make_memory()
    recall, _ = make_memory_skills(mem)
    assert any(p.name == "query" for p in recall.parameters)


def test_remember_schema_has_key_and_value():
    mem = _make_memory()
    _, remember = make_memory_skills(mem)
    names = {p.name for p in remember.parameters}
    assert names == {"key", "value"}


def test_openai_schema_structure():
    mem = _make_memory()
    recall, _ = make_memory_skills(mem)
    schema = recall.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "recall"
    assert "query" in schema["function"]["parameters"]["properties"]


def test_anthropic_schema_structure():
    mem = _make_memory()
    recall, _ = make_memory_skills(mem)
    schema = recall.to_anthropic_schema()
    assert schema["name"] == "recall"
    assert "query" in schema["input_schema"]["properties"]


# ── A4 synthesis path ─────────────────────────────────────────────────────────


async def test_recall_no_vector_skips_api():
    """Without vector search, A4 is never consulted."""
    mem = _make_memory()
    api = _FakeAPI("should not appear")
    recall, _ = make_memory_skills(mem, api=api)
    # No exact key match and no vector layer → fallback message, not A4 output
    result = await recall.execute(query="unknown")
    assert "no memory found" in result
    assert "should not appear" not in result


async def test_recall_with_api_none_returns_snippets(monkeypatch):
    """Vector results returned raw when no A4 api is configured."""
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
    recall, _ = make_memory_skills(mem, api=None)
    result = await recall.execute(query="capital of Germany")
    assert "Berlin is the capital" in result
    assert "relevance=" in result


async def test_recall_with_api_synthesises_results(monkeypatch):
    """When A4 is set and vector search finds results, A4 is used to synthesise."""
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
    recall, _ = make_memory_skills(mem, api=api)
    result = await recall.execute(query="capital of France")
    assert result == "Paris"


# ── remember + vector auto-index ─────────────────────────────────────────────


async def test_remember_indexes_when_vector_enabled(monkeypatch):
    """remember() should call memory.index() when vector layer is present."""
    from autumn.core.memory.base import MemoryArea, _VectorLayer

    indexed: list[tuple] = []

    class _FakeStore:
        async def store(self, id, text, vector, metadata): indexed.append((id, text))

    class _FakeEmbedding:
        async def embed(self, text): return [0.5]

    mem = _make_memory()
    mem._vector = _VectorLayer(_FakeEmbedding(), _FakeStore())
    _, remember = make_memory_skills(mem)
    await remember.execute(key="fact", value="The sky is blue")
    assert any("fact" in idx[0] for idx in indexed)

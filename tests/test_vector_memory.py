"""Tests for vector memory: SQLiteVectorStore, MemoryArea.search/index, auto_index."""
import pytest

np = pytest.importorskip("numpy", reason="numpy not installed")

from autumn.core.types import SearchResult
from autumn.core.memory.backends.vector_backend import SQLiteVectorStore
from autumn.core.memory.base import MemoryArea
from autumn.core.memory.backends import DictBackend


# ── test double ───────────────────────────────────────────────────────────────

class _MockEmbedding:
    """Returns controllable deterministic vectors for testing."""

    def __init__(self, dim: int = 8):
        self._dim = dim
        self._overrides: dict[str, list[float]] = {}

    def preset(self, text: str, vec: list[float]) -> None:
        self._overrides[text] = vec

    async def embed(self, text: str) -> list[float]:
        if text in self._overrides:
            return list(self._overrides[text])
        # hash-based fallback: deterministic but not semantic
        seed = abs(hash(text)) % (2 ** 31)
        rng = np.random.default_rng(seed)
        vec = rng.standard_normal(self._dim).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec.tolist()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.embed(t) for t in texts]


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "vec.db")


# ── SQLiteVectorStore ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_store_and_search_exact(db):
    store = SQLiteVectorStore(db)
    emb = _MockEmbedding()

    text = "the quick brown fox"
    vec = await emb.embed(text)
    await store.store("id1", text, vec, {"tag": "test"})

    results = await store.search(vec, k=1)
    assert len(results) == 1
    result = results[0]
    assert result.id == "id1"
    assert result.text == text
    assert result.score > 0.999
    assert result.metadata == {"tag": "test"}

    await store.close()


@pytest.mark.asyncio
async def test_search_returns_top_k(db):
    store = SQLiteVectorStore(db)
    emb = _MockEmbedding()

    for i in range(6):
        vec = await emb.embed(f"doc_{i}")
        await store.store(f"id{i}", f"doc_{i}", vec)

    results = await store.search(await emb.embed("doc_0"), k=3)
    assert len(results) == 3
    assert results[0].id == "id0"
    # scores should be in descending order
    assert results[0].score >= results[1].score >= results[2].score

    await store.close()


@pytest.mark.asyncio
async def test_delete_removes_from_results(db):
    store = SQLiteVectorStore(db)
    emb = _MockEmbedding()

    vec = await emb.embed("hello")
    await store.store("target", "hello", vec)
    await store.delete("target")

    results = await store.search(vec, k=5)
    assert all(r.id != "target" for r in results)

    await store.close()


@pytest.mark.asyncio
async def test_empty_store_returns_empty(db):
    store = SQLiteVectorStore(db)
    emb = _MockEmbedding()
    results = await store.search(await emb.embed("anything"), k=5)
    assert results == []
    await store.close()


@pytest.mark.asyncio
async def test_insert_or_replace(db):
    store = SQLiteVectorStore(db)
    emb = _MockEmbedding()

    vec = await emb.embed("v1")
    await store.store("dup", "original", vec)
    vec2 = await emb.embed("v2")
    await store.store("dup", "updated", vec2)

    results = await store.search(vec2, k=1)
    assert results[0].text == "updated"

    await store.close()


# ── MemoryArea vector layer ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enable_vector_index_search(db):
    area = MemoryArea("test", DictBackend())
    emb = _MockEmbedding()
    store = SQLiteVectorStore(db)

    area.enable_vector(emb, store)
    assert area.has_vector

    await area.index("doc1", "semantic search result")
    results = await area.search("semantic search result", k=1)

    assert len(results) == 1
    assert results[0].id == "doc1"
    assert results[0].score > 0.999

    await store.close()


@pytest.mark.asyncio
async def test_search_without_vector_raises():
    area = MemoryArea("test", DictBackend())
    with pytest.raises(RuntimeError, match="Vector layer not enabled"):
        await area.search("query")


@pytest.mark.asyncio
async def test_index_without_vector_raises():
    area = MemoryArea("test", DictBackend())
    with pytest.raises(RuntimeError, match="Vector layer not enabled"):
        await area.index("id", "text")


@pytest.mark.asyncio
async def test_auto_index_on_append_history(db):
    area = MemoryArea("mem", DictBackend())
    emb = _MockEmbedding()
    store = SQLiteVectorStore(db)

    area.enable_vector(emb, store, auto_index=True)

    entry = {"role": "user", "content": "the quick brown fox jumps over the lazy dog"}
    await area.append_history(entry)

    # The exact JSON of the entry should be in the store; searching with the
    # same text should return that entry at the top.
    import json
    results = await area.search(json.dumps(entry, ensure_ascii=False), k=1)
    assert len(results) == 1
    assert results[0].score > 0.999
    assert results[0].metadata["type"] == "history"
    assert results[0].metadata["area"] == "mem"

    await store.close()


@pytest.mark.asyncio
async def test_no_auto_index_when_disabled(db):
    area = MemoryArea("mem", DictBackend())
    emb = _MockEmbedding()
    store = SQLiteVectorStore(db)

    # auto_index=False (default)
    area.enable_vector(emb, store, auto_index=False)
    await area.append_history({"role": "user", "content": "hello"})

    results = await area.search("hello", k=5)
    assert results == []

    await store.close()


@pytest.mark.asyncio
async def test_has_vector_false_by_default():
    area = MemoryArea("test", DictBackend())
    assert not area.has_vector


# ── SearchResult type ─────────────────────────────────────────────────────────

def test_search_result_fields():
    r = SearchResult(id="x", text="hello", score=0.9, metadata={"k": "v"})
    assert r.id == "x"
    assert r.text == "hello"
    assert r.score == 0.9
    assert r.metadata == {"k": "v"}

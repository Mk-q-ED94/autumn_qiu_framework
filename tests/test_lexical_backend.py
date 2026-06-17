"""P1-B tests: BM25/FTS5 lexical store + hybrid (RRF) recall fusion.

Contract:
- the lexical store ranks keyword matches and ignores noise;
- enabling lexical on a MemoryArea surfaces keyword hits (and fuses with vector
  when both are present) — a strict opt-in superset;
- with no lexical layer, recall is byte-identical to the vector-only path;
- a SQLite without FTS5 degrades gracefully (no crash, empty results).
"""
import math
import random

from autumn.core.config import BehaviorConfig
from autumn.core.memory.backends import DictBackend, SQLiteLexicalStore
from autumn.core.memory.backends.lexical_backend import _build_match
from autumn.core.memory.base import MemoryArea


# ── test double: deterministic, presettable embedding ───────────────────────────

class _MockEmbedding:
    def __init__(self, dim: int = 8):
        self._dim = dim
        self._overrides: dict[str, list[float]] = {}

    def preset(self, text: str, vec: list[float]) -> None:
        self._overrides[text] = vec

    async def embed(self, text: str) -> list[float]:
        if text in self._overrides:
            return list(self._overrides[text])
        seed = abs(hash(text)) % (2 ** 31)
        rng = random.Random(seed)
        vec = [rng.uniform(-1.0, 1.0) for _ in range(self._dim)]
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec


# ── query sanitisation ──────────────────────────────────────────────────────────

def test_build_match_tokenises_and_ors():
    assert _build_match("deploy the database") == '"deploy" OR "the" OR "database"'


def test_build_match_neutralises_fts5_operators():
    # Every token is quoted — even a literal "OR"/"NEAR" becomes a search term,
    # not an FTS5 operator, and stray *, /, " are dropped by tokenisation.
    out = _build_match('drop * OR "x" NEAR/2')
    assert out == '"drop" OR "OR" OR "x" OR "NEAR" OR "2"'
    # The joiners between quoted terms are the only real OR operators.
    assert '*' not in out and '/' not in out


def test_build_match_empty_query():
    assert _build_match("   ") == ""
    assert _build_match("!@#$%") == ""


# ── SQLiteLexicalStore ──────────────────────────────────────────────────────────

async def test_store_and_search_ranks_relevant_first(tmp_path):
    store = SQLiteLexicalStore(str(tmp_path / "lex.db"))
    await store.store("1", "deploy the production database safely", {})
    await store.store("2", "a recipe for cooking pasta", {})
    results = await store.search("database deploy", k=5)
    assert results
    assert results[0].id == "1"
    assert all(r.id != "2" for r in results) or results[0].score >= results[-1].score


async def test_search_empty_query_returns_empty(tmp_path):
    store = SQLiteLexicalStore(str(tmp_path / "lex.db"))
    await store.store("1", "anything", {})
    assert await store.search("   ", k=5) == []


async def test_special_chars_in_query_do_not_crash(tmp_path):
    store = SQLiteLexicalStore(str(tmp_path / "lex.db"))
    await store.store("1", "alpha beta", {})
    # Raw FTS5 operators / an unbalanced quote must be neutralised, not raise.
    results = await store.search('alpha OR "unterminated NEAR/2 *', k=5)
    assert [r.id for r in results] == ["1"]


async def test_upsert_replaces_text(tmp_path):
    store = SQLiteLexicalStore(str(tmp_path / "lex.db"))
    await store.store("1", "first version apricot", {})
    await store.store("1", "second version banana", {})
    assert await store.search("apricot", k=5) == []
    assert (await store.search("banana", k=5))[0].id == "1"


async def test_delete_removes_entry(tmp_path):
    store = SQLiteLexicalStore(str(tmp_path / "lex.db"))
    await store.store("1", "deletable token zeta", {})
    await store.delete("1")
    assert await store.search("zeta", k=5) == []


async def test_metadata_round_trips(tmp_path):
    store = SQLiteLexicalStore(str(tmp_path / "lex.db"))
    await store.store("1", "tagged entry", {"area": "mom1", "kind": "fact"})
    r = (await store.search("tagged", k=5))[0]
    assert r.metadata == {"area": "mom1", "kind": "fact"}


async def test_fts5_unavailable_degrades_gracefully(tmp_path):
    store = SQLiteLexicalStore(str(tmp_path / "lex.db"))
    store._available = False  # simulate a SQLite build without FTS5
    await store.store("1", "ignored", {})   # no-op, must not raise
    assert await store.search("ignored", k=5) == []


# ── MemoryArea: lexical-only recall ─────────────────────────────────────────────

async def test_enable_lexical_and_recall_keyword(tmp_path):
    area = MemoryArea("mom1", DictBackend())
    area.enable_lexical(SQLiteLexicalStore(str(tmp_path / "a.db")), auto_index=True)
    await area.append_history("the Kubernetes ingress controller config")
    await area.append_history("an unrelated note about tea")
    res = await area.recall("Kubernetes ingress")
    assert res
    assert "ingress" in res[0].content
    assert "lexical" in res[0].tags


async def test_lexical_search_requires_enable():
    area = MemoryArea("mom1", DictBackend())
    raised = False
    try:
        await area.lexical_search("x")
    except RuntimeError:
        raised = True
    assert raised
    assert area.has_lexical is False


# ── MemoryArea: hybrid (vector + lexical) fusion ────────────────────────────────

async def test_hybrid_fuses_vector_and_lexical(tmp_path):
    from autumn.core.memory.backends.vector_backend import SQLiteVectorStore

    area = MemoryArea("mom1", DictBackend())
    emb = _MockEmbedding()
    area.enable_vector(emb, SQLiteVectorStore(str(tmp_path / "v.db")), auto_index=True)
    area.enable_lexical(SQLiteLexicalStore(str(tmp_path / "l.db")), auto_index=True)

    await area.append_history("postgres replica connection pool")
    await area.append_history("frontend button hover animation")

    res = await area.recall("postgres replica", k=5)
    assert res
    top = res[0]
    assert "postgres" in top.content
    # The hit came through at least one modality and is RRF-scored.
    assert ({"vector", "lexical"} & set(top.tags))
    assert "score" in top.meta


async def test_no_lexical_recall_path_unchanged(tmp_path):
    """Without a lexical layer, vector recall keeps its original tag/shape."""
    from autumn.core.memory.backends.vector_backend import SQLiteVectorStore

    area = MemoryArea("mom1", DictBackend())
    emb = _MockEmbedding()
    area.enable_vector(emb, SQLiteVectorStore(str(tmp_path / "v.db")), auto_index=True)
    await area.append_history("only vector indexed entry")
    res = await area.recall("vector", k=5)
    assert res
    assert res[0].tags == ["vector"]  # the legacy vector-only synthetic shape


# ── config flag ─────────────────────────────────────────────────────────────────

def test_lexical_flag_default_off():
    assert BehaviorConfig().lexical_recall_enabled is False


def test_lexical_flag_from_env(monkeypatch):
    monkeypatch.setenv("LEXICAL_RECALL_ENABLED", "true")
    assert BehaviorConfig.from_env().lexical_recall_enabled is True
    monkeypatch.setenv("LEXICAL_RECALL_ENABLED", "off")
    assert BehaviorConfig.from_env().lexical_recall_enabled is False

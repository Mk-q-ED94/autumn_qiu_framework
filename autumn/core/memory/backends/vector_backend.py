import asyncio
from array import array
import heapq
import json
import math
import sqlite3

from ...types import SearchResult


def _vector_to_blob(vector: list) -> bytes:
    return array("f", (float(v) for v in vector)).tobytes()


def _vector_from_blob(blob: bytes) -> list[float]:
    values = array("f")
    values.frombytes(blob)
    return list(values)


def _norm(vector: list[float]) -> float:
    return math.sqrt(sum(v * v for v in vector))


def _cosine_score(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    left_norm = _norm(left)
    right_norm = _norm(right)
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


class SQLiteVectorStore:
    """Stores text embeddings as float32 blobs in SQLite."""

    def __init__(self, db_path: str, table: str = "vectors"):
        self._db_path = db_path
        self._table = table
        self._conn: sqlite3.Connection | None = None

    # ── sync internals (run in executor) ─────────────────────────────────────

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.execute(
                f"""CREATE TABLE IF NOT EXISTS {self._table} (
                    id     TEXT PRIMARY KEY,
                    text   TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    meta   TEXT NOT NULL DEFAULT '{{}}'
                )"""
            )
            self._conn.commit()
        return self._conn

    def _sync_store(self, id: str, text: str, vector: list, metadata: dict) -> None:
        conn = self._ensure_conn()
        blob = _vector_to_blob(vector)
        conn.execute(
            f"INSERT OR REPLACE INTO {self._table} (id, text, vector, meta) VALUES (?, ?, ?, ?)",
            (id, text, blob, json.dumps(metadata)),
        )
        conn.commit()

    def _sync_search(self, query_vector: list, k: int) -> list:
        conn = self._ensure_conn()
        rows = conn.execute(
            f"SELECT id, text, vector, meta FROM {self._table}"
        ).fetchall()
        if not rows:
            return []

        query = [float(v) for v in query_vector]
        query_norm = _norm(query)
        if query_norm == 0.0:
            return []
        dim = len(query)

        # Score each row against the query, reusing the query norm computed once
        # (was recomputed per row inside _cosine_score). Zero-norm / dimension
        # mismatches score 0.0, exactly as before.
        def _score(blob: bytes) -> float:
            entry = _vector_from_blob(blob)
            if len(entry) != dim:
                return 0.0
            entry_norm = _norm(entry)
            if entry_norm == 0.0:
                return 0.0
            return sum(a * b for a, b in zip(query, entry)) / (query_norm * entry_norm)

        # Bounded heap selects the top-k in O(N log k) instead of sorting the
        # whole table O(N log N); metadata JSON is only parsed for the survivors.
        # heapq.nlargest over the full tuple preserves the original tie-break
        # order (score, then id, text, meta) of sorted(..., reverse=True)[:k].
        top = heapq.nlargest(
            k,
            ((_score(blob), row_id, text, meta) for row_id, text, blob, meta in rows),
        )
        return [
            SearchResult(
                id=row_id,
                text=text,
                score=float(score),
                metadata=json.loads(meta),
            )
            for score, row_id, text, meta in top
        ]

    def _sync_delete(self, id: str) -> None:
        conn = self._ensure_conn()
        conn.execute(f"DELETE FROM {self._table} WHERE id = ?", (id,))
        conn.commit()

    def _sync_close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── async public api ──────────────────────────────────────────────────────

    async def store(
        self, id: str, text: str, vector: list, metadata: dict | None = None
    ) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, self._sync_store, id, text, vector, metadata or {}
        )

    async def search(self, query_vector: list, k: int = 5) -> list[SearchResult]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_search, query_vector, k)

    async def delete(self, id: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sync_delete, id)

    async def close(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sync_close)

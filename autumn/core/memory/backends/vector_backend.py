import asyncio
import json
import sqlite3

from ...types import SearchResult


def _require_numpy():
    try:
        import numpy as np
        return np
    except ImportError:
        raise ImportError(
            "numpy is required for vector memory. "
            "Install it with: pip install 'autumn[vector]'"
        )


class SQLiteVectorStore:
    """Stores text embeddings as float32 blobs in SQLite.

    Cosine similarity is computed in-process via numpy. Requires numpy
    (install with: pip install autumn[vector]).
    """

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
        np = _require_numpy()
        conn = self._ensure_conn()
        blob = np.array(vector, dtype=np.float32).tobytes()
        conn.execute(
            f"INSERT OR REPLACE INTO {self._table} (id, text, vector, meta) VALUES (?, ?, ?, ?)",
            (id, text, blob, json.dumps(metadata)),
        )
        conn.commit()

    def _sync_search(self, query_vector: list, k: int) -> list:
        np = _require_numpy()
        conn = self._ensure_conn()
        rows = conn.execute(
            f"SELECT id, text, vector, meta FROM {self._table}"
        ).fetchall()
        if not rows:
            return []

        q = np.array(query_vector, dtype=np.float32)
        q_norm = np.linalg.norm(q)
        if q_norm == 0.0:
            return []
        q = q / q_norm

        ids, texts, blobs, metas = zip(*rows)
        mat = np.stack([np.frombuffer(b, dtype=np.float32) for b in blobs])
        row_norms = np.linalg.norm(mat, axis=1, keepdims=True)
        row_norms[row_norms == 0.0] = 1.0
        scores = (mat / row_norms) @ q

        ranked = sorted(zip(scores.tolist(), ids, texts, metas), reverse=True)
        return [
            SearchResult(
                id=row_id,
                text=text,
                score=float(score),
                metadata=json.loads(meta),
            )
            for score, row_id, text, meta in ranked[:k]
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

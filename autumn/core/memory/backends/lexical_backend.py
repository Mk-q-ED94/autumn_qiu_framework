"""Lexical (BM25) memory store via SQLite FTS5 (RFC 4D-memory P1-B).

Adds the keyword/lexical half of hybrid retrieval that vector search alone
misses: proper nouns, identifiers, code symbols and exact terms that are
"semantically near but only literally match". Mirrors
:class:`SQLiteVectorStore`'s shape so :class:`MemoryArea` can drive both the
same way, and the two are fused by Reciprocal Rank Fusion in ``recall``.

Uses SQLite's built-in FTS5 (no dependency). When the SQLite build lacks FTS5
the store degrades gracefully — :attr:`available` is ``False`` and every op is a
no-op / empty result, so enabling lexical recall never crashes a deployment.
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import threading

from ...types import SearchResult

_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _build_match(query: str) -> str:
    """Turn a free-text query into a safe FTS5 MATCH expression.

    Extracts word tokens and ORs them as quoted terms, so user input can never
    inject FTS5 operators (``*``, ``:``, ``NEAR``, unbalanced quotes). Returns
    ``""`` when the query has no usable tokens (caller skips the search).
    """
    tokens = _TOKEN_RE.findall(query or "")
    if not tokens:
        return ""
    return " OR ".join(f'"{t}"' for t in tokens)


class SQLiteLexicalStore:
    """BM25 keyword index over entry text, backed by a SQLite FTS5 table."""

    def __init__(self, db_path: str, table: str = "lexical"):
        if not _TABLE_NAME_RE.match(table):
            raise ValueError(f"Invalid lexical table name: {table!r}. Use [A-Za-z_][A-Za-z0-9_]*.")
        self._db_path = db_path
        self._table = table
        self._conn: sqlite3.Connection | None = None
        self._available: bool | None = None  # resolved on first connect
        # Guards first-use: executor threads must not race to open the connection
        # / probe FTS5 availability and orphan a connection.
        self._init_lock = threading.Lock()

    # ── sync internals (run in executor) ─────────────────────────────────────

    def _ensure_conn(self) -> sqlite3.Connection | None:
        if self._available is False:
            return None
        if self._conn is not None:
            return self._conn
        with self._init_lock:
            if self._available is False:
                return None
            if self._conn is None:
                conn = sqlite3.connect(self._db_path, check_same_thread=False)
                try:
                    conn.execute(
                        f"CREATE VIRTUAL TABLE IF NOT EXISTS {self._table} "
                        f"USING fts5(id UNINDEXED, text, meta UNINDEXED)",
                    )
                    conn.commit()
                    self._available = True
                    self._conn = conn
                except sqlite3.OperationalError:
                    # FTS5 not compiled into this SQLite build — degrade to no-op.
                    conn.close()
                    self._available = False
                    return None
        return self._conn

    def _sync_store(self, id: str, text: str, metadata: dict) -> None:
        conn = self._ensure_conn()
        if conn is None:
            return
        # FTS5 has no PRIMARY KEY, so emulate upsert: drop any existing rows first.
        conn.execute(f"DELETE FROM {self._table} WHERE id = ?", (id,))
        conn.execute(
            f"INSERT INTO {self._table} (id, text, meta) VALUES (?, ?, ?)",
            (id, text, json.dumps(metadata)),
        )
        conn.commit()

    def _sync_search(self, query: str, k: int) -> list:
        conn = self._ensure_conn()
        if conn is None:
            return []
        match = _build_match(query)
        if not match:
            return []
        # bm25() returns LOWER = better; order ascending and expose -bm25 as a
        # "higher is better" relevance score for transparency. Ranking/fusion
        # downstream uses position, not the raw magnitude.
        rows = conn.execute(
            f"SELECT id, text, meta, bm25({self._table}) AS score "
            f"FROM {self._table} WHERE {self._table} MATCH ? ORDER BY score LIMIT ?",
            (match, k),
        ).fetchall()
        return [
            SearchResult(id=row_id, text=text, score=-float(score), metadata=json.loads(meta))
            for row_id, text, meta, score in rows
        ]

    def _sync_delete(self, id: str) -> None:
        conn = self._ensure_conn()
        if conn is None:
            return
        conn.execute(f"DELETE FROM {self._table} WHERE id = ?", (id,))
        conn.commit()

    def _sync_close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── async public api (mirrors SQLiteVectorStore) ──────────────────────────

    async def store(self, id: str, text: str, metadata: dict | None = None) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sync_store, id, text, metadata or {})

    async def search(self, query: str, k: int = 5) -> list[SearchResult]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_search, query, k)

    async def delete(self, id: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sync_delete, id)

    async def close(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sync_close)

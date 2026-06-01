import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from ..base import MemoryBackend


class SQLiteBackend(MemoryBackend):
    """Persistent storage backend using SQLite. Thread-safe via executor."""

    def __init__(self, db_path: str):
        self._path = Path(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS memory "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at REAL NOT NULL)"
            )

    def _run(self, fn):
        return asyncio.get_event_loop().run_in_executor(None, fn)

    async def get(self, key: str) -> Any:
        def _():
            with self._connect() as conn:
                row = conn.execute("SELECT value FROM memory WHERE key=?", (key,)).fetchone()
                return json.loads(row[0]) if row else None
        return await self._run(_)

    async def set(self, key: str, value: Any) -> None:
        def _():
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO memory (key,value,updated_at) VALUES (?,?,?)",
                    (key, json.dumps(value, ensure_ascii=False), time.time()),
                )
        await self._run(_)

    async def delete(self, key: str) -> None:
        def _():
            with self._connect() as conn:
                conn.execute("DELETE FROM memory WHERE key=?", (key,))
        await self._run(_)

    async def keys(self) -> list[str]:
        def _():
            with self._connect() as conn:
                return [r[0] for r in conn.execute("SELECT key FROM memory").fetchall()]
        return await self._run(_)

    async def clear(self) -> None:
        def _():
            with self._connect() as conn:
                conn.execute("DELETE FROM memory")
        await self._run(_)

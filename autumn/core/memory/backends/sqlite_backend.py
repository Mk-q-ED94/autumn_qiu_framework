import asyncio
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from ..base import MemoryBackend


class SQLiteBackend(MemoryBackend):
    """Persistent storage backend using SQLite. Thread-safe via executor.

    Connections are cached per OS thread (``threading.local``): the executor
    reuses a small pool of threads, so each one opens its SQLite connection
    once and reuses it for every subsequent op instead of reconnecting on each
    call. WAL + ``synchronous=NORMAL`` keeps writes durable while skipping the
    per-commit fsync, which dominates the append-heavy memory write path.
    """

    def __init__(self, db_path: str):
        self._path = Path(db_path)
        # Ensure the parent directory exists so a per-user data dir (e.g.
        # %APPDATA%\Autumn on Windows) works on first run. Bare filenames have
        # parent "." which already exists, so this is a no-op for the default.
        parent = self._path.parent
        if parent and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
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

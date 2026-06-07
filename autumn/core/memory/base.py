from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from ..types import SearchResult

if TYPE_CHECKING:
    from ..api.embedding import EmbeddingInterface
    from .backends.vector_backend import SQLiteVectorStore

_HISTORY_KEY = "history"
_MAX_HISTORY = 50


class MemoryBackend(ABC):
    """Abstract storage backend. Implement to plug in a concrete storage system."""

    @abstractmethod
    async def get(self, key: str) -> Any: ...

    @abstractmethod
    async def set(self, key: str, value: Any) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def keys(self) -> list[str]: ...

    @abstractmethod
    async def clear(self) -> None: ...


class _VectorLayer:
    __slots__ = ("embedding", "store", "auto_index")

    def __init__(self, embedding: EmbeddingInterface, store: SQLiteVectorStore, auto_index: bool = False):
        self.embedding = embedding
        self.store = store
        self.auto_index = auto_index


class MemoryArea:
    """A named, namespaced area backed by a MemoryBackend.

    Call enable_vector() to attach a semantic search layer. Once enabled:
      - index(id, text) embeds and stores text for later retrieval.
      - search(query, k) returns the k most similar indexed entries.
      - auto_index=True in enable_vector() causes append_history() to
        automatically embed and index each new entry.
    """

    def __init__(self, name: str, backend: MemoryBackend):
        self.name = name
        self._backend = backend
        self._vector: _VectorLayer | None = None
        # Serializes the read-modify-write inside append_history so concurrent
        # turns (e.g. two streams sharing this area) can't lose entries.
        self._history_lock = asyncio.Lock()

    @property
    def has_vector(self) -> bool:
        return self._vector is not None

    def enable_vector(
        self,
        embedding: EmbeddingInterface,
        store: SQLiteVectorStore,
        auto_index: bool = False,
    ) -> None:
        """Attach a vector layer for semantic search."""
        self._vector = _VectorLayer(embedding=embedding, store=store, auto_index=auto_index)

    def _k(self, key: str) -> str:
        return f"{self.name}:{key}"

    async def get(self, key: str) -> Any:
        return await self._backend.get(self._k(key))

    async def set(self, key: str, value: Any) -> None:
        await self._backend.set(self._k(key), value)

    async def delete(self, key: str) -> None:
        await self._backend.delete(self._k(key))

    async def keys(self) -> list[str]:
        prefix = f"{self.name}:"
        return [
            k.removeprefix(prefix)
            for k in await self._backend.keys()
            if k.startswith(prefix)
        ]

    async def clear(self) -> None:
        for key in await self.keys():
            await self.delete(key)

    # ── vector helpers ────────────────────────────────────────────────────────

    async def index(self, id: str, text: str, metadata: dict | None = None) -> None:
        """Embed text and store it for semantic search. Requires enable_vector()."""
        if self._vector is None:
            raise RuntimeError("Vector layer not enabled. Call enable_vector() first.")
        vector = await self._vector.embedding.embed(text)
        await self._vector.store.store(id, text, vector, metadata or {})

    async def search(self, query: str, k: int = 5) -> list[SearchResult]:
        """Return the k most semantically similar indexed entries. Requires enable_vector()."""
        if self._vector is None:
            raise RuntimeError("Vector layer not enabled. Call enable_vector() first.")
        query_vec = await self._vector.embedding.embed(query)
        return await self._vector.store.search(query_vec, k)

    # ── history helpers ───────────────────────────────────────────────────────

    async def append_history(self, entry: dict, max_entries: int = _MAX_HISTORY) -> None:
        """Append a turn record to history, capped at max_entries (most recent kept)."""
        async with self._history_lock:
            history = await self.get(_HISTORY_KEY) or []
            history.append(entry)
            if len(history) > max_entries:
                history = history[-max_entries:]
            await self.set(_HISTORY_KEY, history)

        if self._vector is not None and self._vector.auto_index:
            import json as _json
            import time as _time
            text = _json.dumps(entry, ensure_ascii=False) if isinstance(entry, dict) else str(entry)
            entry_id = f"{self.name}:h:{_time.time_ns()}"
            await self.index(entry_id, text, {"type": "history", "area": self.name})

    async def get_history(self) -> list[dict]:
        return await self.get(_HISTORY_KEY) or []

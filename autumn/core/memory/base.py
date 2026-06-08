from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from ..types import SearchResult

if TYPE_CHECKING:
    from ..api.embedding import EmbeddingInterface
    from .backends.vector_backend import SQLiteVectorStore

_HISTORY_KEY = "history"
_MAX_HISTORY = 50
_PIN_THRESHOLD = 1.5  # importance >= this → never evicted


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class MemoryEntry:
    """Typed history record with importance weighting and tagging.

    Entries with importance >= MemoryEntry.PIN_THRESHOLD are pinned and survive
    eviction even when history is at capacity. Default importance is 1.0 (normal).
    Setting importance to 0.5 marks an entry as low-priority (evicted first).
    """

    id: str
    content: Any           # dict | str | list — the stored payload
    timestamp: float       # unix epoch seconds
    importance: float = 1.0
    tags: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    PIN_THRESHOLD: ClassVar[float] = _PIN_THRESHOLD

    @property
    def is_pinned(self) -> bool:
        return self.importance >= _PIN_THRESHOLD

    @property
    def text(self) -> str:
        """String representation of content — used for display and vector indexing."""
        if isinstance(self.content, str):
            return self.content
        import json
        return json.dumps(self.content, ensure_ascii=False)

    def to_dict(self) -> dict:
        return {
            "_m": True,
            "id": self.id,
            "content": self.content,
            "timestamp": self.timestamp,
            "importance": self.importance,
            "tags": self.tags,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "MemoryEntry":
        """Load from serialized form, or transparently upgrade a legacy raw dict."""
        if raw.get("_m"):
            return cls(
                id=raw["id"],
                content=raw["content"],
                timestamp=raw["timestamp"],
                importance=raw.get("importance", 1.0),
                tags=raw.get("tags", []),
                meta=raw.get("meta", {}),
            )
        # Legacy workspace dict ({"ts": ..., "input": ..., "output": ...})
        return cls(
            id=_new_id(),
            content=raw,
            timestamp=raw.get("ts", 0.0),
            importance=1.0,
            tags=[],
        )


def _evict(history: list[MemoryEntry], limit: int) -> list[MemoryEntry]:
    """Trim history to at most *limit* entries.

    Pinned entries are kept unconditionally. Among normal entries, the highest
    importance ones survive; recency breaks ties (newer wins).
    The final list is returned in ascending timestamp order.
    """
    if len(history) <= limit:
        return history
    pinned = [e for e in history if e.is_pinned]
    normal = [e for e in history if not e.is_pinned]
    normal.sort(key=lambda e: (-e.importance, -e.timestamp))  # best first
    keep_normal = max(0, limit - len(pinned))
    if len(pinned) > limit:
        kept = sorted(pinned, key=lambda e: -e.importance)[:limit]
    else:
        kept = pinned + normal[:keep_normal]
    kept.sort(key=lambda e: e.timestamp)  # restore chronological order
    return kept


# ── Backend ABC ───────────────────────────────────────────────────────────────

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


# ── Internal vector layer wrapper ─────────────────────────────────────────────

class _VectorLayer:
    __slots__ = ("embedding", "store", "auto_index")

    def __init__(
        self,
        embedding: "EmbeddingInterface",
        store: "SQLiteVectorStore",
        auto_index: bool = False,
    ):
        self.embedding = embedding
        self.store = store
        self.auto_index = auto_index


# ── MemoryArea ────────────────────────────────────────────────────────────────

class MemoryArea:
    """A named, namespaced area backed by a MemoryBackend.

    Key-value API (get/set/delete/keys) provides raw storage.

    History API (append_history/get_history/recent/pin/unpin) stores structured
    MemoryEntry records with importance weighting.  When the cap is reached,
    low-importance entries are evicted first; pinned entries never evict.

    Recall API (recall) unifies exact-key lookup, tag filtering, and optional
    semantic search into a single ranked result list.

    Call enable_vector() to attach a semantic search layer.
    """

    def __init__(self, name: str, backend: MemoryBackend, history_limit: int = _MAX_HISTORY):
        self.name = name
        self._backend = backend
        self._vector: _VectorLayer | None = None
        self._history_limit = history_limit
        # Serialises the read-modify-write cycle in append_history so concurrent
        # turns cannot lose entries.
        self._history_lock = asyncio.Lock()

    @property
    def has_vector(self) -> bool:
        return self._vector is not None

    def enable_vector(
        self,
        embedding: "EmbeddingInterface",
        store: "SQLiteVectorStore",
        auto_index: bool = False,
    ) -> None:
        """Attach a vector layer for semantic search."""
        self._vector = _VectorLayer(embedding=embedding, store=store, auto_index=auto_index)

    # ── namespaced key-value ──────────────────────────────────────────────────

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

    # ── history ───────────────────────────────────────────────────────────────

    async def append_history(
        self,
        entry: "dict | str | MemoryEntry",
        importance: float = 1.0,
        tags: list[str] | None = None,
        max_entries: int | None = None,
    ) -> "MemoryEntry":
        """Append a turn record. Returns the stored MemoryEntry.

        Accepts a raw dict or string (backward-compatible) or a MemoryEntry.
        When capacity is exceeded, lowest-importance non-pinned entries are removed
        first; recency breaks importance ties (older entries removed first).
        Pinned entries (importance >= PIN_THRESHOLD) are never evicted.
        """
        limit = max_entries if max_entries is not None else self._history_limit

        if not isinstance(entry, MemoryEntry):
            ts = entry.get("ts", time.time()) if isinstance(entry, dict) else time.time()
            entry = MemoryEntry(
                id=_new_id(),
                content=entry,
                timestamp=ts,
                importance=importance,
                tags=tags or [],
            )

        async with self._history_lock:
            raw = await self.get(_HISTORY_KEY) or []
            history = [
                MemoryEntry.from_dict(e) if isinstance(e, dict) else e
                for e in raw
            ]
            history.append(entry)
            history = _evict(history, limit)
            await self.set(_HISTORY_KEY, [e.to_dict() for e in history])

        if self._vector is not None and self._vector.auto_index:
            meta = {"type": "history", "area": self.name}
            meta.update({f"tag:{t}": True for t in entry.tags})
            await self.index(entry.id, entry.text, meta)

        return entry

    async def get_history(
        self,
        n: int | None = None,
        tags: list[str] | None = None,
        since: float | None = None,
    ) -> list["MemoryEntry"]:
        """Return history entries, optionally filtered.

        Args:
            n:     Return at most the *last* n entries (most recent).
            tags:  If given, only entries that have ALL listed tags are returned.
            since: If given, only entries with timestamp >= since are returned.
        """
        raw = await self.get(_HISTORY_KEY) or []
        entries = [
            MemoryEntry.from_dict(e) if isinstance(e, dict) else e
            for e in raw
        ]
        if since is not None:
            entries = [e for e in entries if e.timestamp >= since]
        if tags is not None:
            tag_set = set(tags)
            entries = [e for e in entries if tag_set.issubset(set(e.tags))]
        if n is not None:
            entries = entries[-n:]
        return entries

    async def recent(self, n: int = 5) -> list["MemoryEntry"]:
        """Return the n most recent history entries (convenience wrapper)."""
        return await self.get_history(n=n)

    async def recall(
        self,
        query: str,
        k: int = 5,
        tags: list[str] | None = None,
    ) -> list["MemoryEntry"]:
        """Unified retrieval combining three strategies, ranked by relevance.

        1. Exact key-value lookup on *query* as a key.
        2. History filtering by *tags* (if given).
        3. Semantic vector search (if vector layer is enabled).

        Returns up to k MemoryEntry objects, deduplicated and sorted by
        descending importance then descending timestamp. Never raises.
        """
        results: list[MemoryEntry] = []

        # 1. Exact KV lookup
        value = await self.get(query)
        if value is not None:
            results.append(MemoryEntry(
                id=f"kv:{query}",
                content=value,
                timestamp=time.time(),
                importance=2.0,
                tags=["kv"],
            ))

        # 2. Tag-filtered history
        if tags:
            results.extend(await self.get_history(tags=tags))

        # 3. Semantic search
        if self._vector is not None and len(results) < k:
            try:
                semantic = await self.search(query, k=k)
                for r in semantic:
                    meta = dict(getattr(r, "metadata", None) or {})
                    meta["score"] = r.score
                    results.append(MemoryEntry(
                        id=r.id,
                        content=r.text,
                        timestamp=0.0,
                        importance=r.score * _PIN_THRESHOLD,
                        tags=["vector"],
                        meta=meta,
                    ))
            except Exception:
                pass

        # Deduplicate: keep highest importance per id
        seen: dict[str, MemoryEntry] = {}
        for e in results:
            if e.id not in seen or e.importance > seen[e.id].importance:
                seen[e.id] = e

        ranked = sorted(seen.values(), key=lambda e: (-e.importance, -e.timestamp))
        return ranked[:k]

    # ── pin / unpin ───────────────────────────────────────────────────────────

    async def pin(self, entry_id: str) -> bool:
        """Raise an entry's importance to PIN_THRESHOLD so it survives eviction.

        Returns True if the entry was found, False otherwise.
        """
        async with self._history_lock:
            raw = await self.get(_HISTORY_KEY) or []
            history = [
                MemoryEntry.from_dict(e) if isinstance(e, dict) else e
                for e in raw
            ]
            for i, e in enumerate(history):
                if e.id == entry_id:
                    history[i] = MemoryEntry(
                        id=e.id, content=e.content, timestamp=e.timestamp,
                        importance=_PIN_THRESHOLD, tags=e.tags, meta=e.meta,
                    )
                    await self.set(_HISTORY_KEY, [h.to_dict() for h in history])
                    return True
        return False

    async def unpin(self, entry_id: str) -> bool:
        """Reset an entry's importance to 1.0. Returns True if found."""
        async with self._history_lock:
            raw = await self.get(_HISTORY_KEY) or []
            history = [
                MemoryEntry.from_dict(e) if isinstance(e, dict) else e
                for e in raw
            ]
            for i, e in enumerate(history):
                if e.id == entry_id:
                    history[i] = MemoryEntry(
                        id=e.id, content=e.content, timestamp=e.timestamp,
                        importance=1.0, tags=e.tags, meta=e.meta,
                    )
                    await self.set(_HISTORY_KEY, [h.to_dict() for h in history])
                    return True
        return False

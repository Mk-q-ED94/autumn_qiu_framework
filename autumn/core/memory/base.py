from __future__ import annotations

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from ..types import SearchResult
from .dimensions import ActivationContext, Aim, Trigger, Use, UseMode, activation_score

if TYPE_CHECKING:
    from ..api.base import ModelAPIInterface
    from ..api.embedding import EmbeddingInterface
    from .backends.vector_backend import SQLiteVectorStore

_HISTORY_KEY = "history"
_MAX_HISTORY = 50
_PIN_THRESHOLD = 1.5  # importance >= this → never evicted


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class MemoryEntry:
    """Typed history record with importance weighting, tagging and expiry.

    Entries with importance >= MemoryEntry.PIN_THRESHOLD are pinned and survive
    eviction even when history is at capacity. Default importance is 1.0 (normal).
    Setting importance to 0.5 marks an entry as low-priority (evicted first).

    ``expires_at`` (unix epoch seconds) gives an entry a time-to-live: once the
    clock passes it the entry is treated as gone — filtered from reads and purged
    on the next write. ``None`` means the entry never expires.
    """

    id: str
    content: Any           # dict | str | list — the stored payload
    timestamp: float       # unix epoch seconds
    importance: float = 1.0
    tags: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    expires_at: float | None = None
    # 4D memory dimensions (see autumn/core/memory/dimensions.py). All default to
    # empty, so an entry carrying none of them behaves exactly as before. ``trigger``
    # is the time 维 (named ``trigger`` to avoid shadowing the stdlib ``time`` module).
    aim: Aim = field(default_factory=Aim)
    use: Use = field(default_factory=Use)
    trigger: Trigger = field(default_factory=Trigger)

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

    def is_expired(self, now: float | None = None) -> bool:
        """True if this entry has a TTL that has elapsed."""
        if self.expires_at is None:
            return False
        return (now if now is not None else time.time()) >= self.expires_at

    def effective_importance(
        self, now: float | None = None, half_life: float | None = None,
    ) -> float:
        """Importance after time-decay.

        Pinned entries never decay. With no ``half_life`` the raw importance is
        returned unchanged. Otherwise importance halves every ``half_life``
        seconds of age, so old low-value memories fade ahead of fresh ones.
        """
        if self.is_pinned or not half_life or half_life <= 0:
            return self.importance
        now = now if now is not None else time.time()
        age = max(0.0, now - self.timestamp)
        return self.importance * (0.5 ** (age / half_life))

    def activation(
        self, ctx: ActivationContext, half_life: float | None = None,
    ) -> float:
        """Query-time 4D activation score (see docs/rfc-4d-memory.md §5).

        ``trigger`` gates and weights by time, ``aim`` gates by purpose, ``use``
        boosts by past utility; the importance×decay base keeps the time factor
        anchored to today's ranking. With empty dimensions this collapses to
        ``effective_importance``, so enabling 4D scoring on un-annotated data
        changes nothing (modulo decay). Returns 0 when the trigger or aim vetoes.
        """
        w = self.trigger.weight(self.timestamp, ctx.now, ctx, self.use.stats.last_used)
        if w <= 0:
            return 0.0
        a = self.aim.align(ctx)
        if a <= 0:
            return 0.0
        time_factor = w * self.effective_importance(ctx.now, half_life)
        return activation_score(time_factor, a, self.use.utility())

    def retention_score(
        self, now: float | None = None, half_life: float | None = None,
    ) -> float:
        """Context-free value for eviction: importance×decay boosted by usage.

        Deliberately ignores ``aim``/``trigger`` (those gate *when* a memory is
        relevant, not whether it is worth keeping). Collapses to
        ``effective_importance`` for never-used entries, so 4D eviction matches
        today's on un-annotated data.
        """
        return self.effective_importance(now, half_life) * (1.0 + self.use.utility())

    def to_dict(self) -> dict:
        return {
            "_m": True,
            "_v": 2,  # schema version: 2 adds the aim/use/trigger dimensions
            "id": self.id,
            "content": self.content,
            "timestamp": self.timestamp,
            "importance": self.importance,
            "tags": self.tags,
            "meta": self.meta,
            "expires_at": self.expires_at,
            "aim": self.aim.to_dict(),
            "use": self.use.to_dict(),
            "trigger": self.trigger.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> MemoryEntry:
        """Load from serialized form, or transparently upgrade a legacy raw dict.

        v1 records (no ``_v``) simply lack the ``aim``/``use``/``trigger`` keys,
        so each falls back to its empty default and the entry behaves as before.
        """
        if raw.get("_m"):
            return cls(
                id=raw["id"],
                content=raw["content"],
                timestamp=raw["timestamp"],
                importance=raw.get("importance", 1.0),
                tags=raw.get("tags", []),
                meta=raw.get("meta", {}),
                expires_at=raw.get("expires_at"),
                aim=Aim.from_dict(raw["aim"]) if raw.get("aim") else Aim(),
                use=Use.from_dict(raw["use"]) if raw.get("use") else Use(),
                trigger=Trigger.from_dict(raw["trigger"]) if raw.get("trigger") else Trigger(),
            )
        # Legacy workspace dict ({"ts": ..., "input": ..., "output": ...})
        return cls(
            id=_new_id(),
            content=raw,
            timestamp=raw.get("ts", 0.0),
            importance=1.0,
            tags=[],
        )


def _decode(raw: list | None) -> list[MemoryEntry]:
    """Decode a stored history list into MemoryEntry objects (legacy-tolerant)."""
    return [
        MemoryEntry.from_dict(e) if isinstance(e, dict) else e
        for e in (raw or [])
    ]


def _evict(
    history: list[MemoryEntry],
    limit: int,
    now: float | None = None,
    half_life: float | None = None,
    fourd: bool = False,
) -> list[MemoryEntry]:
    """Trim history to at most *limit* entries.

    Pinned entries are kept unconditionally. Among normal entries, the highest
    retention value survives; recency breaks ties (newer wins). Returned in
    ascending timestamp order. ``fourd`` switches the retention metric from
    ``effective_importance`` (time-decay only) to ``retention_score``
    (decay boosted by use utility); the two coincide for un-annotated entries.
    """
    if len(history) <= limit:
        return history
    now = now if now is not None else time.time()
    pinned = [e for e in history if e.is_pinned]
    normal = [e for e in history if not e.is_pinned]
    if fourd:
        normal.sort(key=lambda e: (-e.retention_score(now, half_life), -e.timestamp))
    else:
        normal.sort(key=lambda e: (-e.effective_importance(now, half_life), -e.timestamp))
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
        embedding: EmbeddingInterface,
        store: SQLiteVectorStore,
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
    MemoryEntry records with importance weighting and optional TTL.  When the cap
    is reached, low-importance entries are evicted first (with time-decay when a
    ``decay_half_life`` is configured); pinned entries never evict.

    Recall API (recall) unifies exact-key lookup, tag filtering, and optional
    semantic search into a single ranked result list.

    Lifecycle API (consolidate/forget/stats) summarises, prunes and reports on
    stored memory.

    Call enable_vector() to attach a semantic search layer.
    """

    def __init__(
        self,
        name: str,
        backend: MemoryBackend,
        history_limit: int = _MAX_HISTORY,
        decay_half_life: float | None = None,
        fourd_enabled: bool = False,
    ):
        self.name = name
        self._backend = backend
        self._vector: _VectorLayer | None = None
        self._history_limit = history_limit
        # When set, importance decays by half every this-many seconds of age,
        # influencing eviction priority. None disables decay (default).
        self._decay_half_life = decay_half_life or None
        # When True, recall/evict rank by the 4D activation/retention score
        # instead of raw importance; collapses to today's behavior for
        # un-annotated entries. See docs/rfc-4d-memory.md.
        self._fourd_enabled = fourd_enabled
        # Serialises the read-modify-write cycle in append_history so concurrent
        # turns cannot lose entries.
        self._history_lock = asyncio.Lock()

    @property
    def fourd_enabled(self) -> bool:
        """Whether recall/eviction currently rank by 4D activation score."""
        return self._fourd_enabled

    def set_fourd_enabled(self, enabled: bool) -> None:
        """Toggle 4D activation ranking at runtime.

        recall() and eviction read ``_fourd_enabled`` live, so flipping it takes
        effect on the next operation — no rebuild needed.
        """
        self._fourd_enabled = enabled

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
        entry: dict | str | MemoryEntry,
        importance: float = 1.0,
        tags: list[str] | None = None,
        max_entries: int | None = None,
        ttl: float | None = None,
        aim: Aim | None = None,
        use: Use | None = None,
        trigger: Trigger | None = None,
    ) -> MemoryEntry:
        """Append a turn record. Returns the stored MemoryEntry.

        Accepts a raw dict or string (backward-compatible) or a MemoryEntry.
        ``ttl`` (seconds) gives the entry a time-to-live; expired entries are
        filtered from reads and purged here on the next append. When capacity is
        exceeded, lowest effective-importance non-pinned entries are removed
        first. Pinned entries (importance >= PIN_THRESHOLD) are never evicted.

        ``aim`` / ``use`` / ``trigger`` attach the 4D-memory dimensions; when
        omitted the entry keeps its existing (empty) defaults, so the call is
        identical to before. They are purely stored here — no activation logic
        runs yet (that arrives in a later phase).
        """
        limit = max_entries if max_entries is not None else self._history_limit
        now = time.time()

        if not isinstance(entry, MemoryEntry):
            ts = entry.get("ts", now) if isinstance(entry, dict) else now
            entry = MemoryEntry(
                id=_new_id(),
                content=entry,
                timestamp=ts,
                importance=importance,
                tags=tags or [],
            )
        # Apply any explicitly-provided dimensions (override the entry's defaults).
        if aim is not None:
            entry.aim = aim
        if use is not None:
            entry.use = use
        if trigger is not None:
            entry.trigger = trigger
        if ttl is not None and entry.expires_at is None:
            entry.expires_at = now + ttl

        async with self._history_lock:
            history = _decode(await self.get(_HISTORY_KEY))
            history = [e for e in history if not e.is_expired(now)]  # purge expired
            history.append(entry)
            history = _evict(
                history, limit, now=now,
                half_life=self._decay_half_life, fourd=self._fourd_enabled,
            )
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
        include_expired: bool = False,
    ) -> list[MemoryEntry]:
        """Return history entries, optionally filtered.

        Args:
            n:     Return at most the *last* n entries (most recent).
            tags:  If given, only entries that have ALL listed tags are returned.
            since: If given, only entries with timestamp >= since are returned.
            include_expired: If True, do not filter out TTL-expired entries.

        """
        entries = _decode(await self.get(_HISTORY_KEY))
        if not include_expired:
            now = time.time()
            entries = [e for e in entries if not e.is_expired(now)]
        if since is not None:
            entries = [e for e in entries if e.timestamp >= since]
        if tags is not None:
            tag_set = set(tags)
            entries = [e for e in entries if tag_set.issubset(set(e.tags))]
        if n is not None:
            entries = entries[-n:]
        return entries

    async def recent(self, n: int = 5) -> list[MemoryEntry]:
        """Return the n most recent (non-expired) history entries."""
        return await self.get_history(n=n)

    async def recall(
        self,
        query: str,
        k: int = 5,
        tags: list[str] | None = None,
    ) -> list[MemoryEntry]:
        """Unified retrieval combining three strategies, ranked by relevance.

        1. Exact key-value lookup on *query* as a key.
        2. History filtering by *tags* (if given), expired entries excluded.
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

        # 2. Tag-filtered history (expired already excluded by get_history)
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

        if self._fourd_enabled:
            # Rank by 4D activation against the query (tags act as cues). KV/vector
            # synthetic entries carry empty dimensions, so they fall back to their
            # importance exactly as before; only annotated entries reorder.
            ctx = ActivationContext(now=time.time(), query=query, cues=list(tags or []))
            ranked = sorted(
                seen.values(),
                key=lambda e: (-e.activation(ctx, self._decay_half_life), -e.timestamp),
            )
        else:
            ranked = sorted(seen.values(), key=lambda e: (-e.importance, -e.timestamp))
        return ranked[:k]

    # ── pin / unpin ───────────────────────────────────────────────────────────

    async def _reweight(self, entry_id: str, importance: float) -> bool:
        """Set an entry's importance in place. Returns True if found."""
        async with self._history_lock:
            history = _decode(await self.get(_HISTORY_KEY))
            for e in history:
                if e.id == entry_id:
                    e.importance = importance
                    await self.set(_HISTORY_KEY, [h.to_dict() for h in history])
                    return True
        return False

    async def pin(self, entry_id: str) -> bool:
        """Raise an entry's importance to PIN_THRESHOLD so it survives eviction.

        Returns True if the entry was found, False otherwise.
        """
        return await self._reweight(entry_id, _PIN_THRESHOLD)

    async def unpin(self, entry_id: str) -> bool:
        """Reset an entry's importance to 1.0. Returns True if found."""
        return await self._reweight(entry_id, 1.0)

    # ── use-dimension feedback ──────────────────────────────────────────────────

    async def reinforce(self, ids: list[str], reward: float = 0.0) -> int:
        """Record that the given history entries were used, persisting the update.

        Touches each matching entry's ``use`` ledger (count + last_used, and
        accumulates ``reward``), closing the 4D positive-feedback loop: entries
        that keep proving useful gain utility and so rank higher in future recall
        / survive eviction longer. Ids that don't match a history entry (e.g. the
        synthetic ``kv:``/vector ids recall returns) are silently ignored, so it
        is safe to pass a whole recall result. Returns the number updated.
        """
        id_set = {i for i in ids if i}
        if not id_set:
            return 0
        now = time.time()
        async with self._history_lock:
            history = _decode(await self.get(_HISTORY_KEY))
            updated = 0
            for e in history:
                if e.id in id_set:
                    e.use.touch(now, reward)
                    updated += 1
            if updated:
                await self.set(_HISTORY_KEY, [h.to_dict() for h in history])
        return updated

    # ── 4D annotation ───────────────────────────────────────────────────────────

    async def annotate(
        self,
        entry_id: str,
        *,
        mode: UseMode | str | None = None,
        weight: float | None = None,
        intent: str | None = None,
        goal_ref: str | None = None,
        scope: list[str] | None = None,
        cues: list[str] | None = None,
        half_life: float | None = None,
    ) -> bool:
        """Set/merge the 4D dimensions on an existing history entry, in place.

        Each argument is applied only when provided, mutating the entry's living
        ``aim`` / ``use`` / ``trigger`` objects — so ``use.stats`` (the usage
        ledger) is preserved across annotation. This is the *producer* side of
        the 4D engine: it gives a memory a purpose (``intent``/``scope``), an
        application protocol (``mode``/``weight``), and time/cue triggers, which
        the recall, eviction and push paths then score against.

        ``mode`` accepts a :class:`UseMode` or its string value; an unknown
        string is ignored (the entry keeps its current mode). Returns True if the
        entry was found, False otherwise.
        """
        async with self._history_lock:
            history = _decode(await self.get(_HISTORY_KEY))
            for e in history:
                if e.id != entry_id:
                    continue
                if mode is not None:
                    try:
                        e.use.mode = mode if isinstance(mode, UseMode) else UseMode(mode)
                    except ValueError:
                        pass  # unknown mode string → keep current
                if weight is not None:
                    e.use.weight = weight
                if intent is not None:
                    e.aim.intent = intent
                if goal_ref is not None:
                    e.aim.goal_ref = goal_ref
                if scope is not None:
                    e.aim.scope = list(scope)
                if cues is not None:
                    e.trigger.cues = list(cues)
                if half_life is not None:
                    e.trigger.half_life = half_life
                await self.set(_HISTORY_KEY, [h.to_dict() for h in history])
                return True
        return False

    # ── lifecycle: forget / consolidate / stats ────────────────────────────────

    async def forget(
        self,
        tags: list[str] | None = None,
        before: float | None = None,
        expired: bool = False,
    ) -> int:
        """Bulk-remove history entries matching any given criterion.

        An entry is removed if it matches ANY of:
          - has ALL of ``tags``
          - has ``timestamp`` < ``before``
          - is TTL-expired (when ``expired`` is True)

        Pinned entries are removed too if they match — this is an explicit
        instruction, not automatic eviction. With no criteria, removes nothing.
        Returns the number of entries removed.
        """
        if not tags and before is None and not expired:
            return 0
        now = time.time()
        tag_set = set(tags) if tags else None

        def matches(e: MemoryEntry) -> bool:
            if tag_set is not None and tag_set.issubset(set(e.tags)):
                return True
            if before is not None and e.timestamp < before:
                return True
            if expired and e.is_expired(now):
                return True
            return False

        async with self._history_lock:
            history = _decode(await self.get(_HISTORY_KEY))
            kept = [e for e in history if not matches(e)]
            removed = len(history) - len(kept)
            if removed:
                await self.set(_HISTORY_KEY, [e.to_dict() for e in kept])
        return removed

    async def consolidate(
        self,
        api: ModelAPIInterface,
        keep_recent: int = 10,
        min_candidates: int = 3,
        max_chars: int = 4000,
        system_prompt: str | None = None,
    ) -> MemoryEntry | None:
        """Summarise older history into a single pinned entry to free space.

        The most recent ``keep_recent`` entries, plus all pinned entries and any
        prior summaries, are preserved. Remaining older entries are replaced by
        one pinned ``summary`` entry synthesised by ``api``. No-op (returns None)
        when there are fewer than ``min_candidates`` consolidatable entries.

        Args:
            api: an inference model (e.g. the A4 slot) exposing ``complete``.
            keep_recent: number of newest entries to leave untouched.
            min_candidates: minimum old entries required to bother summarising.
            max_chars: cap on the candidate text fed to the model.
            system_prompt: optional override for the consolidation system prompt
                (the P1-C prompt slot). Defaults to
                :data:`autumn.core.memory.prompts.CONSOLIDATE_SYSTEM`.

        """
        async with self._history_lock:
            now = time.time()
            history = [e for e in _decode(await self.get(_HISTORY_KEY)) if not e.is_expired(now)]
            tail = history[-keep_recent:] if keep_recent else []
            head = history[:-keep_recent] if keep_recent else history
            candidates = [e for e in head if not e.is_pinned and "summary" not in e.tags]
            preserved = [e for e in head if e.is_pinned or "summary" in e.tags]
            if len(candidates) < min_candidates:
                return None

            joined = "\n".join(f"- {e.text}" for e in candidates)[:max_chars]
            from ..types import Message, Role
            from .prompts import CONSOLIDATE_SYSTEM, consolidate_instruction
            messages = [
                Message(role=Role.SYSTEM, content=system_prompt or CONSOLIDATE_SYSTEM),
                Message(
                    role=Role.USER,
                    content=consolidate_instruction(len(candidates), joined),
                ),
            ]
            summary_text = await api.complete(messages)

            summary = MemoryEntry(
                id=_new_id(),
                content=summary_text,
                # Slot the summary where the old block lived so order is sane.
                timestamp=max(e.timestamp for e in candidates),
                importance=_PIN_THRESHOLD,
                tags=["summary"],
                meta={"consolidated": len(candidates)},
                # A consolidated digest is, by its nature, a summary-mode memory:
                # this makes the 4D engine treat it as a consolidation priority
                # rather than a plain context snippet.
                use=Use(mode=UseMode.SUMMARIZE),
            )
            new_history = [*preserved, summary, *tail]
            new_history.sort(key=lambda e: e.timestamp)
            await self.set(_HISTORY_KEY, [e.to_dict() for e in new_history])

        if self._vector is not None:
            try:
                await self.index(summary.id, summary.text, {"type": "summary", "area": self.name})
            except Exception:
                pass
        return summary

    async def stats(self) -> dict:
        """Return a snapshot of this area's history for observability.

        Counts live and expired entries, pinned count, tag histogram, time span,
        average importance, and the area's configuration.
        """
        all_entries = await self.get_history(include_expired=True)
        now = time.time()
        live = [e for e in all_entries if not e.is_expired(now)]
        tags: dict[str, int] = {}
        for e in live:
            for t in e.tags:
                tags[t] = tags.get(t, 0) + 1
        timestamps = [e.timestamp for e in live if e.timestamp]
        return {
            "area": self.name,
            "total": len(live),
            "expired": len(all_entries) - len(live),
            "pinned": sum(1 for e in live if e.is_pinned),
            "tags": tags,
            "oldest": min(timestamps) if timestamps else None,
            "newest": max(timestamps) if timestamps else None,
            "avg_importance": (
                round(sum(e.importance for e in live) / len(live), 3) if live else 0.0
            ),
            "history_limit": self._history_limit,
            "decay_half_life": self._decay_half_life,
            "has_vector": self.has_vector,
        }

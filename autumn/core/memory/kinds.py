"""Memory kind conventions (RFC 4D-memory P2-A).

Lightweight typing for memory entries via reserved tags — a "kind" is just a tag
every read/write already understands, so no new ``MemoryEntry`` shape is needed.
Mirrors EverOS's typed memory (episode / atomic_fact / profile / summary / case)
the cheap way: tag conventions + helpers, filterable through the existing
``recall(tags=...)`` / ``get_history(tags=...)`` paths.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import MemoryEntry

KIND_EPISODE = "episode"          # a raw conversation turn / log line
KIND_ATOMIC_FACT = "atomic_fact"  # a discrete, self-contained claim extracted from episodes
KIND_PROFILE = "profile"          # stable user/agent profile facts
KIND_SUMMARY = "summary"          # consolidated digest (already produced by consolidate())
KIND_CASE = "case"                # an agent task experience

ALL_KINDS: tuple[str, ...] = (
    KIND_EPISODE, KIND_ATOMIC_FACT, KIND_PROFILE, KIND_SUMMARY, KIND_CASE,
)

# Kinds that are framework-derived (not raw input) — skipped when re-extracting
# atomic facts so a pass never feeds on its own output.
DERIVED_KINDS: frozenset[str] = frozenset({KIND_ATOMIC_FACT, KIND_SUMMARY})


def is_kind(entry: MemoryEntry, kind: str) -> bool:
    """True if *entry* carries the given kind tag."""
    return kind in getattr(entry, "tags", ())


def kind_of(entry: MemoryEntry) -> str | None:
    """Return the first recognised kind tag on *entry*, or ``None``."""
    tags = getattr(entry, "tags", ()) or ()
    for tag in tags:
        if tag in ALL_KINDS:
            return tag
    return None

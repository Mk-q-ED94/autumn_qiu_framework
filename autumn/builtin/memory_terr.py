"""Memory capability domain — wraps the existing ``recall`` / ``remember`` skills.

The underlying logic lives in :mod:`autumn.core.memory.skills`. This module
re-packages those Skills as a Terr so they slot into the same enable/disable
toggle the desktop UI uses for every other capability domain.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.components.terr import Terr
from ..core.memory.skills import make_memory_skills

if TYPE_CHECKING:
    from ..core.api.base import ModelAPIInterface
    from ..core.memory.base import MemoryArea


def memory_terr(
    memory: "MemoryArea",
    api: "ModelAPIInterface | None" = None,
    *,
    area_name: str = "shared",
) -> Terr:
    """Build the ``memory`` Terr bound to a specific memory area.

    Parameters
    ----------
    memory:
        A :class:`MemoryArea` — typically ``autumn.shared``, ``autumn.mom1``,
        ``autumn.mom2``, or ``autumn.mom3``.
    api:
        Optional A4-style model used to synthesise vector-search results
        into a concise answer. When ``None``, raw snippets are returned.
    area_name:
        Human-readable label appended to the Terr description so the user
        can tell which memory zone these skills target.
    """
    skills = make_memory_skills(memory, api=api)
    return Terr(
        name="memory",
        description=(
            f"Recall and remember facts in the {area_name} memory area. "
            "recall(query) performs exact-key lookup with vector-search fallback; "
            "remember(key, value) persists a fact and auto-indexes when vector "
            "memory is enabled."
        ),
        skills=skills,
    )


__all__ = ["memory_terr"]

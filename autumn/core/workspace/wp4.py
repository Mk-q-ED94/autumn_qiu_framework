"""WP4 — the memory-management workspace.

WP1–WP3 each own a single Mom area and drive the conversation. WP4 owns none of
that flow; it is the dedicated curator of *all* memory, backed by the optional
A4 model slot. Where A4 is configured it powers the cognitive operations —
recall synthesis and consolidation summaries; the mechanical operations
(forget, stats, pin) delegate straight to the target :class:`MemoryArea`.

Zones are addressed by name:

    "mom1" / "mom2" / "mom3"  — the per-workspace memories
    "shared"                  — the cross-workspace shared zone
    "project"                 — the context-active project's zone (when projects
                                are configured)

WP4 keeps its own audit log (``self.memory``) so each management action it
performs — consolidations, forgets, remembers — is itself recorded and
observable, the same way every other workspace logs its turns to its Mom area.
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from .base import WorkspaceBase

if TYPE_CHECKING:
    from ..components.skill import Skill
    from ..memory.base import MemoryArea, MemoryEntry
    from ..memory.project import ProjectMemory


class WP4Mem(WorkspaceBase):
    """Memory workspace (WP4). The A4-backed curator of every memory zone.

    Parameters
    ----------
    api:
        The A4 model interface, or ``None`` when no memory model is configured.
        Operations that need inference (``consolidate``, synthesised ``process``)
        require it; the rest work without.
    memory:
        WP4's own audit-log area. Management actions are appended here so the
        curator's work is itself part of the memory record.
    zones:
        Mapping of zone name → :class:`MemoryArea` that WP4 manages directly
        (typically ``mom1``/``mom2``/``mom3``/``shared``).
    projects:
        Optional :class:`ProjectMemory` manager. When supplied, the ``"project"``
        area resolves to the context-active project's shared zone.
    """

    def __init__(
        self,
        api,
        memory: "MemoryArea",
        zones: "dict[str, MemoryArea]",
        projects: "ProjectMemory | None" = None,
    ):
        super().__init__(api, memory)
        self._zones: dict[str, MemoryArea] = dict(zones)
        self._projects = projects

    # ── model availability ──────────────────────────────────────────────────────

    @property
    def has_model(self) -> bool:
        """True when the A4 slot is configured (enables synthesis / consolidation)."""
        return self.api is not None

    # ── zone resolution ─────────────────────────────────────────────────────────

    def zone_names(self) -> list[str]:
        """Names of every addressable zone, including ``"project"`` when wired."""
        names = list(self._zones)
        if self._projects is not None:
            names.append("project")
        return names

    def _resolve(self, area: str) -> "MemoryArea":
        """Resolve a zone name to a live :class:`MemoryArea`.

        ``"project"`` resolves to the *context-active* project's zone, so the
        same call serves whichever project is bound for the current request.
        """
        if area == "project":
            if self._projects is None:
                raise ValueError("Project memory is not configured.")
            return self._projects.current()
        try:
            return self._zones[area]
        except KeyError:
            raise ValueError(
                f"Unknown memory area: {area!r}. Choose from: {self.zone_names()}"
            ) from None

    # ── audit log ───────────────────────────────────────────────────────────────

    async def _log(self, action: str, area: str, detail: dict) -> None:
        """Record a management action in WP4's own memory. Never raises."""
        try:
            await self.memory.append_history(
                {"ts": time.time(), "action": action, "area": area, **detail},
                tags=["wp4", action],
            )
        except Exception:
            pass  # auditing must never break the operation it describes

    async def audit_log(self, n: int = 20) -> list["MemoryEntry"]:
        """Return the most recent management actions WP4 has performed."""
        return await self.memory.recent(n)

    # ── skills ──────────────────────────────────────────────────────────────────

    def skills(self, area: str = "shared") -> list["Skill"]:
        """Build memory skills bound to a zone, wired to WP4's A4 model.

        Returns ``[recall, remember, list_recent, pin_memory]``. ``area="project"``
        returns project-scoped variants that resolve the context-active project's
        zone at call time, so one registration serves every project.
        """
        from ..memory.skills import make_memory_skills, make_project_memory_skills

        if area == "project":
            if self._projects is None:
                raise ValueError("Project memory is not configured.")
            return make_project_memory_skills(self._projects, api=self.api)
        return make_memory_skills(self._resolve(area), api=self.api)

    # ── recall / remember ───────────────────────────────────────────────────────

    async def recall(
        self, query: str, area: str = "shared", k: int = 5
    ) -> list["MemoryEntry"]:
        """Unified retrieval (exact key → tags → semantic) over a zone."""
        return await self._resolve(area).recall(query, k=k)

    async def remember(self, key: str, value: Any, area: str = "shared") -> None:
        """Persist a fact under ``key`` in a zone, indexing it when vectors exist."""
        zone = self._resolve(area)
        await zone.set(key, value)
        if zone.has_vector:
            await zone.index(key, f"{key}: {value}")
        await self._log("remember", area, {"key": key})

    # ── consolidate ─────────────────────────────────────────────────────────────

    async def consolidate(
        self,
        area: str = "shared",
        keep_recent: int = 10,
        min_candidates: int = 3,
    ) -> "MemoryEntry | None":
        """Summarise a zone's older history into one pinned entry via A4.

        Raises ``RuntimeError`` when no A4 model is configured. Returns ``None``
        when there is too little to summarise.
        """
        if not self.has_model:
            raise RuntimeError(
                "Memory consolidation needs the A4 model slot; none is configured."
            )
        summary = await self._resolve(area).consolidate(
            self.api, keep_recent=keep_recent, min_candidates=min_candidates
        )
        await self._log(
            "consolidate",
            area,
            {
                "consolidated": summary.meta.get("consolidated") if summary else 0,
                "noop": summary is None,
            },
        )
        return summary

    async def consolidate_all(
        self, keep_recent: int = 10, min_candidates: int = 3
    ) -> "dict[str, MemoryEntry | None]":
        """Run :meth:`consolidate` across every directly-managed zone.

        Project zones are dynamic and per-request, so they are not swept here —
        consolidate a project explicitly with ``area="project"`` under a
        :func:`project_context`.
        """
        return {
            name: await self.consolidate(
                name, keep_recent=keep_recent, min_candidates=min_candidates
            )
            for name in self._zones
        }

    # ── forget ──────────────────────────────────────────────────────────────────

    async def forget(
        self,
        area: str = "shared",
        tags: list[str] | None = None,
        before: float | None = None,
        expired: bool = False,
    ) -> int:
        """Bulk-remove matching history entries from a zone. Returns the count."""
        removed = await self._resolve(area).forget(
            tags=tags, before=before, expired=expired
        )
        if removed:
            await self._log(
                "forget",
                area,
                {"removed": removed, "tags": tags, "before": before, "expired": expired},
            )
        return removed

    # ── pin / unpin ─────────────────────────────────────────────────────────────

    async def pin(self, entry_id: str, area: str = "shared") -> bool:
        """Pin an entry so it survives eviction. Returns True if found."""
        return await self._resolve(area).pin(entry_id)

    async def unpin(self, entry_id: str, area: str = "shared") -> bool:
        """Reset a pinned entry to normal importance. Returns True if found."""
        return await self._resolve(area).unpin(entry_id)

    # ── stats ───────────────────────────────────────────────────────────────────

    async def stats(self, area: str | None = None) -> dict:
        """Observability snapshot for one zone, or every managed zone at once.

        With ``area`` set, returns that zone's :meth:`MemoryArea.stats`. With
        ``area=None``, returns ``{"zones": {...}, "total": int, "areas": [...]}``
        aggregating all directly-managed zones.
        """
        if area is not None:
            return await self._resolve(area).stats()
        zones = {name: await zone.stats() for name, zone in self._zones.items()}
        return {
            "zones": zones,
            "total": sum(z.get("total", 0) for z in zones.values()),
            "areas": list(zones),
        }

    # ── WorkspaceBase compliance ────────────────────────────────────────────────

    async def process(self, query: str) -> str:
        """Answer a natural-language question from memory (the shared zone).

        This is WP4's entry point as a workspace: ask the memory system a
        question. When A4 is configured the matching entries are synthesised into
        a direct answer; otherwise they are returned as a formatted list.
        """
        entries = await self.recall(query, area="shared")
        if not entries:
            return f"[no memory found for '{query}']"
        snippets = "\n".join(f"- {e.text}" for e in entries)
        if not self.has_model:
            return snippets
        from ..types import Message, Role

        messages = [
            Message(
                role=Role.SYSTEM,
                content=(
                    "You are a memory assistant. Synthesise the stored facts into "
                    "a direct, concise answer."
                ),
            ),
            Message(
                role=Role.USER,
                content=f"Using these memory entries, answer: {query!r}\n\n{snippets}",
            ),
        ]
        return await self.api.complete(messages)

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

WP4 also provides A4-powered project intelligence:

* :meth:`draft_description` — synthesise a project description from free text
* :meth:`draft_goals` — structure goals into master / long-term / short-term
* :meth:`infer_environment` — suggest terrs, skills, tools, MCP, agent channel
"""
from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from ..memory.dimensions import ActivationContext, UseMode
from .base import WorkspaceBase

if TYPE_CHECKING:
    from ..components.skill import Skill
    from ..memory.base import MemoryArea, MemoryEntry
    from ..memory.project import ProjectGoals, ProjectMemory, ProjectMeta

# Modes that surface proactively at turn start (push). CONTEXT is pull-only,
# SUMMARIZE feeds consolidation — neither is injected by the push engine.
_PUSH_MODES = (UseMode.CONSTRAIN, UseMode.REMIND)


def _render_one(entry: MemoryEntry) -> str:
    """One activated memory as a line, applying its use.template when present."""
    template = entry.use.template
    if template:
        try:
            return template.format(content=entry.text)
        except (KeyError, IndexError, ValueError):
            pass
    return entry.text


def render_push_context(entries: list[MemoryEntry]) -> str:
    """Render push-activated memories into an injectable prompt fragment.

    CONSTRAIN entries become a "must follow" rules block; REMIND entries become
    a reminders block. Returns "" when there is nothing to inject, so callers can
    unconditionally prepend the result.
    """
    constraints = [e for e in entries if e.use.mode == UseMode.CONSTRAIN]
    reminders = [e for e in entries if e.use.mode == UseMode.REMIND]
    blocks: list[str] = []
    if constraints:
        lines = "\n".join(f"- {_render_one(e)}" for e in constraints)
        blocks.append(f"Active constraints (must follow):\n{lines}")
    if reminders:
        lines = "\n".join(f"- {_render_one(e)}" for e in reminders)
        blocks.append(f"Active reminders:\n{lines}")
    return "\n\n".join(blocks)


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
        memory: MemoryArea,
        zones: dict[str, MemoryArea],
        projects: ProjectMemory | None = None,
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

    def _resolve(self, area: str) -> MemoryArea:
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
                f"Unknown memory area: {area!r}. Choose from: {self.zone_names()}",
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

    async def audit_log(self, n: int = 20) -> list[MemoryEntry]:
        """Return the most recent management actions WP4 has performed."""
        return await self.memory.recent(n)

    # ── skills ──────────────────────────────────────────────────────────────────

    def skills(self, area: str = "shared") -> list[Skill]:
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
        self, query: str, area: str = "shared", k: int = 5,
    ) -> list[MemoryEntry]:
        """Unified retrieval (exact key → tags → semantic) over a zone."""
        return await self._resolve(area).recall(query, k=k)

    async def remember(self, key: str, value: Any, area: str = "shared") -> None:
        """Persist a fact under ``key`` in a zone, indexing it when vectors exist."""
        zone = self._resolve(area)
        await zone.set(key, value)
        if zone.has_vector:
            await zone.index(key, f"{key}: {value}")
        await self._log("remember", area, {"key": key})

    # ── activate (pull) ─────────────────────────────────────────────────────────

    async def activate(
        self,
        query: str,
        area: str = "shared",
        k: int = 5,
        tags: list[str] | None = None,
        reward: float = 0.0,
        reinforce: bool = True,
    ) -> list[MemoryEntry]:
        """Pull-activate a zone's memories for *query*, closing the feedback loop.

        Ranks via the zone's :meth:`MemoryArea.recall` (4D activation when the
        zone has it enabled), then — unless ``reinforce`` is False — records the
        hits in their ``use`` ledger (with ``reward``) so repeated usefulness
        raises their future activation and slows their eviction. Each returned
        entry carries its ``use.mode``, telling the caller *how* to apply it
        (context / remind / constrain / summarize). Needs no A4 model.

        This is the pull side of the activation engine; the push side (firing
        memories on a turn/event) builds on the same reinforcement primitive.
        """
        zone = self._resolve(area)
        entries = await zone.recall(query, k=k, tags=tags)
        if reinforce and entries:
            await zone.reinforce([e.id for e in entries], reward=reward)
        await self._log("activate", area, {"query": query, "tags": tags, "hits": len(entries)})
        return entries

    async def activate_push(
        self,
        area: str = "shared",
        ctx: ActivationContext | None = None,
        k: int = 5,
        reinforce: bool = False,
    ) -> list[MemoryEntry]:
        """Push side of the engine: scan a zone and fire turn-relevant memories.

        Query-less. Only ``CONSTRAIN``/``REMIND`` entries are candidates (those
        are the proactively-surfaced modes); among them, an entry fires when its
        ``trigger`` and ``aim`` gates open against *ctx* (empty gates = always
        fire). Results are ranked by 4D activation, newest breaking ties. Unlike
        pull, reinforcement defaults **off** — a memory auto-surfaced by the turn
        wasn't deliberately used, so it shouldn't inflate its own utility.

        Returns the firing entries (each carrying its ``use.mode``); pair with
        :func:`render_push_context` to get an injectable prompt fragment.
        """
        ctx = ctx or ActivationContext()
        zone = self._resolve(area)
        scored: list[tuple[float, MemoryEntry]] = []
        for e in await zone.get_history():
            if e.use.mode not in _PUSH_MODES:
                continue
            score = e.activation(ctx)
            if score > 0:
                scored.append((score, e))
        scored.sort(key=lambda pair: (-pair[0], -pair[1].timestamp))
        fired = [e for _, e in scored[:k]]
        if reinforce and fired:
            await zone.reinforce([e.id for e in fired], reward=0.0)
        await self._log("activate_push", area, {"fired": [e.id for e in fired]})
        return fired

    # ── consolidate ─────────────────────────────────────────────────────────────

    async def consolidate(
        self,
        area: str = "shared",
        keep_recent: int = 10,
        min_candidates: int = 3,
    ) -> MemoryEntry | None:
        """Summarise a zone's older history into one pinned entry via A4.

        Raises ``RuntimeError`` when no A4 model is configured. Returns ``None``
        when there is too little to summarise.
        """
        if not self.has_model:
            raise RuntimeError(
                "Memory consolidation needs the A4 model slot; none is configured.",
            )
        summary = await self._resolve(area).consolidate(
            self.api, keep_recent=keep_recent, min_candidates=min_candidates,
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
        self, keep_recent: int = 10, min_candidates: int = 3,
    ) -> dict[str, MemoryEntry | None]:
        """Run :meth:`consolidate` across every directly-managed zone.

        Project zones are dynamic and per-request, so they are not swept here —
        consolidate a project explicitly with ``area="project"`` under a
        :func:`project_context`.
        """
        return {
            name: await self.consolidate(
                name, keep_recent=keep_recent, min_candidates=min_candidates,
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
            tags=tags, before=before, expired=expired,
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

    # ── project intelligence (A4-powered) ──────────────────────────────────────

    def _require_model(self, op: str) -> None:
        if not self.has_model:
            raise RuntimeError(
                f"{op} needs the A4 model slot; none is configured.",
            )

    def _require_projects(self) -> ProjectMemory:
        if self._projects is None:
            raise ValueError("Project memory is not configured.")
        return self._projects

    @staticmethod
    def _extract_json(text: str) -> str:
        """Strip markdown fences so json.loads can parse AI responses."""
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts[1::2]:  # odd parts are inside fences
                code = part.strip()
                if code.lower().startswith("json"):
                    code = code[4:].strip()
                if code.startswith(("{", "[")):
                    return code
        return text

    async def draft_description(self, user_input: str, project_id: str) -> str:
        """Synthesise a concise project description from the user's free-text input.

        The result is *not* persisted automatically — call
        ``projects.update_metadata(project_id, description=result)`` to save it.
        """
        self._require_model("Description drafting")
        self._require_projects()
        from ..types import Message, Role

        messages = [
            Message(
                role=Role.SYSTEM,
                content=(
                    "You are a project assistant. The user will describe their project idea. "
                    "Synthesise a clear, concise project description (2–4 sentences). "
                    "Return only the description text, no preamble or commentary."
                ),
            ),
            Message(role=Role.USER, content=user_input),
        ]
        result = await self.api.complete(messages)
        return result.strip()

    async def draft_goals(self, user_input: str, project_id: str) -> ProjectGoals:
        """Structure the user's goal description into master / long-term / short-term.

        Returns a :class:`~autumn.core.memory.project.ProjectGoals` instance.
        The result is *not* persisted automatically — call
        ``projects.update_metadata(project_id, goals=result.to_dict())`` to save it.
        """
        self._require_model("Goals drafting")
        projects = self._require_projects()
        from ..memory.project import ProjectGoals
        from ..types import Message, Role

        meta = await projects.zone(project_id).get_meta()
        desc_context = f"Project description: {meta.description}\n\n" if meta.description else ""

        messages = [
            Message(
                role=Role.SYSTEM,
                content=(
                    "You are a project planning assistant. Structure the user's goals into "
                    "one master goal, a list of long-term goals, and a list of short-term goals. "
                    'Respond ONLY with valid JSON: {"master": "...", "long_term": ["..."], "short_term": ["..."]}'
                ),
            ),
            Message(
                role=Role.USER,
                content=f"{desc_context}Goals description: {user_input}",
            ),
        ]
        response = await self.api.complete(messages)
        try:
            data = json.loads(self._extract_json(response))
            return ProjectGoals.from_dict(data)
        except (json.JSONDecodeError, ValueError, AttributeError):
            return ProjectGoals(master=response.strip()[:300])

    async def infer_environment(self, project_id: str) -> ProjectMeta:
        """Infer an appropriate environment config for *project_id* using A4.

        Reads the project's type, description, and master goal, calls A4 to
        suggest terrs / skills / tools / MCP / agent channel, and **persists**
        the result back into the project's metadata. Returns the full updated
        :class:`~autumn.core.memory.project.ProjectMeta`.
        """
        self._require_model("Environment inference")
        projects = self._require_projects()
        from ..memory.project import ProjectEnvironment
        from ..types import Message, Role

        zone = projects.zone(project_id)
        meta = await zone.get_meta()

        messages = [
            Message(
                role=Role.SYSTEM,
                content=(
                    "You are a project setup assistant. Based on the project information, "
                    "suggest an appropriate runtime environment configuration. "
                    "Respond ONLY with valid JSON in exactly this shape:\n"
                    '{"terrs": [...], "skills": [...], "tools": [...], '
                    '"mcp": [...], "agent_channel": "name_or_null"}\n'
                    "Use short lowercase identifiers. Keep each list concise (2–5 items). "
                    'Set "agent_channel" to null if none is needed.'
                ),
            ),
            Message(
                role=Role.USER,
                content=(
                    f"Project type: {meta.project_type or 'unspecified'}\n"
                    f"Description: {meta.description or '(none)'}\n"
                    f"Master goal: {meta.goals.master or '(none)'}"
                ),
            ),
        ]
        response = await self.api.complete(messages)
        try:
            data = json.loads(self._extract_json(response))
            meta.environment = ProjectEnvironment.from_dict(data)
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass  # leave environment unchanged if A4 returns unparseable output
        await zone.set_meta(meta)
        await self._log("infer_environment", "project", {"project_id": project_id})
        return meta

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

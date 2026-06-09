"""Per-project shared memory zones.

Each project gets its own isolated memory namespace, but *within* a project the
zone behaves like :class:`~autumn.core.memory.shared.SharedZone` — every
workspace and every turn reads and writes the same data. That is what makes a
project zone "shared": shared across the project, isolated between projects.

A :class:`ProjectMemory` manager owns one backend and hands out lazily-created,
cached :class:`ProjectZone` instances keyed by project id. The active project
for a request is carried in a :class:`contextvars.ContextVar` so project-scoped
skills resolve to the right zone without threading the id through every call.

    pm = ProjectMemory(DictBackend())
    with project_context("acme-app"):
        zone = pm.current()          # → ProjectZone("acme-app")
        await zone.set("api", "v2")  # isolated from every other project

Each project also carries structured metadata (:class:`ProjectMeta`) stored
under a reserved key inside its zone:

* **project_type** — category tag (``"code"``, ``"research"``, etc.) or None
* **description** — free-text summary (written directly or AI-generated)
* **goals** — one master goal + lists of long-term and short-term goals
* **files** — paths of user-added or conversation-generated files
* **environment** — AI-inferred terrs, skills, tools, MCP servers, agent channel
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Iterator

from .base import MemoryArea, MemoryBackend

# Reserved key within each ProjectZone's backend namespace for structured metadata.
_META_KEY = "__meta__"

# Active project for the current async context. The server sets this per request
# so project-scoped memory resolves to the right zone without threading the id
# through every workspace and skill call site.
_current_project: ContextVar[str | None] = ContextVar(
    "autumn_current_project", default=None
)

_REGISTRY = "__projects__"
_DEFAULT_ID = "default"
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


# ── project metadata dataclasses ─────────────────────────────────────────────

@dataclass
class ProjectGoals:
    """Structured goal hierarchy for a project."""

    master: str = ""
    long_term: list[str] = field(default_factory=list)
    short_term: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "master": self.master,
            "long_term": list(self.long_term),
            "short_term": list(self.short_term),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectGoals":
        return cls(
            master=d.get("master", ""),
            long_term=list(d.get("long_term") or []),
            short_term=list(d.get("short_term") or []),
        )


@dataclass
class ProjectEnvironment:
    """AI-inferred runtime environment for a project."""

    terrs: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    mcp: list[str] = field(default_factory=list)
    agent_channel: str | None = None

    def to_dict(self) -> dict:
        return {
            "terrs": list(self.terrs),
            "skills": list(self.skills),
            "tools": list(self.tools),
            "mcp": list(self.mcp),
            "agent_channel": self.agent_channel,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectEnvironment":
        return cls(
            terrs=list(d.get("terrs") or []),
            skills=list(d.get("skills") or []),
            tools=list(d.get("tools") or []),
            mcp=list(d.get("mcp") or []),
            agent_channel=d.get("agent_channel"),
        )


@dataclass
class ProjectMeta:
    """All structured metadata attached to a project zone.

    Stored as a JSON dict under the ``__meta__`` key inside the zone's backend
    namespace so it persists alongside memory entries and survives restarts.
    """

    project_type: str | None = None
    description: str = ""
    goals: ProjectGoals = field(default_factory=ProjectGoals)
    files: list[str] = field(default_factory=list)
    environment: ProjectEnvironment = field(default_factory=ProjectEnvironment)

    def to_dict(self) -> dict:
        return {
            "project_type": self.project_type,
            "description": self.description,
            "goals": self.goals.to_dict(),
            "files": list(self.files),
            "environment": self.environment.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectMeta":
        return cls(
            project_type=d.get("project_type"),
            description=d.get("description", ""),
            goals=ProjectGoals.from_dict(d.get("goals") or {}),
            files=list(d.get("files") or []),
            environment=ProjectEnvironment.from_dict(d.get("environment") or {}),
        )


def _sanitize(project_id: str) -> str:
    """Make a project id safe to embed in a backend key namespace.

    Backend keys are ``"{area}:{key}"`` so the id must not contain ``:``.
    Runs of disallowed characters collapse to ``_``; empty ids become ``default``.
    """
    cleaned = _UNSAFE.sub("_", (project_id or "").strip())
    return cleaned or _DEFAULT_ID


# ── contextvar helpers ──────────────────────────────────────────────────────────

def set_current_project(project_id: str | None) -> Token:
    """Bind ``project_id`` to the current context. Returns a reset token."""
    return _current_project.set(project_id)


def get_current_project() -> str | None:
    """Return the project id bound to the current context, if any."""
    return _current_project.get()


def reset_current_project(token: Token) -> None:
    """Undo a prior :func:`set_current_project`, restoring the previous binding."""
    _current_project.reset(token)


@contextmanager
def project_context(project_id: str | None) -> Iterator[None]:
    """Scope ``project_id`` to a block; restores the prior value on exit.

    ContextVar mutations propagate to coroutines and tasks spawned inside the
    block, so any project-scoped memory skill invoked during the wrapped work
    sees this project.
    """
    token = set_current_project(project_id)
    try:
        yield
    finally:
        reset_current_project(token)


# ── zones ────────────────────────────────────────────────────────────────────────

class ProjectZone(MemoryArea):
    """A per-project shared memory zone.

    Each project id maps to its own namespace within the backend, so two
    projects never collide even though they share one backend. Within a project
    the zone behaves exactly like :class:`SharedZone` — every workspace and turn
    reads and writes the same data, which is what makes it *shared*.

    Structured project metadata (:class:`ProjectMeta`) is stored as a plain
    JSON dict under the reserved ``__meta__`` key.  All other zone operations
    (history, recall, remember) remain unaffected.
    """

    def __init__(
        self,
        project_id: str,
        backend: MemoryBackend,
        history_limit: int = 50,
        decay_half_life: float | None = None,
    ):
        super().__init__(
            f"project:{_sanitize(project_id)}", backend,
            history_limit=history_limit,
            decay_half_life=decay_half_life,
        )
        self.project_id = project_id

    # ── metadata ──────────────────────────────────────────────────────────────

    async def get_meta(self) -> ProjectMeta:
        """Return the project's structured metadata (empty defaults if not set)."""
        raw = await self.get(_META_KEY)
        if isinstance(raw, dict):
            return ProjectMeta.from_dict(raw)
        return ProjectMeta()

    async def set_meta(self, meta: ProjectMeta) -> None:
        """Persist the full :class:`ProjectMeta` for this project."""
        await self.set(_META_KEY, meta.to_dict())

    async def update_meta(self, **kwargs) -> ProjectMeta:
        """Merge ``kwargs`` into the existing metadata and persist. Returns updated meta.

        Nested keys ``"goals"`` and ``"environment"`` are merged shallowly so
        callers can update individual fields without overwriting others::

            await zone.update_meta(goals={"master": "ship v2"})  # long_term unchanged
        """
        meta = await self.get_meta()
        for key, value in kwargs.items():
            if key == "goals" and isinstance(value, dict):
                d = meta.goals.to_dict()
                d.update(value)
                meta.goals = ProjectGoals.from_dict(d)
            elif key == "environment" and isinstance(value, dict):
                d = meta.environment.to_dict()
                d.update(value)
                meta.environment = ProjectEnvironment.from_dict(d)
            elif hasattr(meta, key):
                setattr(meta, key, value)
        await self.set_meta(meta)
        return meta

    async def add_file(self, path: str) -> None:
        """Append ``path`` to the project's file list (idempotent)."""
        meta = await self.get_meta()
        if path not in meta.files:
            meta.files.append(path)
            await self.set_meta(meta)

    async def remove_file(self, path: str) -> None:
        """Remove ``path`` from the project's file list. No-op if not present."""
        meta = await self.get_meta()
        new_files = [f for f in meta.files if f != path]
        if len(new_files) != len(meta.files):
            meta.files = new_files
            await self.set_meta(meta)


class ProjectMemory:
    """Lazily-created, cached per-project shared zones over a single backend.

    ``zone(id)`` returns the dedicated :class:`ProjectZone` for a project,
    creating and caching it on first use. ``current()`` resolves the zone for
    the context-active project (see :func:`set_current_project`), falling back
    to a ``default`` project when none is set.
    """

    def __init__(
        self,
        backend: MemoryBackend,
        history_limit: int = 50,
        default_id: str = _DEFAULT_ID,
        decay_half_life: float | None = None,
    ):
        self._backend = backend
        self._history_limit = history_limit
        self._decay_half_life = decay_half_life or None
        self._default_id = default_id
        self._zones: dict[str, ProjectZone] = {}
        # Persistent index of original ids so list_projects can report the ids
        # callers actually used, not just their sanitized namespaces.
        self._registry = MemoryArea(_REGISTRY, backend)

    def zone(self, project_id: str | None = None) -> ProjectZone:
        """Return (creating if needed) the shared zone for ``project_id``."""
        pid = project_id if project_id else self._default_id
        safe = _sanitize(pid)
        if safe not in self._zones:
            self._zones[safe] = ProjectZone(
                pid, self._backend,
                history_limit=self._history_limit,
                decay_half_life=self._decay_half_life,
            )
        return self._zones[safe]

    def current(self) -> ProjectZone:
        """Return the zone for the context-active project (or the default)."""
        return self.zone(get_current_project())

    async def register(self, project_id: str) -> ProjectZone:
        """Record a project in the persistent registry and return its zone.

        Storing the original (unsanitised) id lets :meth:`list_projects` report
        the ids callers actually used, even across restarts. Idempotent.
        """
        zone = self.zone(project_id)
        await self._registry.set(_sanitize(project_id), project_id)
        return zone

    async def list_projects(self) -> list[str]:
        """Return the original ids of all known projects, sorted.

        Reads the persistent registry first; if it is empty (e.g. zones were
        created without :meth:`register`), falls back to scanning the backend
        keyspace for project namespaces.
        """
        originals = [
            orig
            for safe in await self._registry.keys()
            if (orig := await self._registry.get(safe))
        ]
        if originals:
            return sorted(originals)
        # Fallback: discover sanitized ids straight from the backend keyspace.
        prefix = "project:"
        seen: set[str] = set()
        for key in await self._backend.keys():
            if key.startswith(prefix):
                seen.add(key[len(prefix):].split(":", 1)[0])
        return sorted(seen)

    async def clear_project(self, project_id: str) -> None:
        """Erase all memory for a project and drop it from the registry."""
        safe = _sanitize(project_id)
        await self.zone(project_id).clear()
        await self._registry.delete(safe)
        self._zones.pop(safe, None)

    # ── metadata helpers ──────────────────────────────────────────────────────

    async def get_metadata(self, project_id: str) -> ProjectMeta:
        """Return the :class:`ProjectMeta` for *project_id*."""
        return await self.zone(project_id).get_meta()

    async def update_metadata(self, project_id: str, **kwargs) -> ProjectMeta:
        """Merge ``kwargs`` into *project_id*'s metadata. See :meth:`ProjectZone.update_meta`."""
        return await self.zone(project_id).update_meta(**kwargs)

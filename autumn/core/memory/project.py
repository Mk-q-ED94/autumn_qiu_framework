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
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

from .base import MemoryArea, MemoryBackend

# Active project for the current async context. The server sets this per request
# so project-scoped memory resolves to the right zone without threading the id
# through every workspace and skill call site.
_current_project: ContextVar[str | None] = ContextVar(
    "autumn_current_project", default=None
)

_REGISTRY = "__projects__"
_DEFAULT_ID = "default"
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


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

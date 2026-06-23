"""Memory capability domain — wraps the existing ``recall`` / ``remember`` skills.

The underlying logic lives in :mod:`autumn.core.memory.skills`. This module
re-packages those Skills as a Terr so they slot into the same enable/disable
toggle the desktop UI uses for every other capability domain.

Optional MCP integration:
    Pass ``mcp_memory_client`` (from :func:`autumn.builtin.mcp_catalog.mcp_memory`)
    to add the official ``@modelcontextprotocol/server-memory`` persistent KV graph
    as a supplemental MCP.  The framework's ``add_terr`` pipeline connects and
    bridges it automatically alongside the built-in recall/remember skills.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.components.terr import Terr
from ..core.memory.skills import make_memory_skills, make_project_memory_skills

if TYPE_CHECKING:
    from ..core.api.base import ModelAPIInterface
    from ..core.components.mcp_stdio import StdioMCPClient
    from ..core.memory.base import MemoryArea
    from ..core.memory.project import ProjectMemory


def memory_terr(
    memory: MemoryArea,
    api: ModelAPIInterface | None = None,
    *,
    area_name: str = "shared",
    mcp_memory_client: "StdioMCPClient | None" = None,
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
    mcps = [mcp_memory_client] if mcp_memory_client is not None else []
    return Terr(
        name="memory",
        description=(
            f"Recall and remember facts in the {area_name} memory area. "
            "recall(query) performs exact-key lookup with vector-search fallback; "
            "remember(key, value) persists a fact and auto-indexes when vector "
            "memory is enabled."
        ),
        skills=skills,
        mcps=mcps,
    )


def project_memory_terr(
    projects: ProjectMemory,
    api: ModelAPIInterface | None = None,
) -> Terr:
    """Build the ``memory`` Terr bound to the context-active project's shared zone.

    Same skills as :func:`memory_terr`, but each call reads/writes whichever
    project is active for the current request (see ``Autumn.project_scope``).
    Use this when memory should be isolated per project rather than global.
    """
    skills = make_project_memory_skills(projects, api=api)
    return Terr(
        name="memory",
        description=(
            "Recall and remember facts in the current project's shared memory "
            "zone. Each project keeps its own isolated memory; within a project "
            "the zone is shared across all workspaces and turns. "
            "recall(query) performs exact-key lookup with vector-search fallback; "
            "remember(key, value) persists a fact."
        ),
        skills=skills,
    )


__all__ = ["memory_terr", "project_memory_terr"]

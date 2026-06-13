"""Built-in capability domains (Terrs) for the Autumn framework.

The framework ships with a curated set of Terr factories so common agent
chores — telling time, doing arithmetic, parsing JSON, fetching URLs — don't
have to be re-implemented for every new project. Import what you need:

    from autumn.builtin import time_terr, math_terr, register_safe_builtins

    # Pick individual domains
    autumn.register_terr(time_terr())
    autumn.register_terr(math_terr())

    # Or wire up everything that is sandboxed/offline-safe by default
    register_safe_builtins(autumn)

    # Network and filesystem need explicit opt-in
    autumn.register_terr(web_terr())
    autumn.register_terr(fs_terr(root="/tmp/agent-workspace"))

For external MCP servers, see :mod:`autumn.builtin.mcp_catalog` — factories
for the official ``filesystem``, ``fetch``, ``git``, ``sqlite``, ``brave-search``,
``github``, ``puppeteer`` and ``memory`` MCP servers.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .collection_terr import collection_terr
from .data_terr import data_terr
from .encoding_terr import encoding_terr
from .fs_terr import fs_terr
from .math_terr import math_terr
from .mcp_catalog import (
    KNOWN_MCPS,
    mcp_brave_search,
    mcp_everything,
    mcp_fetch,
    mcp_filesystem,
    mcp_git,
    mcp_github,
    mcp_gitlab,
    mcp_google_maps,
    mcp_memory,
    mcp_postgres,
    mcp_puppeteer,
    mcp_sequential_thinking,
    mcp_slack,
    mcp_sqlite,
    mcp_time,
)
from .memory_terr import memory_terr, project_memory_terr
from .text_terr import text_terr
from .time_terr import time_terr
from .web_terr import web_terr

if TYPE_CHECKING:
    from ..core.framework import Autumn


# ── Terr factories grouped by safety / dependency profile ────────────────────

#: Terrs that need no configuration, make no network calls, touch no files.
SAFE_TERR_FACTORIES = (
    time_terr, math_terr, text_terr, data_terr, encoding_terr, collection_terr,
)


def register_safe_builtins(autumn: Autumn) -> list[str]:
    """Register the always-safe Terrs onto ``autumn``.

    Always safe = no network, no filesystem, no external setup. Returns the
    names of the Terrs that were registered, in order, for easy logging.
    """
    names: list[str] = []
    for factory in SAFE_TERR_FACTORIES:
        terr = factory()
        autumn.register_terr(terr)
        names.append(terr.name)
    return names


def register_builtins(
    autumn: Autumn,
    *,
    include_web: bool = False,
    fs_root: str | None = None,
    include_memory: bool = False,
    memory_area: str = "shared",
) -> list[str]:
    """Register a wider set of Terrs onto ``autumn`` based on opt-in flags.

    Parameters
    ----------
    autumn:
        The :class:`Autumn` instance.
    include_web:
        Register :func:`web_terr`. Off by default because the model will gain
        outbound network access.
    fs_root:
        If set, register :func:`fs_terr` sandboxed at this directory. The
        directory must exist.
    include_memory:
        If True, register :func:`memory_terr` bound to ``memory_area``.
    memory_area:
        Which area to bind the memory Terr to: ``shared``, ``mom1``, ``mom2``,
        ``mom3``, or ``project``. ``project`` binds to the context-active
        project's shared zone (per-project isolated memory). Ignored unless
        ``include_memory`` is True.

    """
    names = register_safe_builtins(autumn)
    if include_web:
        terr = web_terr()
        autumn.register_terr(terr)
        names.append(terr.name)
    if fs_root is not None:
        terr = fs_terr(fs_root)
        autumn.register_terr(terr)
        names.append(terr.name)
    if include_memory:
        if memory_area == "project":
            terr = project_memory_terr(autumn.projects, api=autumn.a4)
        else:
            areas = {
                "shared": autumn.shared,
                "mom1": autumn.mom1,
                "mom2": autumn.mom2,
                "mom3": autumn.mom3,
            }
            if memory_area not in areas:
                raise ValueError(f"Unknown memory area: {memory_area!r}")
            terr = memory_terr(areas[memory_area], api=autumn.a4, area_name=memory_area)
        autumn.register_terr(terr)
        names.append(terr.name)
    return names


__all__ = [
    # individual terr factories
    "time_terr",
    "math_terr",
    "text_terr",
    "data_terr",
    "encoding_terr",
    "collection_terr",
    "web_terr",
    "fs_terr",
    "memory_terr",
    "project_memory_terr",
    # helpers
    "register_safe_builtins",
    "register_builtins",
    "SAFE_TERR_FACTORIES",
    # mcp catalog
    "mcp_filesystem",
    "mcp_fetch",
    "mcp_git",
    "mcp_sqlite",
    "mcp_brave_search",
    "mcp_github",
    "mcp_puppeteer",
    "mcp_memory",
    "mcp_postgres",
    "mcp_slack",
    "mcp_gitlab",
    "mcp_google_maps",
    "mcp_sequential_thinking",
    "mcp_time",
    "mcp_everything",
    "KNOWN_MCPS",
]

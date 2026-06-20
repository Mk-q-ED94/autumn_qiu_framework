from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

from ..components.mcp_bridge import _unwrap_content

if TYPE_CHECKING:
    from ..components.mcp import MCPClient

_BRIEF_MAX_CHARS = 1400


class CodebaseMemory:
    """Framework-owned code-graph subsystem — the token-saving layer.

    Wraps a *connected* ``codebase-memory-mcp`` client and lifts it from 14 raw
    tools to a first-class capability:

    - :meth:`ensure_indexed` indexes the repo once (idempotent), so the graph is
      ready without the agent having to ask.
    - :meth:`architecture_brief` returns a compact, cached structural digest that
      WP2 injects into code tasks — the proactive half of the token saving.

    The raw graph tools (``search_graph`` / ``trace_path`` / ``query_graph`` …)
    stay available to the agent through the ``codebase`` Terr for deeper queries;
    this class is the framework's *proactive* use of the same server.

    Every method is failure-tolerant: a missing binary, an un-indexed repo, or a
    slow server degrades to an empty result and never raises into a turn.
    """

    def __init__(self, client: MCPClient, repo: str | None = None):
        self._client = client
        self._repo = (repo or "").strip()
        self._indexed = False
        self._brief: str | None = None
        # Serialises index/brief so concurrent code tasks index only once.
        self._lock = asyncio.Lock()

    @property
    def repo(self) -> str:
        return self._repo

    @property
    def indexed(self) -> bool:
        return self._indexed

    def project_name(self) -> str:
        """Best-effort project id for graph queries — the repo basename.

        ``codebase-memory-mcp`` keys projects by the indexed path; the basename
        is the human label it reports. Empty when no repo is scoped (the server
        then operates on its single default project).
        """
        if not self._repo:
            return ""
        return os.path.basename(self._repo.rstrip("/")) or self._repo

    async def _call(self, name: str, args: dict) -> str:
        """Invoke an MCP tool and flatten its content to text. "" on any failure."""
        try:
            return _unwrap_content(await self._client.call_tool(name, args))
        except Exception:
            return ""

    async def ensure_indexed(self) -> bool:
        """Index the scoped repo once. Idempotent; returns True when graph-ready."""
        if self._indexed:
            return True
        async with self._lock:
            if self._indexed:
                return True
            args = {"repo_path": self._repo} if self._repo else {}
            out = await self._call("index_repository", args)
            # The server is the source of truth; any non-empty response = indexed.
            self._indexed = bool(out)
            if not self._indexed:
                self._brief = None
            return self._indexed

    async def architecture_brief(self, max_chars: int = _BRIEF_MAX_CHARS) -> str:
        """Compact, cached architecture digest for injection into a code task.

        Returns "" when the layer can't produce one (not indexed, server down),
        so callers can treat it as simply "no extra context". Cached after the
        first successful build; call :meth:`refresh` to rebuild.
        """
        if self._brief is not None:
            return self._brief
        if not await self.ensure_indexed():
            return ""
        async with self._lock:
            if self._brief is not None:
                return self._brief
            project = self.project_name()
            raw = await self._call("get_architecture", {"project": project} if project else {})
            if not raw:
                # Some server builds index a single default project and reject the
                # project arg; retry without it before giving up.
                raw = await self._call("get_architecture", {})
            brief = raw.strip()
            if not brief:
                # Transient empty result (graph still warming up, server hiccup).
                # Don't cache it — a later code task should get a real brief
                # instead of being stuck with "" for this instance's lifetime.
                return ""
            if len(brief) > max_chars:
                brief = brief[:max_chars].rstrip() + " …"
            self._brief = brief
            return brief

    async def refresh(self) -> str:
        """Force a re-index and rebuild the brief (e.g. after large code changes)."""
        async with self._lock:
            self._indexed = False
            self._brief = None
        await self.ensure_indexed()
        return await self.architecture_brief()

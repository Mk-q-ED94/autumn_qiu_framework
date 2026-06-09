"""Memory-backed Skills for the agent ReAct loop.

Call ``make_memory_skills(memory, api=None)`` to get a list of Skills that can
be registered with an Agent or via ``Autumn.add_memory_skills()``.

Returned skills (in order):
  [0] recall       -- unified retrieval: exact key → tag filter → semantic search
  [1] remember     -- persist a fact; auto-indexes into vector store when available
  [2] list_recent  -- list the n most recent history entries
  [3] pin_memory   -- raise an entry's importance so it survives eviction

When *api* is supplied (the optional A4 slot), vector-search results are
synthesised by the model rather than returned as raw snippets.

For per-project shared memory, use ``make_project_memory_skills(projects, api)``:
the same skills, but each resolves the context-active project's zone at call
time, so one registration transparently serves every project.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Callable

from ..components.skill import Skill
from ..components.tool import ToolParameter

if TYPE_CHECKING:
    from ..api.base import ModelAPIInterface
    from .base import MemoryArea
    from .project import ProjectMemory


def make_memory_skills(
    memory: "MemoryArea",
    api: "ModelAPIInterface | None" = None,
) -> list[Skill]:
    """Return [recall, remember, list_recent, pin_memory] skills bound to *memory*.

    Parameters
    ----------
    memory:
        The MemoryArea to read from / write to.
    api:
        Optional inference model (A4) used to synthesise vector-search results
        into a concise answer.  When None, raw snippets are returned.
    """
    return _build_memory_skills(lambda: memory, api)


def make_project_memory_skills(
    projects: "ProjectMemory",
    api: "ModelAPIInterface | None" = None,
) -> list[Skill]:
    """Return memory skills bound to the *context-active project's* shared zone.

    Identical to :func:`make_memory_skills`, but each skill resolves
    ``projects.current()`` at call time. Register once and the same skills read
    and write whichever project is active for the current request (see
    :func:`autumn.core.memory.project.project_context`).
    """
    return _build_memory_skills(projects.current, api)


def _build_memory_skills(
    resolve: "Callable[[], MemoryArea]",
    api: "ModelAPIInterface | None",
) -> list[Skill]:
    """Construct the four memory skills, resolving the target area via *resolve*.

    ``resolve`` is called at the start of every skill invocation, so a static
    area (``lambda: memory``) and a dynamic one (``projects.current``) share one
    implementation.
    """

    async def recall(query: str) -> str:
        memory = resolve()
        entries = await memory.recall(query, k=5)

        if not entries:
            return f"[no memory found for '{query}']"

        # Exact KV hit — return raw value
        kv_hits = [e for e in entries if "kv" in e.tags]
        if kv_hits:
            v = kv_hits[0].content
            return (
                json.dumps(v, ensure_ascii=False)
                if isinstance(v, (dict, list))
                else str(v)
            )

        # Vector hits — synthesize with A4 or return formatted snippets
        vector_hits = [e for e in entries if "vector" in e.tags]
        if vector_hits:
            snippets = "\n".join(
                f"[relevance={e.meta.get('score', 0.0):.2f}] {e.text}"
                for e in vector_hits
            )
            if api is not None:
                from ..types import Message, Role
                prompt = (
                    f"Using these memory entries, answer: {query!r}\n\n"
                    f"{snippets}\n\nBe concise."
                )
                msgs = [
                    Message(
                        role=Role.SYSTEM,
                        content=(
                            "You are a memory assistant. Synthesise stored facts "
                            "into a direct, concise answer."
                        ),
                    ),
                    Message(role=Role.USER, content=prompt),
                ]
                return await api.complete(msgs)
            return snippets

        return f"[no memory found for '{query}']"

    async def remember(key: str, value: str) -> str:
        memory = resolve()
        await memory.set(key, value)
        if memory.has_vector:
            await memory.index(key, f"{key}: {value}")
        return f"[remembered '{key}']"

    async def list_recent(n: str = "5") -> str:
        """List the n most recent history entries."""
        memory = resolve()
        try:
            count = max(1, min(int(n), 20))
        except (ValueError, TypeError):
            count = 5
        entries = await memory.recent(count)
        if not entries:
            return "[no history entries]"
        lines = []
        for e in entries:
            ts_str = f"{e.timestamp:.0f}"
            preview = e.text[:120].replace("\n", " ")
            pin_marker = " [pinned]" if e.is_pinned else ""
            tag_str = f" [{', '.join(e.tags)}]" if e.tags else ""
            lines.append(f"[{ts_str}]{pin_marker}{tag_str} {preview}")
        return "\n".join(lines)

    async def pin_memory(entry_id: str) -> str:
        """Pin a history entry so it is never evicted."""
        memory = resolve()
        ok = await memory.pin(entry_id)
        return (
            f"[pinned entry '{entry_id}']"
            if ok
            else f"[entry '{entry_id}' not found in history]"
        )

    return [
        Skill(
            name="recall",
            description=(
                "Retrieve stored information by key or natural-language query. "
                "Tries exact key lookup first; falls back to semantic search "
                "when the vector layer is enabled."
            ),
            handler=recall,
            parameters=[
                ToolParameter(
                    "query",
                    "string",
                    "The memory key or a natural-language description of what to find.",
                ),
            ],
        ),
        Skill(
            name="remember",
            description=(
                "Persist a fact or value under a key for future retrieval via recall."
            ),
            handler=remember,
            parameters=[
                ToolParameter("key", "string", "Identifier for this memory entry."),
                ToolParameter("value", "string", "The information to store."),
            ],
        ),
        Skill(
            name="list_recent",
            description=(
                "List the most recent history entries from memory. "
                "Useful for reviewing what was discussed in the current session."
            ),
            handler=list_recent,
            parameters=[
                ToolParameter(
                    "n",
                    "string",
                    "Number of recent entries to return (1–20, default 5).",
                ),
            ],
        ),
        Skill(
            name="pin_memory",
            description=(
                "Pin a history entry by its ID so it is never removed during "
                "automatic eviction. Use recall or list_recent to find entry IDs."
            ),
            handler=pin_memory,
            parameters=[
                ToolParameter("entry_id", "string", "The id of the entry to pin."),
            ],
        ),
    ]

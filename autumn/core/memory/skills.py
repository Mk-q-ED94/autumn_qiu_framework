"""Memory-backed Skills for the agent ReAct loop.

Call ``make_memory_skills(memory, api=None)`` to get a [recall, remember] pair
that can be registered with an Agent or via ``Autumn.add_memory_skills()``.

recall(query)         -- exact key lookup; vector-search fallback when enabled.
remember(key, value)  -- persist a fact; auto-indexes into vector store when available.

When *api* is supplied (the optional A4 slot), vector-search results are
synthesised by the model rather than returned as raw snippets.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..components.skill import Skill
from ..components.tool import ToolParameter

if TYPE_CHECKING:
    from ..api.base import ModelAPIInterface
    from .base import MemoryArea


def make_memory_skills(
    memory: "MemoryArea",
    api: "ModelAPIInterface | None" = None,
) -> list[Skill]:
    """Return [recall_skill, remember_skill] bound to *memory*.

    Parameters
    ----------
    memory:
        The MemoryArea to read from / write to.
    api:
        Optional inference model (A4) used to synthesise vector-search results
        into a concise answer.  When None, raw snippets are returned.
    """

    async def recall(query: str) -> str:
        # 1. Exact key lookup
        value = await memory.get(query)
        if value is not None:
            return (
                json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list))
                else str(value)
            )

        # 2. Vector-search fallback
        if memory.has_vector:
            results = await memory.search(query, k=5)
            if results:
                snippets = "\n".join(
                    f"[relevance={r.score:.2f}] {r.text}" for r in results
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
        await memory.set(key, value)
        if memory.has_vector:
            await memory.index(key, f"{key}: {value}")
        return f"[remembered '{key}']"

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
    ]

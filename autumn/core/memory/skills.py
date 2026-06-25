"""Memory-backed Skills for the agent ReAct loop.

Call ``make_memory_skills(memory, api=None)`` to get a list of Skills that can
be registered with an Agent or via ``Autumn.add_memory_skills()``.

Returned skills (in order):
  [0] recall          -- unified retrieval: exact key → tag filter → semantic search
  [1] remember        -- persist a fact; auto-indexes into vector store when available
  [2] list_recent     -- list the n most recent history entries
  [3] pin_memory      -- raise an entry's importance so it survives eviction
  [4] annotate_memory -- attach 4D dimensions (mode/intent/cues) to an entry

When *api* is supplied (the optional A4 slot), vector-search results are
synthesised by the model rather than returned as raw snippets.

For per-project shared memory, use ``make_project_memory_skills(projects, api)``:
the same skills, but each resolves the context-active project's zone at call
time, so one registration transparently serves every project.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from ..components.skill import Skill
from ..components.tool import ToolParameter

if TYPE_CHECKING:
    from ..api.base import ModelAPIInterface
    from .access import Mom1Requester
    from .base import MemoryArea
    from .project import ProjectMemory


def make_memory_skills(
    memory: MemoryArea,
    api: ModelAPIInterface | None = None,
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
    projects: ProjectMemory,
    api: ModelAPIInterface | None = None,
) -> list[Skill]:
    """Return memory skills bound to the *context-active project's* shared zone.

    Identical to :func:`make_memory_skills`, but each skill resolves
    ``projects.current()`` at call time. Register once and the same skills read
    and write whichever project is active for the current request (see
    :func:`autumn.core.memory.project.project_context`).
    """
    return _build_memory_skills(projects.current, api)


def _build_memory_skills(
    resolve: Callable[[], MemoryArea],
    api: ModelAPIInterface | None,
) -> list[Skill]:
    """Construct the four memory skills, resolving the target area via *resolve*.

    ``resolve`` is called at the start of every skill invocation, so a static
    area (``lambda: memory``) and a dynamic one (``projects.current``) share one
    implementation.
    """

    async def recall(query: str) -> str:
        memory = resolve()
        entries = await memory.recall(query, k=5)

        if entries:
            # Close the 4D use-feedback loop: recalling an entry IS a use of it,
            # so touch its utility ledger. Entries that keep proving useful gain
            # utility and rank higher in future recall / survive eviction longer.
            # reinforce ignores the synthetic kv:/vector ids, so the whole result
            # set is safe to pass. Best-effort — a write hiccup must not fail recall.
            try:
                await memory.reinforce([e.id for e in entries])
            except Exception:
                pass

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

        # Semantic / lexical hits — synthesize with A4 or return formatted snippets
        semantic_hits = [e for e in entries if "vector" in e.tags or "lexical" in e.tags]
        if semantic_hits:
            snippets = "\n".join(
                f"[relevance={e.meta.get('score', 0.0):.2f}] {e.text}"
                for e in semantic_hits
            )
            if api is not None:
                from ..types import Message, Role
                from .prompts import RECALL_SYNTH_SYSTEM, recall_synth_prompt
                msgs = [
                    Message(role=Role.SYSTEM, content=RECALL_SYNTH_SYSTEM),
                    Message(role=Role.USER, content=recall_synth_prompt(query, snippets)),
                ]
                try:
                    return await api.complete(msgs)
                except Exception:
                    pass  # A4 unavailable — fall back to raw snippets
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

    async def annotate_memory(
        entry_id: str,
        mode: str = "",
        intent: str = "",
        cues: str = "",
    ) -> str:
        """Attach 4D dimensions to an existing history entry.

        ``mode`` declares how the memory should be applied (constrain / remind /
        summarize / context); ``cues`` is a comma-separated trigger list. Find
        ids via list_recent or recall.
        """
        memory = resolve()
        cue_list = [c.strip() for c in cues.split(",") if c.strip()] or None
        ok = await memory.annotate(
            entry_id,
            mode=mode or None,
            intent=intent or None,
            cues=cue_list,
        )
        return (
            f"[annotated '{entry_id}']"
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
        Skill(
            name="annotate_memory",
            description=(
                "Declare how a stored memory should be applied by tagging it with "
                "4D dimensions. Set mode to 'constrain' for a hard rule the "
                "assistant must always follow, 'remind' for something to resurface "
                "proactively, 'summarize' for a consolidation candidate, or "
                "'context' for ordinary background. Optionally give a short intent "
                "and comma-separated trigger cues. Find entry IDs via list_recent "
                "or recall."
            ),
            handler=annotate_memory,
            parameters=[
                ToolParameter("entry_id", "string", "The id of the entry to annotate."),
                ToolParameter(
                    "mode", "string",
                    "How to apply it: constrain | remind | summarize | context.",
                    required=False,
                ),
                ToolParameter(
                    "intent", "string",
                    "Short phrase naming why this memory matters.",
                    required=False,
                ),
                ToolParameter(
                    "cues", "string",
                    "Comma-separated keywords that should trigger this memory.",
                    required=False,
                ),
            ],
        ),
    ]


def make_mom1_access_skill(requester: Mom1Requester) -> Skill:
    """Build the ``request_mom1_access`` skill bound to a Mom2/Mom3 zone.

    This is the *agent-facing* trigger for the governed upward channel
    (:mod:`autumn.core.memory.access`). A task/mission agent that needs a fact
    living only in Mom1 calls this skill; A1 adjudicates, A4 mediates a
    restricted answer, and the result — granted or denied — comes back as text
    in the ReAct trace. The agent never reads Mom1 directly.

    The skill is only useful once a broker has been attached to *requester*
    (``Autumn`` does this at construction); without one the handler returns a
    clear unavailable message rather than raising into the agent loop.
    """

    async def request_mom1_access(
        query: str,
        reason: str,
        scope: str = "",
        max_entries: str = "5",
    ) -> str:
        scope_list = [s.strip() for s in scope.split(",") if s.strip()] or None
        try:
            n = max(1, min(int(max_entries), 20))
        except (ValueError, TypeError):
            n = 5
        try:
            grant = await requester.request_mom1(
                query=query, reason=reason, scope=scope_list, max_entries=n,
            )
        except RuntimeError as exc:
            return f"[mom1 access unavailable: {exc}]"
        if not grant.approved:
            return f"[mom1 access denied] {grant.decision.reason}".rstrip()
        header = (
            f"[mom1 access granted · {len(grant.entries)} entr"
            f"{'y' if len(grant.entries) == 1 else 'ies'} · via {grant.mediated_by}]"
        )
        body = grant.content or "[no content returned]"
        return f"{header}\n{body}"

    return Skill(
        name="request_mom1_access",
        description=(
            "Request read access to Mom1 — the Total workspace's private memory — "
            "for a fact you cannot find in your own zone. State what you need "
            "(query) and why (reason). A1 decides whether to grant it and A4 "
            "returns a restricted, mediated answer; access is never guaranteed. "
            "Use only when the task genuinely depends on Mom1-held information."
        ),
        handler=request_mom1_access,
        parameters=[
            ToolParameter(
                "query", "string",
                "Natural-language description of the Mom1 information you need.",
            ),
            ToolParameter(
                "reason", "string",
                "Why this task/mission needs it — A1 weighs this when adjudicating.",
            ),
            ToolParameter(
                "scope", "string",
                "Optional comma-separated Mom1 tags or entry ids to restrict the "
                "request to. Leave empty to let A1 pick relevant entries.",
                required=False,
            ),
            ToolParameter(
                "max_entries", "string",
                "Max Mom1 entries the answer may draw on (1–20, default 5).",
                required=False,
            ),
        ],
    )

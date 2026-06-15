"""Externalised memory prompt slots (RFC 4D-memory P1-C).

Centralises the prompts the memory engine feeds to A4 so a product layer can
override them (language, tone, domain) without forking algorithm code. The
defaults reproduce the previously-hardcoded strings **verbatim**, so importing
and using these changes no behaviour.

Override points:
- :data:`CONSOLIDATE_SYSTEM` — system prompt for :meth:`MemoryArea.consolidate`
  (also accepts a per-call ``system_prompt=`` override).
- :func:`consolidate_instruction` — the user message for consolidation.
- :data:`RECALL_SYNTH_SYSTEM` / :func:`recall_synth_prompt` — the recall-synthesis
  prompts used by the ``recall`` skill when an A4 slot is attached.

These are plain module constants/functions: a product build can reassign them at
import time, or pass per-call overrides where the API exposes them.
"""
from __future__ import annotations

# ── consolidation (MemoryArea.consolidate) ───────────────────────────────────

CONSOLIDATE_SYSTEM = (
    "You compress conversation memory. Summarise the entries "
    "into a compact, factual digest that preserves names, "
    "decisions, preferences and unresolved threads. Be terse."
)


def consolidate_instruction(count: int, joined: str) -> str:
    """The user message asking A4 to summarise *count* entries (text *joined*)."""
    return f"Summarise these {count} memory entries:\n\n{joined}"


# ── recall synthesis (make_memory_skills → recall) ───────────────────────────

RECALL_SYNTH_SYSTEM = (
    "You are a memory assistant. Synthesise stored facts "
    "into a direct, concise answer."
)


def recall_synth_prompt(query: str, snippets: str) -> str:
    """The user message asking A4 to answer *query* from retrieved *snippets*."""
    return f"Using these memory entries, answer: {query!r}\n\n{snippets}\n\nBe concise."

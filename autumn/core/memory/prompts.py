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


# ── atomic-fact extraction (MemoryArea.extract_facts) ─────────────────────────

ATOMIC_FACT_SYSTEM = (
    "You extract atomic facts from conversation memory. An atomic fact is a "
    "short, self-contained, durable statement — a name, decision, preference, "
    "constraint or commitment — that stands alone without surrounding context. "
    "Ignore small talk and transient chatter. Respond with ONLY a JSON array of "
    'strings, e.g. ["fact one", "fact two"]. Return [] when nothing is worth keeping.'
)


def atomic_fact_instruction(joined: str) -> str:
    """The user message asking A4 to extract atomic facts from *joined* text."""
    return f"Extract atomic facts from these memory entries:\n\n{joined}"


# ── self-evolution: recurring memories → reusable skill (MemoryArea.evolve) ────

EVOLVE_SYSTEM = (
    "You distill recurring, proven-useful memories into ONE reusable procedural "
    "rule — a 'skill'. Make it general, imperative and actionable, not a recap of "
    "the specific instances. Respond with ONLY the rule text, one or two sentences."
)


def evolve_instruction(intent: str, joined: str) -> str:
    """The user message asking A4 to distill a cluster (shared *intent*) into a rule."""
    return (
        f"These memories share the purpose {intent!r} and have repeatedly proven "
        f"useful. Distill them into one reusable rule:\n\n{joined}"
    )


# ── user profile synthesis (MemoryArea.synthesize_profile) ────────────────────

PROFILE_SYSTEM = (
    "You maintain a concise user profile from conversation memory — stable "
    "preferences, recurring context, working style and standing constraints. "
    "Merge new evidence into the existing profile; keep it short, factual and "
    "current (drop anything contradicted). Respond with ONLY the updated profile."
)


def profile_instruction(current: str, joined: str) -> str:
    """The user message asking A4 to update *current* profile from *joined* memory."""
    base = current.strip() or "(no profile yet)"
    return (
        f"Current profile:\n{base}\n\nRecent memory to fold in:\n\n{joined}\n\n"
        "Return the updated profile."
    )


"""Four-dimensional memory primitives (pure data + pure functions).

P0 of the 4D memory design (see ``docs/rfc-4d-memory.md``). A memory has four
orthogonal dimensions:

* **aim**  — *why* it exists. The relevance gate (:class:`Aim`).
* **content** — *what* it is. The payload (lives on the entry, not here).
* **use**  — *how* to apply it, and *how it has been used* (:class:`Use`).
* **time** — *when* / under what conditions to trigger the other three
  (:class:`Trigger`).

This module is deliberately self-contained: small dataclasses with pure scoring
functions, **no I/O**, and **no dependency** on ``MemoryArea`` / ``recall`` /
``MemoryEntry``. The :class:`Trigger` and activation helpers take plain scalars
(``created_at``, ``last_used``) rather than an entry object, so nothing here is
coupled to storage. Importing this module changes no runtime behavior — it is
the foundation later phases build on (entry extension, recall/evict scoring, the
WP4 activation engine).

Activation combines three factors::

    activation = w_time × align × (1 + utility)

``align`` is a **gate** (0 vetoes activation even when time wants to fire);
``utility`` is a **boost** (a fresh, never-used memory still activates on
``w_time × align`` alone). Defaults are chosen so a memory carrying no aim/use/
time configuration scores exactly as today's importance-and-decay model would.
"""
from __future__ import annotations

import math
import time as _time
from dataclasses import dataclass, field
from enum import Enum


# ── pure helpers ──────────────────────────────────────────────────────────────

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _jaccard(a: list[str], b: list[str]) -> float:
    """Case-insensitive Jaccard overlap of two token lists. Empty side → 0.0."""
    sa = {s.lower() for s in a if s}
    sb = {s.lower() for s in b if s}
    if not sa or not sb:
        return 0.0
    union = len(sa | sb)
    return len(sa & sb) / union if union else 0.0


# ── activation context ────────────────────────────────────────────────────────

@dataclass
class ActivationContext:
    """The situation a memory's dimensions are evaluated against.

    pull (query search) and push (turn/event trigger) share this one shape, so a
    single activation function serves both retrieval styles. A bare context
    (``ActivationContext()``) defaults ``now`` to wall-clock time.
    """

    now: float = field(default_factory=lambda: _time.time())
    query: str | None = None
    goal: str | None = None
    cues: list[str] = field(default_factory=list)
    workspace: str | None = None


# ── aim 维: why the memory exists ─────────────────────────────────────────────

@dataclass
class Aim:
    """Why a memory exists — the relevance gate.

    :meth:`align` returns ``0.0..1.0`` against an :class:`ActivationContext`;
    **0 vetoes activation** even when the time dimension wants to fire. An empty
    Aim aligns with everything (1.0), so memories carrying no purpose behave
    exactly as today.
    """

    intent: str = ""
    goal_ref: str | None = None
    scope: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        """True when no purpose is declared (aligns with any context)."""
        return not self.intent and self.goal_ref is None and not self.scope

    def align(self, ctx: ActivationContext) -> float:
        """Purpose alignment in ``[0, 1]``; 0 means "do not activate here".

        - empty aim → ``1.0`` (no constraint, backward-compatible)
        - ``goal_ref`` equals ``ctx.goal`` → ``1.0`` (exact purpose match)
        - otherwise the Jaccard overlap of ``scope`` against ``ctx.cues``
        - a stated purpose that the context matches by neither → ``0.0`` (veto)
        """
        if self.is_empty():
            return 1.0
        if self.goal_ref is not None and ctx.goal is not None and self.goal_ref == ctx.goal:
            return 1.0
        if self.scope and ctx.cues:
            return _jaccard(self.scope, ctx.cues)
        return 0.0

    def to_dict(self) -> dict:
        return {"intent": self.intent, "goal_ref": self.goal_ref, "scope": list(self.scope)}

    @classmethod
    def from_dict(cls, d: dict) -> "Aim":
        return cls(
            intent=d.get("intent", ""),
            goal_ref=d.get("goal_ref"),
            scope=list(d.get("scope") or []),
        )


# ── use 维: how to apply it, and how it has been used ─────────────────────────

class UseMode(str, Enum):
    """How an activated memory is applied to the current turn."""

    CONTEXT = "context"      # inject into the prompt context (today's recall behavior)
    REMIND = "remind"        # surface as an explicit reminder
    CONSTRAIN = "constrain"  # inject as a hard rule / guardrail
    SUMMARIZE = "summarize"  # mark as a priority candidate for consolidation


@dataclass
class UseStats:
    """The usage ledger — answers "how has this been used?".

    ``reward`` accumulates feedback across uses (positive = it proved useful,
    negative = it did not); its influence on :meth:`Use.utility` is bounded.
    """

    count: int = 0
    last_used: float | None = None
    reward: float = 0.0

    def touch(self, now: float, reward: float = 0.0) -> None:
        """Record one use: bump count, stamp last_used, accumulate reward."""
        self.count += 1
        self.last_used = now
        self.reward += reward

    def to_dict(self) -> dict:
        return {"count": self.count, "last_used": self.last_used, "reward": self.reward}

    @classmethod
    def from_dict(cls, d: dict) -> "UseStats":
        return cls(
            count=int(d.get("count", 0)),
            last_used=d.get("last_used"),
            reward=float(d.get("reward", 0.0)),
        )


@dataclass
class Use:
    """How a memory should be applied (protocol) **and** how it has been used.

    ``mode`` / ``template`` / ``weight`` drive what happens *after* activation;
    ``stats`` feeds :meth:`utility`, which influences activation *before* it.
    """

    mode: UseMode = UseMode.CONTEXT
    weight: float = 1.0
    template: str | None = None
    stats: UseStats = field(default_factory=UseStats)

    def touch(self, now: float, reward: float = 0.0) -> None:
        """Delegate to :meth:`UseStats.touch` — call when this memory is used."""
        self.stats.touch(now, reward)

    def utility(self) -> float:
        """History-based usefulness, ``>= 0``. Never-used memories return 0.

        ``log1p(count)`` rewards repeated use with diminishing returns; the
        reward multiplier is bounded to ``[0.5, 2.0]`` so feedback nudges rather
        than dominates. Returns 0 for an unused memory so it contributes no
        boost (but is not vetoed — see module docstring).
        """
        if self.stats.count <= 0:
            return 0.0
        reward_factor = 1.0 + _clamp(self.stats.reward, -0.5, 1.0)
        return math.log1p(self.stats.count) * reward_factor

    def to_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "weight": self.weight,
            "template": self.template,
            "stats": self.stats.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Use":
        raw_mode = d.get("mode", UseMode.CONTEXT.value)
        try:
            mode = UseMode(raw_mode)
        except ValueError:
            mode = UseMode.CONTEXT  # forward-compatible: unknown mode → default
        return cls(
            mode=mode,
            weight=float(d.get("weight", 1.0)),
            template=d.get("template"),
            stats=UseStats.from_dict(d.get("stats") or {}),
        )


# ── time 维: when / under what conditions to trigger ──────────────────────────

@dataclass
class Trigger:
    """Conditions and weight along the time axis — the scheduler.

    Subsumes today's decay (``half_life``) and TTL (``expires_at``) and adds
    scheduling (``not_before``), throttling (``every``) and contextual cues.
    :meth:`weight` takes plain scalars (``created_at``, ``last_used``) so this
    type stays independent of any entry/storage class.
    """

    half_life: float | None = None     # importance halves every this-many seconds of age
    not_before: float | None = None    # earliest activation time (scheduling)
    expires_at: float | None = None    # TTL; past this the trigger is dead
    every: float | None = None         # min seconds between activations (throttle)
    cues: list[str] = field(default_factory=list)  # contextual cues that boost the weight
    base_weight: float = 1.0

    def is_expired(self, now: float) -> bool:
        """True when a TTL is set and has elapsed."""
        return self.expires_at is not None and now >= self.expires_at

    def weight(
        self,
        created_at: float,
        now: float,
        ctx: ActivationContext,
        last_used: float | None = None,
    ) -> float:
        """Trigger weight ``>= 0``; **0 means "do not fire now"**.

        Gates (any → 0): not yet ``not_before``; past ``expires_at``; within an
        ``every`` cooldown since ``last_used``. Otherwise the weight is
        ``base_weight`` decayed by age (when ``half_life`` is set) and boosted by
        the overlap of ``cues`` against ``ctx.cues``.
        """
        if self.not_before is not None and now < self.not_before:
            return 0.0
        if self.is_expired(now):
            return 0.0
        if self.every is not None and last_used is not None and (now - last_used) < self.every:
            return 0.0  # cooling down since the last activation

        w = self.base_weight
        if self.half_life and self.half_life > 0:
            age = max(0.0, now - created_at)
            w *= 0.5 ** (age / self.half_life)
        if self.cues and ctx.cues:
            w *= 1.0 + _jaccard(self.cues, ctx.cues)
        return max(0.0, w)

    def to_dict(self) -> dict:
        return {
            "half_life": self.half_life,
            "not_before": self.not_before,
            "expires_at": self.expires_at,
            "every": self.every,
            "cues": list(self.cues),
            "base_weight": self.base_weight,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Trigger":
        return cls(
            half_life=d.get("half_life"),
            not_before=d.get("not_before"),
            expires_at=d.get("expires_at"),
            every=d.get("every"),
            cues=list(d.get("cues") or []),
            base_weight=float(d.get("base_weight", 1.0)),
        )


# ── activation: combine the three scored factors ──────────────────────────────

def activation_score(w_time: float, align: float, utility: float) -> float:
    """Combine the three factors into one activation score.

    ``activation = w_time × align × (1 + utility)``. ``align`` is a gate (0
    vetoes); ``utility`` is a boost, so a fresh entry (utility 0) still scores
    ``w_time × align``. Negative inputs are floored at 0.
    """
    w_time = max(0.0, w_time)
    align = max(0.0, align)
    utility = max(0.0, utility)
    return w_time * align * (1.0 + utility)

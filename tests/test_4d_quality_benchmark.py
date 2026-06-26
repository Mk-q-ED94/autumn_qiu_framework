"""4D memory quality benchmark — effect-level proof that annotation improves recall.

These tests demonstrate, without any model call, that 4D annotation actually
changes what the activation engine surfaces:

1. Cue-based discrimination: an annotated entry with matching cues scores higher
   than an unannotated entry for the same query.
2. Push-mode exclusion: a CONSTRAIN/REMIND entry fires via push; a CONTEXT entry
   does not, even if textually similar.
3. Aim-veto: an entry scoped to a different aim tag is excluded when the query aim
   differs — 4D ranking prunes irrelevant-scope entries that pure text search would
   surface.
4. Temporal activation: a Trigger.every-scheduled entry fires only once its cooldown
   has lapsed, not on every turn.

All assertions are on in-process activation scores — no models, no I/O.
"""
import time

import pytest

from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea
from autumn.core.memory.dimensions import (
    Aim,
    ActivationContext,
    Trigger,
    Use,
    UseMode,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _area() -> MemoryArea:
    return MemoryArea("bench", DictBackend(), fourd_enabled=True)


async def _write(area: MemoryArea, text: str, **annotate_kw) -> str:
    """Append a plain history entry and optionally annotate it."""
    entry = await area.append_history(text)
    if annotate_kw:
        await area.annotate(entry.id, **annotate_kw)
    return entry.id


# ── 1. cue-based discrimination ──────────────────────────────────────────────

async def test_annotated_entry_beats_unannotated_in_activation():
    """An entry with matching cues activates before one without.

    Both entries are textually similar; the cue on the annotated one is the
    sole discriminator. This proves annotation adds recall quality beyond
    text matching.
    """
    area = _area()
    ctx = ActivationContext(now=time.time(), query="deploy to production", cues=["deploy", "prod"])

    eid_plain = await _write(area, "we ship to the production server")
    eid_cued = await _write(area, "we ship to the production server",
                            mode="remind", cues=["deploy", "prod"])

    entries = await area.get_history()
    by_id = {e.id: e for e in entries}

    score_plain = by_id[eid_plain].activation(ctx)
    score_cued = by_id[eid_cued].activation(ctx)

    assert score_cued > score_plain, (
        f"Annotated entry (score={score_cued}) should beat unannotated "
        f"(score={score_plain}) when cues match the context"
    )


async def test_non_matching_cue_does_not_inflate():
    """An entry with cues that don't match the query should not score above baseline."""
    area = _area()
    ctx = ActivationContext(now=time.time(), query="fix the login bug", cues=["login", "bug"])

    eid_irrelevant = await _write(area, "database migrations on Friday",
                                  mode="remind", cues=["db", "migration"])
    eid_matching = await _write(area, "login endpoint has an edge case",
                                mode="remind", cues=["login", "bug"])

    entries = await area.get_history()
    by_id = {e.id: e for e in entries}

    assert by_id[eid_matching].activation(ctx) > by_id[eid_irrelevant].activation(ctx)


# ── 2. push-mode exclusion ────────────────────────────────────────────────────

async def test_constrain_entry_fires_in_push_not_plain_context_entry():
    """Only CONSTRAIN/REMIND entries are push candidates; CONTEXT entries aren't.

    Even with identical text, a CONTEXT entry should return score=0 from the
    push engine's activation filter.
    """
    from autumn.core.workspace.wp4 import _PUSH_MODES

    area = _area()
    ctx = ActivationContext(now=time.time(), query="deployment", cues=["deploy"])

    eid_context = await _write(area, "never deploy on Fridays", mode="context")
    eid_constrain = await _write(area, "never deploy on Fridays",
                                 mode="constrain", cues=["deploy"])

    entries = await area.get_history()
    by_id = {e.id: e for e in entries}

    context_entry = by_id[eid_context]
    constrain_entry = by_id[eid_constrain]

    # Push engine filter: only PUSH_MODES get a score.
    assert context_entry.use.mode not in _PUSH_MODES
    assert constrain_entry.use.mode in _PUSH_MODES

    # CONTEXT activation score is the base score (no push boost), CONSTRAIN gets it.
    assert constrain_entry.activation(ctx) > context_entry.activation(ctx)


async def test_push_engine_ignores_context_entries_end_to_end():
    """activate_push returns only CONSTRAIN/REMIND entries, never CONTEXT."""
    from autumn.core.workspace.wp4 import WP4Mem

    area = _area()
    wp4 = WP4Mem(None, area, zones={"bench": area})

    await _write(area, "background fact", mode="context")
    await _write(area, "must follow this rule", mode="constrain", cues=["rule"])

    ctx = ActivationContext(now=time.time(), query="rule check", cues=["rule"])
    fired = await wp4.activate_push(area="bench", ctx=ctx)

    assert len(fired) == 1
    assert fired[0].use.mode == UseMode.CONSTRAIN


# ── 3. aim-veto (scope-based pruning) ────────────────────────────────────────

async def test_aim_scope_prunes_out_of_scope_entry():
    """An entry scoped to 'infra' is vetoed when context cues don't match its scope.

    This is the 4D aim-veto: ``aim.scope`` is tested via Jaccard against ``ctx.cues``.
    An entry whose scope has no overlap with the context cues scores 0 — it is pruned
    even if its text is highly relevant. This proves the aim dimension adds a
    scope-based filter on top of pure text similarity.

    Scoring formula: activation = w_time × aim_align × (1 + utility)
    aim_align = jaccard(entry.scope, ctx.cues)  when scope is set and not empty
    """
    area = _area()

    # Infra entry: scope=["infra"] — only relevant when ctx has "infra" cue.
    eid_infra = await _write(area, "use Terraform for all infra changes",
                             mode="remind", cues=["infra"], scope=["infra"])
    # Product entry: scope=["feature"] — relevant when ctx has "feature" cue.
    eid_product = await _write(area, "user features go through design review",
                               mode="remind", cues=["feature"], scope=["feature"])
    # Unannotated entry: no aim scope → always aligns (aim_align = 1.0).
    eid_generic = await _write(area, "general background note")

    entries = await area.get_history()
    by_id = {e.id: e for e in entries}

    # Context that carries "feature" cues — matches product scope, not infra.
    ctx_feature = ActivationContext(
        now=time.time(), query="shipping a new feature", cues=["feature"],
    )
    # Context that carries "infra" cues — matches infra scope, not product.
    ctx_infra = ActivationContext(
        now=time.time(), query="provisioning new servers", cues=["infra"],
    )

    score_infra_in_feature_ctx = by_id[eid_infra].activation(ctx_feature)
    score_product_in_feature_ctx = by_id[eid_product].activation(ctx_feature)
    score_infra_in_infra_ctx = by_id[eid_infra].activation(ctx_infra)
    score_generic_in_feature_ctx = by_id[eid_generic].activation(ctx_feature)

    # Infra entry is vetoed (score=0) when context cues are about "feature".
    assert score_infra_in_feature_ctx == 0.0, (
        "Infra-scoped entry should be vetoed in a 'feature' context (aim-veto)"
    )
    # Product entry scores > 0 in a feature context (scope matches cue).
    assert score_product_in_feature_ctx > 0.0, (
        "Product-scoped entry should score > 0 when context carries 'feature' cue"
    )
    # Infra entry scores > 0 in its own context.
    assert score_infra_in_infra_ctx > 0.0, (
        "Infra-scoped entry should score > 0 in an infra context"
    )
    # Unannotated entry is never vetoed (empty aim → align=1.0).
    assert score_generic_in_feature_ctx > 0.0, (
        "Unannotated entry should never be aim-vetoed"
    )


# ── 4. trigger cooldown (temporal activation) ─────────────────────────────────

async def test_trigger_every_respects_cooldown():
    """A Trigger.every entry fires after its cooldown but is suppressed during it.

    This is the temporal dimension of 4D: time-gated memories don't inject on
    every turn, only when the ``every``-interval has lapsed since last use
    (``use.stats.last_used``). Cooldown is checked by ``Trigger.weight()``:
    if ``(now - last_used) < every``, weight returns 0 → activation = 0.
    """
    from autumn.core.memory.dimensions import Trigger

    area = _area()
    now = time.time()

    # Write a REMIND entry and annotate it with cues.
    entry = await area.append_history("check the deploy queue every hour")
    await area.annotate(entry.id, mode="remind", cues=["deploy"])

    # Retrieve the live entry and attach a Trigger.every cooldown.
    entry = (await area.get_history())[-1]
    entry.trigger.every = 60  # 60-second cooldown

    # Simulate: just fired — set use.stats.last_used to "now".
    entry.use.stats.last_used = now

    ctx = ActivationContext(now=now, query="deploy check", cues=["deploy"])
    score_hot = entry.activation(ctx)
    assert score_hot == 0.0, (
        f"Entry within cooldown should score 0, got {score_hot}"
    )

    # Simulate: cooldown lapsed (90 s since last use).
    entry.use.stats.last_used = now - 90
    score_cool = entry.activation(ctx)
    assert score_cool > 0.0, (
        f"Entry after cooldown should score > 0, got {score_cool}"
    )


# ── 5. recall quality: annotation improves ranking in actual recall ───────────

async def test_annotated_entry_ranks_first_in_4d_sorted_history():
    """4D activation sorting surfaces annotated entries before unannotated ones.

    The 4D-enabled recall path (fourd_enabled=True on the area) ranks candidate
    entries by ``entry.activation(ctx)`` — this is the ``recall``'s tag-based
    path with cues. We test the ranking effect directly by:
    1. Sorting all history entries by their activation score against the query.
    2. Verifying the annotated (cue-matched) entry ranks first.

    Without annotation, both entries score the same base importance (same text,
    same timestamp); annotation with matching cues is the sole discriminator.
    """
    area = _area()
    now = time.time()

    eid_dull = await _write(area, "we deploy to production regularly")
    eid_sharp = await _write(area, "we deploy to production regularly",
                             mode="remind", cues=["deploy", "production"])

    ctx = ActivationContext(now=now, query="upcoming production deployment",
                            cues=["deploy", "production"])
    entries = await area.get_history()
    by_id = {e.id: e for e in entries}

    score_dull = by_id[eid_dull].activation(ctx)
    score_sharp = by_id[eid_sharp].activation(ctx)

    assert score_sharp > score_dull, (
        f"Annotated entry (score={score_sharp:.3f}) should rank above unannotated "
        f"(score={score_dull:.3f}) when cues match"
    )

    # Confirm the sort order: annotated entry comes first in 4D-ranked list.
    ranked = sorted(entries, key=lambda e: (-e.activation(ctx), -e.timestamp))
    assert ranked[0].id == eid_sharp, (
        "4D-ranked sort should place the annotated entry first"
    )

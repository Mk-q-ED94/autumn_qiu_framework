"""Mediated, adjudicated access from Mom2/Mom3 up to Mom1.

By default the workspace memory hierarchy is asymmetric: WP1's Mom1 can read
Mom2 and Mom3, but the task/mission zones cannot read Mom1 (see ``mom1.py``).
That isolation is deliberate — yet a task or mission occasionally needs a fact
that only lives in the total workspace's memory.

This module adds a *governed* upward channel without dissolving the isolation:

    1. Mom2/Mom3 file an :class:`AccessRequest` (what they want, and why).
    2. **A1** — the authority that governs Mom1 (WP1) — adjudicates: approve or
       deny, optionally narrowing the scope and demanding redaction.
    3. On approval, **A4** — the memory curator — performs the read on the
       requester's behalf and returns a *restricted* synthesis: scoped, capped,
       summarised, and redacted on request. The requester never touches Mom1.
    4. Every decision is appended to an audit log.

So the three guarantees of the original design survive: Mom2/Mom3 still cannot
read Mom1 themselves; access is need-to-know (A1 gates it); and what crosses the
boundary is a mediated answer (A4 filters it), never a raw memory dump.

    grant = await mom2.request_mom1(
        query="production database host",
        reason="the task must connect to the same DB the user configured earlier",
    )
    if grant.approved:
        use(grant.content)        # an A4-synthesised, restricted answer
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .base import MemoryArea, MemoryEntry

if TYPE_CHECKING:
    from ..api.base import ModelAPIInterface

# Workspaces permitted to file a request. Mom1 itself never requests upward.
_ALLOWED_REQUESTERS = ("mom2", "mom3")
_PREVIEW_CHARS = 160


def _extract_json(text: str) -> str:
    """Strip markdown fences so :func:`json.loads` can parse a model reply."""
    text = text.strip()
    if "```" in text:
        for part in text.split("```")[1::2]:  # odd segments live inside fences
            code = part.strip()
            if code.lower().startswith("json"):
                code = code[4:].strip()
            if code.startswith(("{", "[")):
                return code
    return text


# ── request / decision / grant value objects ─────────────────────────────────

@dataclass
class AccessRequest:
    """A lower-privilege zone's bid to read Mom1.

    ``scope`` optionally restricts the request to specific Mom1 entry tags or
    ids; an empty list means "anything relevant to the query". ``max_entries``
    caps how many Mom1 entries may back the answer.
    """

    requester: str
    query: str
    reason: str
    scope: list[str] = field(default_factory=list)
    max_entries: int = 5


@dataclass
class AccessDecision:
    """A1's ruling on an :class:`AccessRequest`.

    ``allowed_scope`` may narrow (never widen) the requested scope to a subset
    of candidate tags/ids; empty means "every candidate entry is allowed".
    ``redact`` instructs the mediator to strip sensitive specifics.
    """

    approved: bool
    reason: str = ""
    allowed_scope: list[str] = field(default_factory=list)
    redact: bool = False


@dataclass
class AccessGrant:
    """The outcome handed back to the requester.

    ``content`` is the A4-mediated restricted answer when approved, else ``None``.
    ``entries`` are the (already scoped + capped) Mom1 entries that backed it —
    exposed for auditing, not as a raw channel. ``mediated_by`` is ``"a4"`` when
    a model synthesised the answer or ``"fallback"`` when no A4 was available.
    """

    request: AccessRequest
    decision: AccessDecision
    content: str | None = None
    entries: list[MemoryEntry] = field(default_factory=list)
    mediated_by: str | None = None

    @property
    def approved(self) -> bool:
        return self.decision.approved


# ── broker ────────────────────────────────────────────────────────────────────

class Mom1AccessBroker:
    """Adjudicates and mediates Mom2/Mom3 requests to read Mom1.

    Parameters
    ----------
    mom1:
        The total-workspace memory area being protected.
    adjudicator:
        The A1 model interface — the authority over Mom1. Decides each request.
    mediator:
        The A4 model interface, or ``None``. When present it synthesises the
        restricted answer; when absent the broker falls back to capped,
        truncated previews so the channel still works without A4.
    audit:
        Optional :class:`MemoryArea` for an immutable trail of every decision.
    default_max_entries:
        Cap applied when a request does not specify ``max_entries``.
    enabled:
        When ``False`` every request is denied without consulting A1 — a kill
        switch for the whole channel.
    """

    def __init__(
        self,
        mom1: MemoryArea,
        adjudicator: "ModelAPIInterface | None",
        mediator: "ModelAPIInterface | None" = None,
        audit: MemoryArea | None = None,
        default_max_entries: int = 5,
        enabled: bool = True,
    ):
        self._mom1 = mom1
        self._a1 = adjudicator
        self._a4 = mediator
        self._audit = audit
        self._default_max = max(1, default_max_entries)
        self.enabled = enabled

    async def request(
        self,
        requester: str,
        query: str,
        reason: str,
        scope: list[str] | None = None,
        max_entries: int | None = None,
    ) -> AccessGrant:
        """Run the full apply → adjudicate → mediate protocol. Never raises.

        Returns an :class:`AccessGrant`; check ``grant.approved`` and read
        ``grant.content`` for the restricted answer.
        """
        if requester not in _ALLOWED_REQUESTERS:
            raise ValueError(
                f"Only {_ALLOWED_REQUESTERS} may request Mom1 access, not {requester!r}."
            )

        req = AccessRequest(
            requester=requester,
            query=query,
            reason=reason,
            scope=list(scope or []),
            max_entries=max(1, max_entries or self._default_max),
        )

        if not self.enabled:
            decision = AccessDecision(False, reason="Mom1 access channel is disabled.")
            grant = AccessGrant(req, decision)
            await self._record(grant)
            return grant

        # Gather candidate Mom1 entries the request could plausibly draw on,
        # filtered to the requester's own ``scope`` before A1 ever sees them.
        candidates = self._in_scope(await self._gather(req.query, req.max_entries * 2), req.scope)

        decision = await self._adjudicate(req, candidates)
        if not decision.approved:
            grant = AccessGrant(req, decision)
            await self._record(grant)
            return grant

        # Apply A1's (possibly narrowed) scope, then cap.
        allowed = self._in_scope(candidates, decision.allowed_scope)[: req.max_entries]
        content, mediated_by = await self._mediate(req, decision, allowed)
        grant = AccessGrant(
            req, decision, content=content, entries=allowed, mediated_by=mediated_by
        )
        await self._record(grant)
        return grant

    # ── candidate gathering ────────────────────────────────────────────────────

    async def _gather(self, query: str, k: int) -> list[MemoryEntry]:
        """Pull plausibly-relevant Mom1 entries: semantic/KV recall + recency."""
        found: dict[str, MemoryEntry] = {}
        try:
            for e in await self._mom1.recall(query, k=k):
                found[e.id] = e
        except Exception:
            pass
        try:
            for e in await self._mom1.recent(k):
                found.setdefault(e.id, e)
        except Exception:
            pass
        return list(found.values())

    @staticmethod
    def _in_scope(entries: list[MemoryEntry], scope: list[str]) -> list[MemoryEntry]:
        """Keep entries whose id or any tag is named in ``scope``.

        An empty scope is a wildcard (keep everything). Scope tokens match an
        entry's id or its tags exactly — never a substring of its content, so a
        narrow grant cannot be widened by coincidental text matches.
        """
        if not scope:
            return entries
        wanted = set(scope)
        return [e for e in entries if e.id in wanted or wanted.intersection(e.tags)]

    # ── adjudication (A1) ──────────────────────────────────────────────────────

    async def _adjudicate(
        self, req: AccessRequest, candidates: list[MemoryEntry]
    ) -> AccessDecision:
        """Ask A1 to rule on the request. Fails closed (deny) on any error."""
        if self._a1 is None:
            return AccessDecision(False, reason="No adjudicating model (A1) configured.")
        if not candidates:
            return AccessDecision(False, reason="No matching Mom1 entries to grant.")

        listing = "\n".join(
            f"[id={e.id} tags={','.join(e.tags) or '-'}] "
            f"{e.text[:_PREVIEW_CHARS].replace(chr(10), ' ')}"
            for e in candidates
        )
        from ..types import Message, Role

        messages = [
            Message(role=Role.SYSTEM, content=_ADJUDICATION_SYSTEM),
            Message(
                role=Role.USER,
                content=(
                    f"Requester: {req.requester}\n"
                    f"Reason: {req.reason}\n"
                    f"Query: {req.query}\n\n"
                    f"Candidate Mom1 entries:\n{listing}"
                ),
            ),
        ]
        try:
            raw = await self._a1.complete(messages, max_tokens=200)
            data = json.loads(_extract_json(raw))
            return AccessDecision(
                approved=bool(data.get("approved", False)),
                reason=str(data.get("reason", "")),
                allowed_scope=[str(s) for s in (data.get("allowed_scope") or [])],
                redact=bool(data.get("redact", False)),
            )
        except (json.JSONDecodeError, ValueError, KeyError, AttributeError, TypeError):
            # Unparseable verdict → deny. An access gate must fail closed.
            return AccessDecision(False, reason="Adjudicator returned an unreadable verdict.")

    # ── mediation (A4) ─────────────────────────────────────────────────────────

    async def _mediate(
        self, req: AccessRequest, decision: AccessDecision, entries: list[MemoryEntry]
    ) -> tuple[str, str]:
        """Turn approved entries into a restricted answer. Returns (content, mediated_by)."""
        if not entries:
            return "[approved, but no Mom1 entries fell within the granted scope]", "fallback"

        if self._a4 is None:
            return self._fallback_view(entries, decision.redact), "fallback"

        body = "\n".join(f"- {e.text}" for e in entries)
        redaction = (
            " Redact sensitive specifics — credentials, secrets, personal "
            "identifiers, exact internal figures — and generalise them instead."
            if decision.redact
            else ""
        )
        from ..types import Message, Role

        messages = [
            Message(role=Role.SYSTEM, content=_MEDIATION_SYSTEM.format(redaction=redaction)),
            Message(
                role=Role.USER,
                content=(
                    f"Requester: {req.requester}\n"
                    f"Their reason: {req.reason}\n"
                    f"Their query: {req.query}\n\n"
                    f"Authorised Mom1 entries:\n{body}\n\n"
                    "Provide the restricted answer:"
                ),
            ),
        ]
        try:
            answer = await self._a4.complete(messages)
            return answer.strip(), "a4"
        except Exception:
            return self._fallback_view(entries, decision.redact), "fallback"

    @staticmethod
    def _fallback_view(entries: list[MemoryEntry], redact: bool) -> str:
        """Mechanical restricted view used when no A4 model can synthesise.

        Without a model we cannot redact intelligently, so a redaction-required
        grant degrades to metadata only (id + tags); otherwise short previews.
        """
        if redact:
            return "\n".join(f"[id={e.id} tags={','.join(e.tags) or '-'}]" for e in entries)
        return "\n".join(f"- {e.text[:_PREVIEW_CHARS].replace(chr(10), ' ')}" for e in entries)

    # ── audit ──────────────────────────────────────────────────────────────────

    async def _record(self, grant: AccessGrant) -> None:
        """Append the decision to the audit log. Never breaks the request."""
        if self._audit is None:
            return
        action = "mom1_access_granted" if grant.approved else "mom1_access_denied"
        try:
            await self._audit.append_history(
                {
                    "ts": time.time(),
                    "action": action,
                    "requester": grant.request.requester,
                    "query": grant.request.query,
                    "reason": grant.request.reason,
                    "decision_reason": grant.decision.reason,
                    "redact": grant.decision.redact,
                    "entries": [e.id for e in grant.entries],
                    "mediated_by": grant.mediated_by,
                },
                tags=["access", action],
            )
        except Exception:
            pass  # auditing must never break the operation it describes


# ── requester mixin ───────────────────────────────────────────────────────────

class Mom1Requester:
    """Gives a lower-privilege zone an adjudicated channel up to Mom1.

    Mixed into :class:`Mom2` / :class:`Mom3`. The broker is attached after
    construction (Mom1 is built last), so until :meth:`attach_mom1_broker` runs
    the zone simply has no upward channel — exactly the pre-existing isolation.
    """

    name: str  # provided by MemoryArea
    _mom1_broker: "Mom1AccessBroker | None" = None

    def attach_mom1_broker(self, broker: "Mom1AccessBroker") -> None:
        """Wire the adjudicated channel that lets this zone request Mom1 access."""
        self._mom1_broker = broker

    @property
    def can_request_mom1(self) -> bool:
        """True once a broker is attached (the channel is available)."""
        return self._mom1_broker is not None

    async def request_mom1(
        self,
        query: str,
        reason: str,
        scope: list[str] | None = None,
        max_entries: int | None = None,
    ) -> AccessGrant:
        """Apply to read Mom1; A1 adjudicates and A4 mediates the result.

        Returns an :class:`AccessGrant` — denied requests carry A1's reason and
        no content. Raises ``RuntimeError`` only when no broker is attached.
        """
        if self._mom1_broker is None:
            raise RuntimeError(
                "Mom1 access broker is not configured; this zone cannot reach Mom1."
            )
        return await self._mom1_broker.request(
            requester=self.name,
            query=query,
            reason=reason,
            scope=scope,
            max_entries=max_entries,
        )


_ADJUDICATION_SYSTEM = """\
You are A1, the authority governing Mom1 (the Total workspace's private memory) \
in the Autumn framework. A lower-privilege workspace — Mom2 (task) or Mom3 \
(mission) — is requesting read access to Mom1. Decide whether to grant it.

Approve only when the stated reason genuinely needs the requested information. \
Prefer the narrowest possible grant: restrict access to just the candidate \
entries that are relevant (by tag or id), and require redaction whenever the \
content includes anything sensitive (credentials, secrets, personal data).

Respond with ONLY valid JSON in exactly this shape:
{"approved": true, "reason": "<one sentence>", "allowed_scope": ["<tag-or-id>"], "redact": false}

"allowed_scope": [] means every candidate entry is allowed. Deny by setting \
"approved" to false."""

_MEDIATION_SYSTEM = """\
You are A4, the memory curator in the Autumn framework. A lower-privilege \
workspace has been granted RESTRICTED read access to Mom1 for a specific reason. \
Return only the information relevant to that reason and query, synthesised into \
a brief, direct answer. Do not reproduce the raw entries verbatim and do not \
surface anything unrelated to the request.{redaction}"""

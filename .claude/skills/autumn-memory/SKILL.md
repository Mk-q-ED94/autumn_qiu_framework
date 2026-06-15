---
name: autumn-memory
description: How to use Autumn's 4D memory — recall, remember, annotate, pin, list_recent, and request_mom1_access — across the Mom1/Mom2/Mom3/shared zones. Covers the four memory dimensions (aim / content / use / time), pull vs push retrieval, when to recall vs remember vs annotate, the Mom1 access-control channel, and the HTTP surface for client integrations. Use whenever stored context, past turns, user preferences, or cross-session facts would improve a response.
---

# Autumn Memory (4D)

> Adapted for Autumn from `skills/upstream/everos-memory`. The upstream skill drives the
> EverMem **cloud** `evermem_search` tool. Autumn has its **own local 4D memory engine** —
> this rewrite binds the guidance to Autumn's real skills, zones, and HTTP API. No cloud,
> no API key.

You have access to Autumn's memory engine. Use it proactively when stored context would
help — but selectively, not on every turn.

---

## The memory tools (ReAct skills)

Bound per workspace via `make_memory_skills` (`autumn/core/memory/skills.py`):

| Skill | Signature | What it does |
|-------|-----------|--------------|
| `recall` | `recall(query)` | Retrieve by key or natural language. Exact-key → tag filter → semantic vector search; top 5, relevance-ranked. |
| `remember` | `remember(key, value)` | Persist a fact under a key; auto-indexes into the vector store when enabled. |
| `list_recent` | `list_recent(n="5")` | The n most recent history entries (1–20), with pin/tag markers and ids. |
| `pin_memory` | `pin_memory(entry_id)` | Raise importance to the pin threshold so the entry is never evicted. |
| `annotate_memory` | `annotate_memory(entry_id, mode, intent, cues)` | Attach 4D dimensions to an entry (see below). |
| `request_mom1_access` | `request_mom1_access(query, reason, scope, max_entries)` | Governed read into Mom1 from a Mom2/Mom3 agent (see §Access). |

Find `entry_id`s via `list_recent` or `recall`.

---

## The four dimensions (why memory is "4D")

A memory is not a flat record. It has four orthogonal dimensions
(`autumn/core/memory/dimensions.py`; full design in `docs/rfc-4d-memory.md`):

| Dim | Question | Role |
|-----|----------|------|
| **aim** | *why* it exists | relevance **gate** — wrong goal/context ⇒ activation vetoed |
| **content** | *what* it is | the payload |
| **use** | *how* to apply it & *how it's been used* | processor **mode** + usage ledger (count / reward) |
| **time** (trigger) | *when* to fire | scheduler — decay, TTL, scheduling, throttle, contextual cues |

Activation combines them:

```
activation = w_time(trigger) × align(aim) × (1 + utility(use))
```

`align` is a gate (0 vetoes). `utility` is a boost (a fresh, never-used memory still
activates on `w_time × align`). With no dimensions set, this collapses to today's
importance×decay ranking — annotating is purely additive.

### Pull vs push

- **Pull** — someone calls `recall(query)`. The query is the activation context.
- **Push** — at the start of a turn the engine scans for memories whose `use.mode` is
  `constrain` or `remind` and whose trigger/aim fire **for the current situation**, and
  injects them automatically. This is why annotating a fact as a `constrain` matters: it
  surfaces itself when relevant instead of waiting to be searched.

Both are gated behind config (`fourd_memory_enabled`, `fourd_push_on_turn`), default off.

---

## The four zones

Autumn partitions memory by workspace (`autumn/core/memory/`):

| Zone | Owner | Visibility |
|------|-------|-----------|
| **Mom1** | WP1 (total/orchestration) | reads Mom1 **and** Mom2 **and** Mom3 |
| **Mom2** | WP2 (task) | reads Mom2 + shared |
| **Mom3** | WP3 (mission) | reads Mom3 + shared |
| **shared** | WP2 ⇄ WP3 | read/write by both task and mission |

Rules:
- Mom2/Mom3 **cannot** read Mom1 directly. To pull a Mom1-only fact, a task/mission agent
  calls `request_mom1_access(query, reason)`; A1 adjudicates and A4 returns a *mediated,
  restricted* answer. Access is never guaranteed — use only when the task truly needs it.
- Mom1 pushes context down via `broadcast(key, value)`, which writes to the **shared** zone
  so both WP2 and WP3 can see it. Use sparingly for session-level facts/preferences.

---

## When to use which

**`recall` when:**
- the user refers to past work/decisions ("how did we handle X?", "last time", "remember when")
- debugging something that may have been solved before
- the answer depends on project conventions/architecture already discussed
- context from earlier would materially improve the response

**Don't `recall` when:**
- the question is self-contained, or the user already gave all needed context
- it's general knowledge unrelated to this project's history
- you already searched this topic this session

**`remember` when:** a durable fact emerges worth carrying forward — a user preference, a
decision, a stable project fact, an unresolved thread. Use a clear `key`.

**`annotate_memory` when** a stored memory needs a behavior, set `mode`:

| mode | effect |
|------|--------|
| `constrain` | a hard rule the assistant must always follow — injected into the system prompt, eligible for push |
| `remind` | resurfaces proactively when its cues fire (push) |
| `summarize` | marks it a priority for consolidation by A4 |
| `context` | ordinary background (default; pull-only) |

Add a short `intent` (why it matters) and comma-separated `cues` (keywords that should
trigger it). Example: a deployment guardrail →
`annotate_memory(id, mode="constrain", intent="deploy_guardrail", cues="deploy,db,production")`.

**`pin_memory` when** an entry must survive eviction regardless of age (a critical fact in
a busy zone).

---

## Best practices

1. **Be selective.** Memory is a tool, not a reflex. Search only when past context adds value.
2. **Specific queries.** Search the relevant terms, not the user's whole message.
3. **Synthesize.** Integrate hits naturally into the answer; don't dump raw snippets.
4. **Be transparent.** Note when a response is informed by recalled context.
5. **Close the loop.** When a recalled memory proved useful, that's positive `reward` for
   its `use` ledger — useful memories rise, misleading ones sink over time.
6. **Right zone.** Write task facts to Mom2/shared, mission facts to Mom3/shared; don't try
   to reach into Mom1 unless the task depends on it (then go through `request_mom1_access`).

---

## HTTP surface (for client / web integrations)

The desktop and web clients drive memory over the Autumn server (`autumn/server/app.py`),
not these ReAct skills directly:

```
GET  /memory/{area}/history          list entries (area ∈ mom1|mom2|mom3|shared)
GET  /memory/stats                   stats across all zones
GET  /memory/{area}/stats            stats for one zone
POST /memory/{area}/consolidate      summarise old entries into one pinned digest (A4)
POST /memory/{area}/annotate         attach 4D dimensions
POST /memory/{area}/auto-annotate    let A4 infer dimensions
GET  /memory/4d/status               read the 4D feature flags
POST /memory/4d/config               toggle fourd_memory_enabled / push / reward decay
POST /memory/push/preview            preview what push would inject this turn
GET  /memory/audit/access_log        Mom1 access-control audit trail
GET  /projects/{project_id}/memory   per-project shared zone (501 if disabled)
```

Use these from `web/frontend/src/api/client.ts` and the desktop memory panels — never
hard-code the EverMem cloud routes the upstream skill referenced.

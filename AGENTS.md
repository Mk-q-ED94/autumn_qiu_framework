# AGENTS.md — Autumn (秋)

Guidance for Codex / Cursor / other agents in this repo. **Autumn** is a multi-model
collaborative workflow framework (Python core + macOS / Windows / web clients on one
HTTP/SSE contract). Companion: [`CLAUDE.md`](CLAUDE.md) (same content, Claude Code's
auto-loaded skills are mirrored here).

## Skills — read the matching one before working

Unlike Claude Code, you do **not** auto-discover `.claude/skills/`. Before doing work in
these areas, **open and follow** the matching skill file:

| When you are… | Read this skill |
|---------------|-----------------|
| building/restyling **any UI** (WinUI, SwiftUI, web) | [`.claude/skills/autumn-design-taste/SKILL.md`](.claude/skills/autumn-design-taste/SKILL.md) |
| working under **`web/frontend/`** (React) | [`.claude/skills/autumn-web-design-engineer/SKILL.md`](.claude/skills/autumn-web-design-engineer/SKILL.md) |
| using Autumn's **memory** (recall/remember/annotate, Mom1–3/shared) | [`.claude/skills/autumn-memory/SKILL.md`](.claude/skills/autumn-memory/SKILL.md) |

They are authoritative — don't freelance past them. Pristine upstream sources are under
`skills/upstream/`; the EverOS comparison is in `docs/everos-4d-memory-takeaways.md`.

## Repo map

```
autumn/              Python framework — core/ (framework, workspace wp1–wp4, memory),
                     builtin/ (Terrs), server/ (FastAPI HTTP/SSE), plugins/
desktop/AutumnApp/   macOS SwiftUI client — DesignSystem/Tokens.swift = canonical design
windows/AutumnDesktop/  Windows WinUI 3 / .NET 8 client
web/frontend/        React 18 + Vite + plain CSS (no UI framework)
docs/                rfc-4d-memory.md · everos-4d-memory-takeaways.md
tests/               pytest suite
```

## Architecture — A1–A4 / WP1–WP4

Four model slots → four workspaces (`autumn/core/workspace/`):

- **A1 / WP1** (`wp1.py`) — entry + router: classify the turn, route `direct` vs `convert`; lead project metadata discussions; quality advisory (Checker).
- **A2 / WP2** (`wp2.py`) — executor: ReAct loop over tools/skills, per-task-type hints.
- **A3 / WP3** (`wp3.py`) — mission: `answer_directly` or `convert_to_task` for WP2 (routing decided in WP1).
- **A4 / WP4** (`wp4.py`) — optional memory curator: recall synthesis + consolidation (A4), 4D push engine, Mom1 access broker, audit log. It does not lead project metadata discussions.

WP1–WP3 own Mom1/2/3; WP2⇄WP3 share `shared`. Wiring: `framework.py`; flags: `config.py`.

## Adding a capability domain (Terr)

A **Terr** (`autumn/core/components/terr.py`) bundles tools/skills/MCP into one domain.
Pattern (see `autumn/builtin/memory_terr.py`): write `def my_terr(...) -> Terr:` returning
`Terr(name, description, skills=[Skill(name, description, handler, parameters=[ToolParameter(...)])])`,
then register via `Autumn.add_terr(...)`. Don't connect MCP clients in a sync context.

## Design language — "Paper & Clay"

One neutral canvas + a single clay accent (`#CC6645`), hairline borders, near-zero
shadows. Source of truth: `desktop/AutumnApp/DesignSystem/Tokens.swift`; WinUI and web
mirror it. Never hard-code a value a token covers. (Web currently uses a divergent dark
theme — see the design-taste skill §3.)

## Memory — 4D

Four dimensions (aim / content / use / time), pull + push activation. Zones: Mom1 (reads
all) · Mom2 · Mom3 · shared. Design: `docs/rfc-4d-memory.md`; code: `autumn/core/memory/`.
From a task/mission agent, reach Mom1 only via `request_mom1_access`.

## Dev commands

```bash
pip install -e ".[dev]"     # Python 3.11+
pytest                       # full suite
ruff check .                 # lint (excludes desktop/)
bash script/build_and_run.sh # build + run
```

WinUI / SwiftUI clients aren't compilable in Linux CI — hand-reviewed; built locally.

## Branch policy

- **`main`** — Python framework + general work + agent skills/docs.
- **`claude/windows-client`** — Windows client only (PR #20). Keep non-Windows work off it.
- Don't open PRs unless asked. Commits: imperative, scoped, no model identifiers.

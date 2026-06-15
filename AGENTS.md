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

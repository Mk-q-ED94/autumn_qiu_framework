# CLAUDE.md — Autumn (秋)

Guidance for AI agents working in this repo. **Autumn** (秋) is a multi-model
collaborative workflow framework: a Python core (A1/A2/A3/A4 across WP1–WP4) plus three
native clients sharing one HTTP/SSE contract.

## Mounted skills (use them — this is the point)

Three customized skills live in `.claude/skills/` and are **authoritative**. Invoke the
matching one *before* doing work in its area; don't freelance past it.

| When you are… | Use skill | Source |
|---------------|-----------|--------|
| building/restyling **any UI** (WinUI, SwiftUI, or web) | **`autumn-design-taste`** | `.claude/skills/autumn-design-taste/SKILL.md` |
| working under **`web/frontend/`** (React) | **`autumn-web-design-engineer`** | `.claude/skills/autumn-web-design-engineer/SKILL.md` |
| using Autumn's **memory** (recall/remember/annotate, Mom1–3/shared) | **`autumn-memory`** | `.claude/skills/autumn-memory/SKILL.md` |

Pristine upstream sources kept under `skills/upstream/` for diffing. Rationale + the
EverOS comparison live in `docs/everos-4d-memory-takeaways.md`.

## Repo map

```
autumn/              Python framework (the runtime "framework")
  core/              framework.py · workspace/{wp1..wp4} · memory/ · components/ · api/
  builtin/           built-in Terrs (capability domains: fs, web, memory, time, …)
  server/            FastAPI HTTP/SSE app (app.py) — the client contract
  plugins/           PluginLoader (loads Terr/Skill/Tool/Agent from .py dirs)
desktop/AutumnApp/   macOS SwiftUI client  (DesignSystem/Tokens.swift = canonical design)
windows/AutumnDesktop/  Windows WinUI 3 / .NET 8 client
web/frontend/        React 18 + Vite + plain CSS client (no UI framework)
docs/                rfc-4d-memory.md · everos-4d-memory-takeaways.md
skills/ + .claude/skills/   agent skills (see above)
tests/               pytest suite
```

## Design language — "Paper & Clay"

One calm, neutral canvas warmed by **a single clay/terracotta accent** (`#CC6645`).
Hairline borders do the structure; shadows are near-invisible. **`desktop/AutumnApp/
DesignSystem/Tokens.swift` is the source of truth**; WinUI (`windows/.../App.xaml`) and
web (`web/frontend/src/styles.css`) mirror it. Never hard-code a value a token covers.
⚠️ The web client currently uses a divergent dark dev-theme — see `autumn-design-taste` §3.

## Memory — 4D

Memory is four orthogonal dimensions (aim / content / use / time) with pull **and** push
activation. Zones: Mom1 (WP1, reads all) · Mom2 (WP2) · Mom3 (WP3) · shared (Mom2⇄Mom3).
Design: `docs/rfc-4d-memory.md`. Code: `autumn/core/memory/`. Usage: the `autumn-memory`
skill. Don't reach into Mom1 from a task/mission agent — use `request_mom1_access`.

## Runtime "Skills" vs these dev skills

Two different things, don't conflate them:
- **Autumn runtime `Skill`/`Terr`** (`autumn/core/components/skill.py`) = Python callables
  exposed to A1/A2/A3 as LLM tools (e.g. `recall`, `remember`, fs/web ops).
- **`.claude/skills/*` SKILL.md** = dev-time guidance for the agent building Autumn (you).

## Dev commands

```bash
pip install -e ".[dev]"     # Python 3.11+
pytest                       # full suite (asyncio_mode=auto, testpaths=tests)
ruff check .                 # lint (F + E; line-length 110; excludes desktop/)
bash script/build_and_run.sh # build + run (the Codex "Run" action)
```

WinUI (`windows/`) and SwiftUI (`desktop/`) can't be compiled in this Linux env — they are
hand-reviewed; the user builds locally.

## Branch policy

- **`main`** — Python framework + general work + agent skills/docs. General changes land here.
- **`claude/windows-client`** — **Windows client only** (tracked by PR #20). Don't put
  non-Windows work on it.
- Don't open PRs unless asked. Commit messages: imperative, scoped, no model identifiers.

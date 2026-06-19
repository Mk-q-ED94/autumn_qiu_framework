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

## Architecture — A1–A4 / WP1–WP4

Four model slots drive four workspaces (`autumn/core/workspace/`):

| Slot | Workspace | Role |
|------|-----------|------|
| **A1** | **WP1** `wp1.py` (orchestration) | Entry + router. A Selector classifies the turn and picks a mission route — `direct` (answer conversationally) or `convert` (make a structured task). Runs the quality advisory (Checker). |
| **A2** | **WP2** `wp2.py` (task) | The executor: a ReAct loop over enabled tools/skills, with per-task-type hints (CODE / SEARCH / WRITE / DATA / GENERAL). |
| **A3** | **WP3** `wp3.py` (mission) | `answer_directly` (natural reply) or `convert_to_task` (reformat the mission into a task for WP2). The routing decision itself lives in WP1. |
| **A4** | **WP4** `wp4.py` (memory) | Optional. Curator of *all* memory: cognitive ops (recall synthesis, consolidation) use A4; mechanical ops (forget/stats/pin) delegate to the `MemoryArea`. Owns the 4D push engine, the Mom1 access broker, project intelligence, and its own audit log. |

WP1–WP3 each own one Mom zone (Mom1/2/3); WP2⇄WP3 share the `shared` zone. Wiring is in
`autumn/core/framework.py`; model slots + behavior flags in `autumn/core/config.py`
(`BehaviorConfig`, incl. `fourd_memory_enabled` / `fourd_push_on_turn` /
`codebase_memory_enabled`).

**Codebase memory (token-saving layer).** `codebase_memory_enabled` (off by default)
wires the external `codebase-memory-mcp` code-graph server (catalog id `codebase_memory`,
factory `mcp_codebase_memory`) so agents query code structure (calls/imports/architecture)
instead of reading files. The server auto-connects it at startup when on; it's also a live
toggle at `/config/codebase-memory` (设置 → 高级). It's a normal catalog MCP — needs `uvx`/`npx`
on the host — surfaced through the shared integration runtime, not a vendored engine.

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

## Adding a capability domain (Terr)

A **Terr** (域, `autumn/core/components/terr.py`) bundles related tools/skills/MCP clients
into one capability domain registered in a single call. The model sees the flat
tool/skill schemas; the Terr description is surfaced in the system prompt.

Convention (examples: `autumn/builtin/memory_terr.py`, `time_terr.py`):
1. Write a factory `def my_terr(...) -> Terr:` that builds `Skill`s (name, description,
   `handler`, `parameters=[ToolParameter(...)]`) and returns
   `Terr(name=..., description=..., skills=[...], tools=[...])`.
2. Register via `Autumn.add_terr(terr)` — it runs the MCP connect → bridge → register
   pipeline. Don't connect MCP clients yourself in a sync context.
3. Handlers return strings / JSON the model can read; mirror the existing builtin terrs'
   docstring + parameter style. `PluginLoader.load_from_directory` auto-loads `.py` files
   that define `Terr`/`Skill`/`Tool`/`Agent` objects.

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

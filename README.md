<p align="center">
  <img src="./assets/banner.png" alt="秋 / Autumn — Multi-Model Collaborative Workflow Framework" width="100%">
</p>

<p align="center"><strong>English</strong> | <a href="./README.zh-CN.md">简体中文</a></p>


A multi-model collaborative workflow framework. Three model API interfaces (A1, A2, A3) each govern a workspace (WP1, WP2, WP3) backed by a memory area (Mom1, Mom2, Mom3), coordinated by a strict routing protocol to produce results that exceed what any single model can achieve alone. A fourth, optional model (A4) drives **WP4**, the dedicated memory-management workspace that curates every zone.

## Architecture

```
                       ┌─────────────────────────────────────┐
                       │           WP1 Tot  (A1, Mom1)        │
                       │    ┌────────────┐                    │
  user input ──────────┼──► │  selector  │                    │
                       │    └────────────┘                    │
                       │       │      │                       │
                       │     task   mission                   │
                       │       │      │                       │
                       │       ▼      ▼                       │
                       │  ┌──────────────────────────────┐    │
                       │  │  WP2 Tas (A2, Mom2)          │    │
                       │  │  WP3 Mis (A3, Mom3)          │    │
                       │  │       └─ shared zone ─┘      │    │
                       │  └──────────────────────────────┘    │
                       │    each WP has its own checker       │
                       └─────────────────────────────────────┘
                          WP4 Mem (A4) curates all memory ▲
                          Mom1/2/3 · shared · project ────┘
```

**Routing pipelines** (all paths end with WP1.checker before reaching the user):

| Path                  | Flow                                                            |
| --------------------- | --------------------------------------------------------------- |
| `task`                | WP2 → wp2.check → wp1.check                                     |
| `mission` → direct    | WP3 → wp1.check                                                 |
| `mission` → convert   | WP3 → wp3.check → wp1.check → WP2 → wp2.check → wp1.check       |

**Memory access** (enforced by composition):

- `Mom1` can read `Mom2` and `Mom3`.
- `Mom2` and `Mom3` share a public zone but cannot read `Mom1`.
- Each layer has two tiers: short-term in-memory cache + persistent SQLite.

**Governed upward channel** — the default isolation is asymmetric, but a *gated*
path exists so a lower zone is not permanently walled off: `Mom2`/`Mom3` can
**request** a `Mom1` read, which `A1` adjudicates (approve/deny + narrowed scope
+ redaction), `A4` mediates into a restricted answer, and `WP4` audits. It is
exposed to the agent ReAct loop as the `request_mom1_access` skill, and every
decision — granted or denied — is recorded to the access audit log
(`GET /memory/audit/access_log`). Kill-switch: `MOM1_ACCESS_ENABLED=false`
denies every request without ever consulting `A1`.

**Per-project shared memory** — each project id gets its own isolated zone, but
within a project the zone is *shared* across every workspace and turn:

```python
autumn.add_memory_skills("project")        # recall/remember bind to the active project
with autumn.project_scope("acme-app"):     # sets the active project for this block
    await autumn.process("remember the deploy target is fly.io")
# A different project sees nothing of acme-app's memory:
await autumn.project_zone("acme-app").get("...")   # isolated namespace
```

Over HTTP, pass `project_id` to `/process`, `/trace`, or `/stream`; manage zones
with `GET /projects`, `GET /projects/{id}/memory`, and `DELETE /projects/{id}`.

**Memory lifecycle** — every zone (Mom1/2/3, shared, project) supports:

- **Importance & pinning** — `append_history(..., importance=2.0)` pins an entry;
  pinned entries never evict. Eviction drops the lowest-importance entries first.
- **TTL / expiry** — `append_history(..., ttl=3600)` makes an entry ephemeral;
  expired entries are filtered on read and purged on the next write.
- **Time-decay** — set `MEMORY_DECAY_HALF_LIFE` (seconds) so stale low-value
  memories fade and get evicted before fresh ones.
- **Consolidation** — `await zone.consolidate(api)` summarises old entries into a
  single pinned digest (uses the A4 model); over HTTP: `POST /memory/{area}/consolidate`.
- **Forget & stats** — `zone.forget(tags=..., before=..., expired=True)` bulk-prunes;
  `zone.stats()` / `GET /memory/{area}/stats` report counts, tags and time span.

**WP4 — the memory-management workspace** — A4 gets its own workspace whose sole
job is curating *all* memory. WP1–WP3 each own one Mom area and drive the
conversation; WP4 owns none of that flow and instead addresses every zone by
name (`mom1`/`mom2`/`mom3`/`shared`/`project`). A4 powers the cognitive work
(recall synthesis, consolidation summaries); the mechanical work (forget, stats,
pin) delegates to the target zone. WP4 keeps its own audit log so each action it
takes is itself recorded.

```python
autumn.add_memory_skills("shared")          # recall/remember skills, built by WP4

await autumn.wp4.remember("deploy", "fly.io")          # write to a zone
await autumn.wp4.recall("deploy")                       # unified retrieval
await autumn.wp4.consolidate("mom2")                    # summarise via A4
await autumn.wp4.forget("shared", tags=["scratch"])     # bulk prune
await autumn.wp4.stats()                                # snapshot of every zone
```

Over HTTP the memory endpoints route through WP4: `GET /memory/stats` returns an
all-zone overview, and `shared` joins `mom1/2/3` as an addressable area for
`/memory/{area}/history|stats|consolidate`. Consolidation uses WP4's A4 slot, so
it 400s cleanly when no A4 model is configured.

**4D memory (active memory)** — beyond its content, every entry can optionally
carry three more orthogonal dimensions, turning a passive record into a unit
with its own activation policy (full design:
[`docs/rfc-4d-memory.md`](docs/rfc-4d-memory.md)):

| Dimension | Question it answers | Role |
| --------- | ------------------- | ---- |
| `aim`     | *why* does this memory exist | relevance gate — vetoes activation when misaligned with the turn's goal/cues |
| content   | *what* is it                 | the payload (the existing entry body) |
| `use`     | *how* to apply it — and how it has been used | processing mode (`CONTEXT`/`REMIND`/`CONSTRAIN`/`SUMMARIZE`) + usage ledger |
| `trigger` | *when* should it fire        | scheduler — half-life, not-before/expiry, cooldown, cue matching |

```python
from autumn.core.memory import Aim, Use, UseMode, Trigger

await autumn.mom1.append_history(
    "never write to the prod database directly",
    use=Use(mode=UseMode.CONSTRAIN),                    # how: inject as a hard rule
    aim=Aim(intent="deploy safety", scope=["deploy"]),  # why: gate on alignment
    trigger=Trigger(cues=["deploy", "release"]),        # when: boost on matching cues
)
```

Recall ranks by `activation = trigger.weight × (importance × decay) × aim.align
× (1 + use.utility)`. Eviction deliberately ignores `aim`/`trigger` and keeps
what has proven useful (`retention = effective_importance × (1 + utility)`), so
a high-value but currently-dormant memory is not evicted just because it is out
of context.

Two switches, both **off by default** — when off, behaviour is identical to the
classic importance×recency model, and v1 records load unchanged (serialization
is versioned, `_v=2`):

- `FOURD_MEMORY_ENABLED` (`BehaviorConfig.fourd_memory_enabled`) — recall and
  eviction switch to 4D activation scoring.
- `FOURD_PUSH_ON_TURN` (`BehaviorConfig.fourd_push_on_turn`) — **push
  activation**: at the start of every `process`/`stream` turn,
  `CONSTRAIN`/`REMIND` memories whose trigger/aim gates open against the turn
  fire automatically and are appended to the WP2/WP3 system prompts as an
  "active constraints / reminders" block. The workflow trace gains a `wp4.push`
  stage (WP4 purple in the desktop client) showing what fired.

```python
# pull: recall + use-ledger write-back, so useful memories rank higher over time
hits = await autumn.wp4.activate("deploy target", area="shared")

# push, manual seam (returns "" when the flag is off or nothing fires)
frag = await autumn.active_context(text="deploying v2 now")
```

**Producing annotations** — the activation engine only discriminates once
entries actually carry dimensions; un-annotated data scores exactly as
importance×recency. Three ways to feed it:

- **A4 inference** — `await autumn.wp4.annotate_recent("mom1")` scans
  un-annotated entries and lets A4 classify each into a use-mode + purpose +
  trigger cues. Over HTTP: `POST /memory/{area}/auto-annotate`.
- **Agent-declared** — the `annotate_memory` skill lets a WP2/WP3 agent tag an
  entry it just stored ("this is a constraint", "remind on deploy").
- **User / UI** — `POST /memory/{area}/annotate` sets dimensions on one entry
  (and `MemoryArea.annotate()` in code); consolidation digests are auto-marked
  `SUMMARIZE`.

**Observability** — `GET /memory/4d/status` reports whether ranking/push are
actually enabled (vs. the dormant default), and `POST /memory/push/preview`
dry-runs the push engine for a hypothetical turn *without* reinforcing,
returning the fired memories, their activation scores, and the exact prompt
fragment that would be injected. The macOS Memory view surfaces all of it: 4D
status badges, one-tap auto-annotate, per-entry annotation controls, a
push-preview mode, and a Mom1 access-audit panel.

**Runtime control** — the three switches above are normally env-set, but
`autumn.configure_4d(memory_enabled=…, push_on_turn=…, mom1_access_enabled=…)`
flips them live (propagating the ranking toggle to every zone, including cached
project zones). Over HTTP: `POST /memory/4d/config`; in the macOS client:
**Settings → 记忆 → 4D 记忆引擎**. Changes apply immediately and reset to the
`.env` defaults on restart.

## Quick start

```bash
cp .env.example .env       # fill in A1/A2/A3 keys
pip install -e .
```

```python
import asyncio
from autumn import Autumn, AutumnConfig

async def main():
    config = AutumnConfig.from_env(env_file=".env")
    async with Autumn(config) as autumn:
        result = await autumn.process("帮我写一个周末旅行清单")
        print(result)

asyncio.run(main())
```

Prefer building the config in code? Use `ModelConfig` directly:

```python
from autumn import AutumnConfig, ModelConfig, Protocol

config = AutumnConfig(
    a1=ModelConfig(api_key="...", base_url="https://api.openai.com",
                   model="gpt-4o-mini", protocol=Protocol.OPENAI),
    a2=ModelConfig(api_key="...", base_url="https://api.anthropic.com",
                   model="claude-sonnet-4-5", protocol=Protocol.ANTHROPIC),
    a3=ModelConfig(api_key="...", base_url="https://api.openai.com",
                   model="gpt-4o", protocol=Protocol.OPENAI),
)
```

## Streaming

```python
async for chunk in autumn.stream("写一首关于秋天的诗"):
    print(chunk, end="", flush=True)
```

When you need both real-time chunks AND the final trace (token usage, stage
timings, agent tool calls), use `stream_with_trace` — strings stream as before,
then a single `WorkflowRun` arrives at the end:

```python
from autumn import WorkflowRun

async for event in autumn.stream_with_trace("写一首关于秋天的诗"):
    if isinstance(event, str):
        print(event, end="", flush=True)
    elif isinstance(event, WorkflowRun):
        for stage in event.stages:
            print(f"\n[{stage.id}] {stage.duration_ms:.0f}ms")
```

By default streaming runs the full validated pipeline before chunking — set
`validate_before_stream=False` in `AutumnConfig` (or `VALIDATE_BEFORE_STREAM=false`
in env) to flip on live token streaming with a post-hoc advisory checker.

Override the mission route for a single call when you do not want to use the
configured `HEADLESS_MISSION_ROUTE`:

```python
from autumn import MissionRoute

result = await autumn.process(
    "把这个产品想法整理成执行计划",
    mission_route=MissionRoute.CONVERT,
)
```

## Memory skills

`Autumn.add_memory_skills(area)` registers two skills — `recall(query)` and
`remember(text)` — that any tool-using agent (WP2 included) can call to query
or write into a memory area. Use the optional A4 model slot to power synthesis
cheaply (e.g. a local Ollama model):

```python
from autumn import AutumnConfig, ModelConfig, Protocol

config = AutumnConfig(
    a1=..., a2=..., a3=...,
    a4=ModelConfig(api_key="ollama", base_url="http://localhost:11434",
                   model="llama3.1:8b", protocol=Protocol.OPENAI),
)
async with Autumn(config) as autumn:
    autumn.add_memory_skills("shared")  # or "mom1" / "mom2" / "mom3" / "project"
    await autumn.process("回忆一下我上周让你研究的事情")
```

## Interactive mode

```python
from autumn import CLIInteraction

async with Autumn(config, interaction=CLIInteraction()) as autumn:
    await autumn.process("...")  # confirms low-confidence classifications, asks mission route
```

## Built-in capability domains (Terrs)

`autumn.builtin` ships ready-made Terr factories for the chores every agent
ends up needing — telling time, doing math, parsing JSON, fetching URLs,
reading sandbox files. They register through the same enable/disable toggle
the desktop UI uses for every other Terr.

| Terr         | Safety        | Tools / skills                                                          |
| ------------ | ------------- | ----------------------------------------------------------------------- |
| `time`       | always safe   | `now`, `parse_time`, `time_diff`, `time_add`, `time_today`              |
| `math`       | always safe   | `calc` (AST-whitelisted), `stats`                                       |
| `text`       | always safe   | `count_text`, `regex_find`, `extract_urls`, `split_text`, `replace_text`|
| `data`       | always safe   | `parse_json`, `to_json`, `parse_csv`, `to_csv`, `json_path`             |
| `encoding`   | always safe   | `base64_encode/decode`, `hex_encode/decode`, `hash_text`, `url_encode/decode`, `uuid_generate` |
| `collection` | always safe   | `unique`, `flatten`, `chunk`, `frequencies`, `group_by`, `sort_records` |
| `web`        | opt-in (net)  | `http_get`, `http_get_json`, `http_head`, `fetch_text`                  |
| `fs`         | sandboxed     | `read_file`, `write_file`, `list_dir`, `file_info`, `delete_file`       |
| `memory`     | bound to area | `recall`, `remember`, `list_recent`, `pin_memory`                       |

```python
from autumn import time_terr, math_terr, register_safe_builtins, register_builtins

# Pick what you need
autumn.register_terr(time_terr())
autumn.register_terr(math_terr())

# Or wire up the safe set in one call
register_safe_builtins(autumn)               # time + math + text + data + encoding + collection

# Opt into network + filesystem + memory
register_builtins(
    autumn,
    include_web=True,
    fs_root="/tmp/agent-ws",
    include_memory=True,
    memory_area="shared",
)
```

`autumn.builtin.mcp_catalog` exposes factory functions for the official MCP
servers most commonly used by agents:

| Factory                   | Server                                  | Credentials needed       |
| ------------------------- | --------------------------------------- | ------------------------ |
| `mcp_filesystem(root)`    | `@modelcontextprotocol/server-filesystem` | —                      |
| `mcp_fetch()`             | `mcp-server-fetch`                      | —                        |
| `mcp_git(repo)`           | `mcp-server-git`                        | —                        |
| `mcp_sqlite(db_path)`     | `mcp-server-sqlite`                     | —                        |
| `mcp_brave_search(key)`   | `server-brave-search`                   | Brave Search API key     |
| `mcp_github(token)`       | `server-github`                         | GitHub PAT               |
| `mcp_puppeteer()`         | `server-puppeteer`                      | —                        |
| `mcp_memory()`            | `server-memory`                         | —                        |
| `mcp_postgres(conn_str)`  | `server-postgres`                       | connection string        |
| `mcp_slack(token, team)`  | `server-slack`                          | Slack bot token + team   |
| `mcp_gitlab(token)`       | `server-gitlab`                         | GitLab PAT               |
| `mcp_google_maps(key)`    | `server-google-maps`                    | Google Maps API key      |
| `mcp_sequential_thinking()` | `server-sequential-thinking`          | —                        |
| `mcp_time()`              | `mcp-server-time`                       | —                        |
| `mcp_everything()`        | `server-everything` (reference/test)    | —                        |

Each factory returns an unconnected `StdioMCPClient`; pass it into a
`Terr(mcps=[...])` and `await autumn.add_terr(...)` to connect and register.

**Server-side opt-in**: set `AUTUMN_BUILTIN_TERRS=safe` to automatically
register the always-safe domains on server startup (default off). Use
`AUTUMN_BUILTIN_TERRS=all` to also include `web`.

## Platform integrations

For the credentialed platforms above, the HTTP server turns a saved token into
live agent capability — no code, no per-request plumbing. Save a credential
once and the WP2 agent gains that platform's tools for the rest of the session:
it reads and edits issues, PRs, files and messages on its own whenever a request
calls for it.

```text
GET    /integrations/catalog       # connectable platforms + the fields each needs (secret-free)
GET    /integrations/status        # per-platform: connected? how many tools? last error?
POST   /integrations/connect       # { "id": "github", "args": { "token": "ghp_…" } }
DELETE /integrations/{id}           # revoke: disconnect the MCP server, forget the token
```

`connect` starts the matching MCP server, bridges its tools, and registers them
as a Terr (so they also show up in `/terrs` and can be toggled). Reconnecting an
already-connected platform rotates the token cleanly. Credentials live only in
the server process, survive a `/config/apply` rebuild, and **status never echoes
the secret back**. Catalog: GitHub, GitLab, Slack, Brave Search, Google Maps,
PostgreSQL. The server host needs `npx` / `uvx` to launch the MCP binaries.

In the macOS client this is the **Settings → 集成** tab: a credential form per
platform with connect / update / disconnect and live status.

## Security

Two controls make the HTTP bridge safe to run beyond a single-user localhost box:

- **API-key auth** — set `AUTUMN_API_KEY` and every endpoint except `/health`
  requires the shared secret (`Authorization: Bearer <key>` or `X-API-Key: <key>`),
  compared in constant time and read per request so it rotates without a restart.
  Unset → open, exactly as before, so local runs are unaffected. The server warns
  at startup if it binds beyond `127.0.0.1` with no key set. The desktop client
  carries the key from **Settings → 服务器 → 访问密钥**.
- **Read-only platform access by default** — connecting GitHub / GitLab / Slack / …
  grants the agent only that platform's *read* surface. Mutating tools (create /
  edit / delete / merge / push / post …) are withheld entirely until you pass
  `write_enabled: true` on `POST /integrations/connect` (the **允许写操作** toggle in
  the Settings → 集成 tab) and reconnect. Status reports `write_enabled` and how
  many write tools are blocked, so the grant is always visible. The dangerous
  capability is simply absent unless deliberately granted.

Credentials live only in the server process (status never echoes them back) and
in the client's local preferences. A Keychain-backed at-rest store for the client
is the next planned hardening step.

## Plugins

```python
from autumn import Tool, ToolParameter, Agent, StdioMCPClient

# Custom tool
tool = Tool("search", "Web search", search_fn, [ToolParameter("q", "string", "query")])
autumn.register_tool(tool)

# Agent with ReAct loop — tool calls in each turn run concurrently via asyncio.gather
agent = Agent("researcher", api=autumn.a2, tools=[tool])
result = await agent.run("Find recent papers on retrieval-augmented generation")

# MCP server — all its tools auto-registered
client = StdioMCPClient(["python", "-m", "my_mcp_server"])
mcp_tools = await autumn.add_mcp(client)

# Directory-based hot loading
Autumn(config, plugin_dirs=["./my_plugins"])
```

## Configuration

```python
from autumn import AutumnConfig, WorkspacePrompts, StorageConfig, MissionRoute

AutumnConfig(
    a1=..., a2=..., a3=...,
    prompts=WorkspacePrompts(
        wp2_task="You are a meticulous task executor...",
        wp3_convert="Convert this mission into bullet steps...",
        # Any of the seven slots can be overridden.
    ),
    storage=StorageConfig(db_path="my_app_memory.db"),
    headless_mission_route="auto",   # or MissionRoute.DIRECT / MissionRoute.CONVERT
)
```

## Component reference

| Component        | Responsibility                                                  |
| ---------------- | --------------------------------------------------------------- |
| `Autumn`         | Entry point; wires everything from config                       |
| `WP1Tot`         | Orchestrates routing and final validation                       |
| `WP2Tas`         | Executes structured tasks via A2                                |
| `WP3Mis`         | Handles missions: direct answer or convert-to-task              |
| `WP4Mem`         | Memory-management workspace; A4-backed curator of every zone     |
| `Selector`       | Classifies input; triggers user confirmation when uncertain     |
| `Checker`        | Per-workspace output validator (rules + model eval, retry 3x)   |
| `Agent`          | Autonomous executor with ReAct tool-use loop                    |
| `Tool`           | Callable exposed to models via tool-use API                     |
| `Skill`          | Named, reusable capability                                      |
| `MCPClient`      | Model Context Protocol client (`StdioMCPClient` provided)       |
| `Mom1/2/3`       | Layered memory; supports persistent + session-scoped storage    |
| `PluginLoader`   | Discovers plugins from directories or accepts manual registration |

## Layout

```
autumn/
├── core/
│   ├── api/          # ModelAPIInterface, A1/A2/A3/A4
│   ├── memory/       # Mom1/2/3, SharedZone, ProjectMemory, dimensions (4D), backends (Dict/SQLite/Hybrid)
│   ├── workspace/    # WP1Tot, WP2Tas, WP3Mis, WP4Mem
│   ├── components/   # Agent, Skill, Tool, Selector, Checker, MCP*
│   ├── config.py     # AutumnConfig, ModelConfig, WorkspacePrompts
│   ├── interaction.py# UserInteraction, CLIInteraction
│   └── framework.py  # Autumn (entry point)
└── plugins/loader.py # PluginLoader
```

## HTTP server & desktop client

A FastAPI bridge exposes the framework over HTTP/SSE so any client can drive it.
The SwiftUI macOS app under `desktop/` is the reference client. It automatically
starts the local bridge with `python -m autumn.server` when its server URL points
to localhost and no existing server is responding.

```bash
pip install -e ".[server]"
python -m autumn.server            # listens on 127.0.0.1:8765

curl -X POST http://127.0.0.1:8765/models \
  -H 'Content-Type: application/json' \
  -d '{"api_key":"sk-...","base_url":"https://api.openai.com","protocol":"openai"}'

curl -X POST http://127.0.0.1:8765/process \
  -H 'Content-Type: application/json' \
  -d '{"input":"把这个想法变成任务清单","route":"convert"}'

curl -N 'http://127.0.0.1:8765/stream?input=写一段欢迎语&route=direct'

# Build & open the desktop app (requires Xcode + XcodeGen on macOS):
bash ./script/build_and_run.sh
```

`/stream` interleaves `{"chunk": "..."}` events with a single final
`{"trace": {...}}` carrying the same shape as `/trace`. Every endpoint
(`/process`, `/trace`, `/intent`, `/stream`) accepts an optional
`project_instructions` field that the server prepends to the user input as a
project-scoped preamble — see [`desktop/README.md`](desktop/README.md) for the
full endpoint reference and workflow.

## Development

```bash
pip install -e ".[dev]"
python -m pytest
```

## Development history

Current version: **0.3.1**. Autumn follows semantic versioning; while `0.x`,
minor versions add features and may adjust APIs.

### 0.3.1 — 2026-06-17 · Client optimization & adaptation

Polishes the desktop client and turns the MCP catalog into a place you can
actually learn about and switch on servers — plus the server-side surface that
backs it. Layers on top of the 0.3.0 framework.

- **Per-MCP intro, inline config & setup tutorials** — the 能力域 (Terr) page's
  MCP catalog is now expandable: each MCP shows what it does, a live connection
  badge, an inline credential/path form (read-only by default with a write
  toggle), and a step-by-step setup tutorial with a doc link. Keyless utilities
  connect with one click; configured ones connect after their form is filled.
- **Generalized MCP connection** — new `/mcps/status`, `/mcps/connect`,
  `/mcps/{id}` bring *any* catalog MCP online (not just the six credentialed
  platforms), sharing the platform-integration runtime so connection state is
  consistent across Settings and the Terr page. `GET /mcps/catalog` now carries
  category, form fields and the tutorial.
- **Stale-server resilience** — the server advertises an `api_revision` on
  `/health`; the desktop app detects a reachable-but-old local server (e.g. one
  left running across a `git pull`) and **auto-restarts it** from the repo,
  killing only the process *listening* on the port. Where it can't (remote /
  unmanaged), the Terr page shows a clear "restart your server" notice and maps a
  bare 404 to an actionable message instead of "not found".
- **Desktop design polish (macOS)** — motion unified on the `Autumn.motion`
  tokens; `accessibilityReduceMotion` honoured on every looping animation; shared
  press-scale + hover states on buttons; the window title-bar material no longer
  overshoots and covers the Memory / Terrs / Settings toolbars.
- **Docs** — `docs/local-build-test.md` documents the pull → build → test loop
  across the framework, macOS, web and Windows clients.
- **Tests** — 842 passing (adds `tests/test_server_mcps.py`), ruff clean.

### 0.3.0 — 2026-06-17 · Cooperative multi-model workflow + central security

Turns the A1–A4 pipeline into a **two-way cooperative workflow**: A1 (组长) now
leads — planning, supervising and delegating — instead of only bookending the
route. Every feature sits behind a gate; the `COOPERATIVE_WORKFLOW` master switch
(off) reverts the whole layer to 0.2.x behaviour.

- **Task / Mission boundary, by executor** — TASK → A2 (heavy code work),
  MISSION → A3 (all other general work: writing, analysis, summarisation, docs);
  A3 still escalates heavier missions via convert.
- **A1 leads the pipeline** — A1 gains handles to WP4, project memory and the
  Mom1 access broker, so it supervises execution and leads project discussions
  rather than only appearing at the route / final-check ends.
- **A1 task planning** — before dispatching a TASK, A1 drafts a 3–6 step plan
  injected as a WP2 system hint; surfaced as a `wp1.plan` trace stage. Gated by
  `A1_TASK_PLANNING`.
- **A1 supervision** — after each ReAct step A1 reviews A2's action and may inject
  corrective guidance (provider-agnostic); surfaced as `wp1.supervise` stages.
  Gated by `A1_SUPERVISION`.
- **Capability-aware routing** — the Selector sees a digest of enabled Terr
  domains when classifying, so routing reflects what the agent can actually do.
- **A3 lite toolset** — A3 gains a bounded (≤4-step, whitelist-gated) skill loop
  so it can call recall / time / etc. before answering, on both the streaming and
  non-streaming direct paths. Set via `A3_LITE_SKILLS`.
- **A4 cognitive delegation** — WP4's heavy cognitive ops (consolidate / evolve /
  extract_facts / synthesize_profile / annotate) and project-parameter discussion
  prefer the strong A1 over the weak local A4, with a size threshold keeping small
  ops local. Gated by `A4_DELEGATE_TO_A1` (on).
- **A4 knowledge Terr + research** — a new `knowledge_terr` (web_search /
  fetch_document / knowledge_base_query) and a bounded `WP4.research()` loop give
  A4 external retrieval. Gated by `A4_KNOWLEDGE_TERR`.
- **Execution archive** — each turn's outcome is written to the shared zone
  (`wp4.push`), so the team accrues a searchable history. Gated by
  `ARCHIVE_EXECUTIONS`.
- **Central security module** — `autumn/core/security.py` consolidates the SSRF
  guard, secret redaction, path sandboxing and resource limits used across the
  network Terrs and the HTTP bridge, plus broadened protections (math-DoS bounds,
  request body-size limit, security headers, configurable CORS). Builds on the
  0.2.3 API-key auth and read-only-by-default platform integrations.
- **Full-module optimization + robustness pass** — memory decode tolerance, API
  retry/usage hardening, network-Terr dedup with SSRF re-validation on redirects,
  framework-wiring fixes.
- **Tests** — 928 passing (adds `tests/test_cooperative_workflow.py`), ruff clean.

### 0.2.2 — 2026-06-13 · 4D memory (active memory), client redesign, platform integrations & quality pass

- **Platform integrations** — save a credential once (GitHub, GitLab, Slack,
  Brave, Google Maps, Postgres) and the WP2 agent gains that platform's tools
  for the session: it reads and edits issues, PRs, files and messages on its
  own, with no per-request credential plumbing. The server starts the matching
  MCP server and registers it as a Terr — `GET /integrations/catalog`,
  `/integrations/status`, `POST /integrations/connect`,
  `DELETE /integrations/{id}`. Credentials stay in the server process, survive a
  `/config/apply` rebuild, and status never echoes the secret back. The macOS
  Settings → 集成 tab drives connect / update / disconnect with live status.
- **"Paper & Clay" client restyle** — the desktop visual language moves off the
  warm orange ramp to a calm, neutral canvas carried by a single clay accent
  (the restrained, single-accent direction of Claude / ChatGPT / Codex):
  theme-adaptive surfaces, clean system-sans typography, flattened shadows and
  hairline borders. Routed entirely through the design tokens, so every view
  restyles at once.
- **Four orthogonal dimensions** — `MemoryEntry` gains `aim` (why — relevance
  gate), `use` (how — processing mode + usage ledger), and `trigger` (when —
  weighted time-axis scheduler) alongside its content. Serialization is
  versioned (`_v=2`) and fully backward-compatible; v1 records load unchanged.
- **Activation scoring** — recall/eviction can rank by
  `trigger.weight × decayed importance × aim.align × (1 + use.utility)` behind
  the `FOURD_MEMORY_ENABLED` flag (default off → behaviour identical to before).
- **Pull engine** — `WP4.activate(query)` closes the feedback loop: recall hits
  are written back to their `use` ledger, so repeatedly useful memories rank
  higher and survive eviction longer.
- **Push engine & turn auto-injection** — behind `FOURD_PUSH_ON_TURN`,
  `CONSTRAIN`/`REMIND` memories fire query-lessly at the start of every turn
  and are appended to the WP2/WP3 system prompts as an "active constraints /
  reminders" block; `Autumn.active_context()` exposes the same seam manually.
  Push does not reinforce by default — auto-surfacing is not deliberate use.
- **4D producer side** — the activation engine finally has something to score:
  `MemoryArea.annotate()` merges dimensions onto an entry (preserving its usage
  ledger), `WP4.annotate_recent()` runs A4 to infer them in bulk, the
  `annotate_memory` skill lets an agent declare them, and consolidation digests
  are auto-tagged `SUMMARIZE`. Endpoints: `POST /memory/{area}/annotate` and
  `/auto-annotate`.
- **Governed Mom1 access** — `Mom2`/`Mom3` keep their default isolation but gain
  a gated upward channel: A1 adjudicates a requested `Mom1` read (narrowed scope
  + redaction), A4 mediates a restricted answer, and WP4 audits every decision.
  Surfaced as the `request_mom1_access` skill and `GET /memory/audit/access_log`;
  kill-switch `MOM1_ACCESS_ENABLED=false`.
- **4D observability** — `GET /memory/4d/status` and `POST /memory/push/preview`
  make the engine inspectable (the preview dry-runs push without reinforcing);
  the macOS Memory view adds 4D status badges, one-tap auto-annotate, per-entry
  annotation controls, a push-preview mode, and a Mom1 access-audit panel.
- **Runtime 4D control** — `Autumn.configure_4d()` / `POST /memory/4d/config`
  flip 4D ranking, turn-push and the Mom1 channel without an env edit or
  restart (the ranking toggle propagates to every zone, cached project zones
  included); the macOS Settings → 记忆 tab exposes the three switches live.
- **Trace & pipeline strip** — fired pushes surface as a `wp4.push` stage in
  the workflow trace; the pipeline strip gains a purple 4D brain chip, and the
  collapsed trace summary leads with "4D 推入" whenever the engine fired.
- **Memory browser redesign (macOS client)** — the Memory view is rebuilt
  around the 4D system: use-mode filter chips (constrain / remind / context /
  summarize, with live counts — shown only when the area has annotated
  entries), newest-first ordering, pinned / relative-time / tag / importance
  indicators per entry, a 4D annotated-count stat, and a dedicated 四维 card
  rendering `aim.scope` and `trigger.cues` as wrapping chips. A new
  `Autumn.colors.memory` design token unifies the 4D identity across views,
  and v2-serialized records now resolve their titles correctly (the
  schema-default `use.mode=context` no longer badges every row).
- **Reliability & code-quality pass** — packaging metadata corrected to the
  actually-supported dependencies (`pydantic>=2,<3`, FastAPI upper bound
  removed); the server migrated off removed Pydantic v1 APIs
  (`.dict()`/`.json()` → `model_dump…`); vector-store table names are
  validated against SQL injection; tool-call/result pairing uses
  `zip(strict=True)`; the SQLite backend uses `asyncio.get_running_loop()`;
  plus a module-wide ruff style/import sweep (~130 fixes).
- Full design rationale and phasing in
  [`docs/rfc-4d-memory.md`](docs/rfc-4d-memory.md).

### 0.2.1 — Performance, new built-in domains & expanded MCP catalog

- **Concurrent agent tool dispatch** — the ReAct loop now runs all tool calls
  in a turn concurrently via `asyncio.gather`; independent tools no longer pay
  the sum of their latencies.
- **Memory performance** — vector search uses `heapq.nlargest` (O(N log k));
  query norm computed once per search; SQLite backend caches one connection per
  thread + `synchronous=NORMAL`; embedding API adds a 512-entry LRU cache.
- **New always-safe Terrs** — `encoding` (base64, hex, URL codecs, hashing,
  UUID — 8 tools) and `collection` (unique, flatten, chunk, frequencies,
  group_by, sort_records — 6 tools); both added to `SAFE_TERR_FACTORIES`.
- **Expanded MCP catalog** — 7 new factories: `mcp_postgres`, `mcp_slack`,
  `mcp_gitlab`, `mcp_google_maps`, `mcp_sequential_thinking`, `mcp_time`,
  `mcp_everything`.
- **Server opt-in** — `AUTUMN_BUILTIN_TERRS=safe|all` registers shipped domains
  on startup and via `/config/apply` (default off).
- **Desktop client** — error messages from the server surface inline in
  Settings; cost totals show in trace and inspector views; `AutumnChip`
  component unifies route pills and status chips; `Autumn.format` / `Autumn.colors`
  tokens eliminate duplicated formatting helpers.

### 0.2.0 — Memory system & project intelligence

- **WP4 memory-management workspace** — the optional A4 model gains its own
  workspace dedicated to curating *every* memory zone (recall synthesis,
  consolidation, forget, pin, stats), addressing each zone by name and keeping
  its own audit log. Exposed over HTTP via `GET /memory/stats` and the
  `/memory/{area}/…` endpoints.
- **Project metadata** — each project now carries a structured **type**,
  **description**, **goals** (one master + long-term + short-term), tracked
  **files**, and an AI-inferred **environment** (terrs, skills, tools, MCP, agent
  channel). WP4 drafts descriptions and goals and infers environments through
  A4; managed over HTTP under `/projects/{id}/metadata|files|describe|goals|infer-environment`.
- **Per-project shared memory** — every project id gets an isolated zone that is
  *shared* across all workspaces and turns within that project.
- **Memory lifecycle** — importance & pinning, TTL/expiry, time-decay,
  A4-powered consolidation, bulk `forget`, and `stats` across every zone.
- **Memory module redesign** — `MemoryEntry`, importance-weighted eviction, and
  unified recall (exact key → tags → semantic).
- **Built-in capability domains (Terrs)** — ready-made `time`, `math`, `text`,
  `data`, `web`, `fs`, and `memory` Terrs, plus an MCP catalog of common servers.
- **A4 local model automation** — in-app Ollama deploy and one-click A4 config.
- **Cost & tuning** — per-turn USD cost tracking and a tunable `BehaviorConfig`.
- **Web deployment** — Cloudflare (Container + Worker + React SPA) and Hugging
  Face Spaces single-container targets.

### 0.1.0 — Multi-model collaborative core

- Three-model workflow: A1/A2/A3 governing WP1/WP2/WP3 over layered memory
  (Mom1/2/3), with a strict routing protocol and a checker per workspace.
- Multi-level selector routing with task sub-classification.
- Real-time streaming with a post-hoc advisory checker.
- Plugin system: skills, tools, ReAct agents (Hermes loop), and MCP clients.
- Terr (域) capability-domain abstraction with enable/disable controls.
- SwiftUI macOS desktop client with a live workflow trace.

## License

MIT.

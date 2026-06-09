# 秋 / Autumn

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

| Terr     | Safety       | Tools / skills                                                |
| -------- | ------------ | ------------------------------------------------------------- |
| `time`   | always safe  | `now`, `parse_time`, `time_diff`, `time_add`, `time_today`    |
| `math`   | always safe  | `calc` (AST-whitelisted), `stats`                             |
| `text`   | always safe  | `count_text`, `regex_find`, `extract_urls`, `split`, `replace`|
| `data`   | always safe  | `parse_json`, `to_json`, `parse_csv`, `to_csv`, `json_path`   |
| `web`    | opt-in (net) | `http_get`, `http_get_json`, `http_head`, `fetch_text`        |
| `fs`     | sandboxed    | `read_file`, `write_file`, `list_dir`, `file_info`, `delete_file` |
| `memory` | bound to area | `recall`, `remember` (re-export of memory skills)           |

```python
from autumn import time_terr, math_terr, register_safe_builtins, register_builtins

# Pick what you need
autumn.register_terr(time_terr())
autumn.register_terr(math_terr())

# Or wire up the safe set in one call
register_safe_builtins(autumn)               # time + math + text + data

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
servers most commonly used by agents: `mcp_filesystem`, `mcp_fetch`,
`mcp_git`, `mcp_sqlite`, `mcp_brave_search`, `mcp_github`, `mcp_puppeteer`,
`mcp_memory`. Each returns an unconnected `StdioMCPClient`; pass it into a
`Terr(mcps=[...])` and `await autumn.add_terr(...)` to connect and register.

## Plugins

```python
from autumn import Tool, ToolParameter, Agent, StdioMCPClient

# Custom tool
tool = Tool("search", "Web search", search_fn, [ToolParameter("q", "string", "query")])
autumn.register_tool(tool)

# Agent with ReAct loop
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
│   ├── memory/       # Mom1/2/3, SharedZone, ProjectMemory, backends (Dict/SQLite/Hybrid)
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

## License

MIT.

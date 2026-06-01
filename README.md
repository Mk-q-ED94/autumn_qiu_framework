# 秋 / Autumn

A multi-model collaborative workflow framework. Three model API interfaces (A1, A2, A3) each govern a workspace (WP1, WP2, WP3) backed by a memory area (Mom1, Mom2, Mom3), coordinated by a strict routing protocol to produce results that exceed what any single model can achieve alone.

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

## Quick start

```python
import asyncio
from autumn import Autumn, AutumnConfig, ModelConfig, Protocol

config = AutumnConfig(
    a1=ModelConfig(api_key="...", base_url="https://api.openai.com",
                   model="gpt-4o-mini", protocol=Protocol.OPENAI),
    a2=ModelConfig(api_key="...", base_url="https://api.anthropic.com",
                   model="claude-sonnet-4-5", protocol=Protocol.ANTHROPIC),
    a3=ModelConfig(api_key="...", base_url="https://api.openai.com",
                   model="gpt-4o", protocol=Protocol.OPENAI),
)

async def main():
    async with Autumn(config) as autumn:
        result = await autumn.process("帮我写一个周末旅行清单")
        print(result)

asyncio.run(main())
```

## Streaming

```python
async for chunk in autumn.stream("写一首关于秋天的诗"):
    print(chunk, end="", flush=True)
```

## Interactive mode

```python
from autumn import CLIInteraction

async with Autumn(config, interaction=CLIInteraction()) as autumn:
    await autumn.process("...")  # confirms low-confidence classifications, asks mission route
```

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
│   ├── api/          # ModelAPIInterface, A1/A2/A3
│   ├── memory/       # Mom1/2/3, SharedZone, backends (Dict/SQLite/Hybrid)
│   ├── workspace/    # WP1Tot, WP2Tas, WP3Mis
│   ├── components/   # Agent, Skill, Tool, Selector, Checker, MCP*
│   ├── config.py     # AutumnConfig, ModelConfig, WorkspacePrompts
│   ├── interaction.py# UserInteraction, CLIInteraction
│   └── framework.py  # Autumn (entry point)
└── plugins/loader.py # PluginLoader
```

## Development

```bash
pip install -e ".[dev]"
python -m pytest
```

## License

MIT.

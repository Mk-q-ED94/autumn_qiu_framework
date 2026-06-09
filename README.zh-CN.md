<p align="center">
  <img src="./assets/banner.png" alt="秋 / Autumn — 多模型协同工作流框架" width="100%">
</p>

<p align="center"><a href="./README.md">English</a> | <strong>简体中文</strong></p>

一个多模型协同工作流框架。三个模型 API 接口（A1、A2、A3）各自掌管一个工作区（WP1、WP2、WP3），并各自背靠一块记忆区（Mom1、Mom2、Mom3），通过一套严格的路由协议彼此协调，从而产出超越任何单一模型独立所能达到的结果。第四个可选模型（A4）驱动 **WP4**——专职的记忆管理工作区，统一管理所有记忆区。

## 架构

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

- **WP1 Tot**：入口工作区。`selector`（选择器）对用户输入分类，分流到 `task`（任务）或 `mission`（使命）。
- **WP2 Tas / WP3 Mis**：分别处理任务与使命，共享一块公共区。
- **WP4 Mem**：由 A4 驱动，凌驾于对话流之上，统管所有记忆区。

**路由管线**（所有路径在抵达用户前都以 WP1.checker 收尾）：

| 路径                    | 流程                                                             |
| ---------------------- | --------------------------------------------------------------- |
| `task`（任务）          | WP2 → wp2.check → wp1.check                                     |
| `mission` → direct（直答） | WP3 → wp1.check                                              |
| `mission` → convert（转化） | WP3 → wp3.check → wp1.check → WP2 → wp2.check → wp1.check    |

**记忆访问**（由组合关系强制约束）：

- `Mom1` 可以读取 `Mom2` 和 `Mom3`。
- `Mom2` 和 `Mom3` 共享一块公共区，但都无法读取 `Mom1`。
- 每一层都有两级：内存中的短期缓存 + 持久化的 SQLite。

**按项目隔离的共享记忆**——每个项目 id 拥有自己独立的记忆命名空间，但在同一个项目*内部*，这块区是跨所有工作区、所有轮次**共享**的：

```python
autumn.add_memory_skills("project")        # recall/remember 绑定到当前激活的项目
with autumn.project_scope("acme-app"):     # 为这个代码块设定当前项目
    await autumn.process("记住部署目标是 fly.io")
# 另一个项目看不到 acme-app 的任何记忆：
await autumn.project_zone("acme-app").get("...")   # 独立命名空间
```

通过 HTTP，在 `/process`、`/trace`、`/stream` 传入 `project_id`；用 `GET /projects`、`GET /projects/{id}/memory`、`DELETE /projects/{id}` 来管理这些区。

### 项目元数据

每个项目除了记忆，还携带一组结构化元数据，存放在该项目区内的保留键下，按项目隔离、跨重启持久化：

- **项目类型** —— 类别标签（`code`、`research` 等），也可不设保持默认。
- **项目简介** —— 自由文本；可直接填写，也可在专门对话中与 A4 讨论后由 AI 生成。
- **项目目标** —— 一个总目标 + 多个长期目标 + 多个短期目标；可直接填写或由 A4 结构化生成。
- **项目文件** —— 用户手动添加的文件，以及项目对话中产生的文件。
- **项目环境** —— 由 A4 根据类型 / 简介 / 总目标推断出合适的 terr 域、skill、tool、MCP 以及项目专属 agent 通道。

```python
# 数据层
meta = await autumn.projects.get_metadata("acme-app")
await autumn.projects.update_metadata("acme-app", project_type="code",
                                      description="一个 REST API 服务")

# A4 驱动的智能（由 WP4 提供）
desc  = await autumn.wp4.draft_description("我想做一个能快速搭建智能体的框架", "acme-app")
goals = await autumn.wp4.draft_goals("先上线 v1，再做规模化和国际化", "acme-app")
meta  = await autumn.wp4.infer_environment("acme-app")   # 推断并写回项目环境
```

通过 HTTP 在 `/projects/{id}/` 下管理：`GET/PATCH metadata`、`POST/DELETE files`、`POST describe`、`POST goals`、`POST infer-environment`（后三者需要 A4）。

**记忆生命周期**——每一块区（Mom1/2/3、共享区、项目区）都支持：

- **重要度与置顶** —— `append_history(..., importance=2.0)` 会置顶一条条目；置顶条目永不被淘汰。淘汰时优先丢弃重要度最低的条目。
- **TTL / 过期** —— `append_history(..., ttl=3600)` 让条目变为临时；过期条目读取时被过滤，下次写入时被清除。
- **时间衰减** —— 设置 `MEMORY_DECAY_HALF_LIFE`（秒），让陈旧的低价值记忆逐渐淡出，先于新记忆被淘汰。
- **归并（Consolidation）** —— `await zone.consolidate(api)` 把旧条目汇总成一条置顶摘要（使用 A4 模型）；HTTP：`POST /memory/{area}/consolidate`。
- **遗忘与统计** —— `zone.forget(tags=..., before=..., expired=True)` 批量清理；`zone.stats()` / `GET /memory/{area}/stats` 报告数量、标签和时间跨度。

**WP4 —— 记忆管理工作区**——A4 拥有自己专属的工作区，唯一职责就是统管*所有*记忆。WP1–WP3 各自掌管一块 Mom 区并驱动对话；WP4 不参与对话流，而是按名字寻址每一块区（`mom1`/`mom2`/`mom3`/`shared`/`project`）。A4 负责认知性工作（回忆合成、归并摘要）；机械性工作（遗忘、统计、置顶）则直接委托给目标区。WP4 维护自己的审计日志，因此它执行的每一个管理动作本身也会被记录、可观测。

```python
autumn.add_memory_skills("shared")          # recall/remember 技能，由 WP4 构建

await autumn.wp4.remember("deploy", "fly.io")          # 写入某块区
await autumn.wp4.recall("deploy")                       # 统一检索
await autumn.wp4.consolidate("mom2")                    # 通过 A4 汇总
await autumn.wp4.forget("shared", tags=["scratch"])     # 批量清理
await autumn.wp4.stats()                                # 所有区的快照
```

通过 HTTP，记忆相关端点都经由 WP4：`GET /memory/stats` 返回所有区的总览；`shared` 与 `mom1/2/3` 一样成为 `/memory/{area}/history|stats|consolidate` 可寻址的区。归并使用 WP4 的 A4 槽位，因此在未配置 A4 模型时会干净地返回 400。

## 快速开始

```bash
cp .env.example .env       # 填入 A1/A2/A3 的密钥
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

更想用代码构建配置？直接用 `ModelConfig`：

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

## 流式输出

```python
async for chunk in autumn.stream("写一首关于秋天的诗"):
    print(chunk, end="", flush=True)
```

当你既需要实时分块、又需要最终的追踪信息（token 用量、各阶段耗时、agent 工具调用）时，用 `stream_with_trace`——字符串照常流式输出，最后再到达一个 `WorkflowRun`：

```python
from autumn import WorkflowRun

async for event in autumn.stream_with_trace("写一首关于秋天的诗"):
    if isinstance(event, str):
        print(event, end="", flush=True)
    elif isinstance(event, WorkflowRun):
        for stage in event.stages:
            print(f"\n[{stage.id}] {stage.duration_ms:.0f}ms")
```

默认情况下，流式会先跑完整套已验证管线再分块——在 `AutumnConfig` 里设 `validate_before_stream=False`（或在环境变量设 `VALIDATE_BEFORE_STREAM=false`），即可开启实时 token 流式 + 事后顾问式检查。

当你不想用配置好的 `HEADLESS_MISSION_ROUTE` 时，可以针对单次调用覆盖使命路由：

```python
from autumn import MissionRoute

result = await autumn.process(
    "把这个产品想法整理成执行计划",
    mission_route=MissionRoute.CONVERT,
)
```

## 记忆技能

`Autumn.add_memory_skills(area)` 会注册两个技能——`recall(query)` 和 `remember(text)`——任何会用工具的 agent（包括 WP2）都能调用它们来查询或写入某块记忆区。用可选的 A4 模型槽位即可低成本地驱动合成（例如一个本地 Ollama 模型）：

```python
from autumn import AutumnConfig, ModelConfig, Protocol

config = AutumnConfig(
    a1=..., a2=..., a3=...,
    a4=ModelConfig(api_key="ollama", base_url="http://localhost:11434",
                   model="llama3.1:8b", protocol=Protocol.OPENAI),
)
async with Autumn(config) as autumn:
    autumn.add_memory_skills("shared")  # 或 "mom1" / "mom2" / "mom3" / "project"
    await autumn.process("回忆一下我上周让你研究的事情")
```

## 交互模式

```python
from autumn import CLIInteraction

async with Autumn(config, interaction=CLIInteraction()) as autumn:
    await autumn.process("...")  # 低置信度分类时确认，并询问使命路由
```

## 内置能力域（Terr）

`autumn.builtin` 自带一批开箱即用的 Terr 工厂，覆盖每个 agent 最终都会用到的杂活——报时、做算术、解析 JSON、抓取 URL、读取沙箱文件。它们通过与桌面 UI 相同的启用/禁用开关注册。

| Terr     | 安全性        | 工具 / 技能                                                    |
| -------- | ------------ | ------------------------------------------------------------- |
| `time`   | 始终安全      | `now`、`parse_time`、`time_diff`、`time_add`、`time_today`     |
| `math`   | 始终安全      | `calc`（AST 白名单）、`stats`                                  |
| `text`   | 始终安全      | `count_text`、`regex_find`、`extract_urls`、`split`、`replace`|
| `data`   | 始终安全      | `parse_json`、`to_json`、`parse_csv`、`to_csv`、`json_path`    |
| `web`    | 需开启（联网）| `http_get`、`http_get_json`、`http_head`、`fetch_text`         |
| `fs`     | 沙箱限制      | `read_file`、`write_file`、`list_dir`、`file_info`、`delete_file` |
| `memory` | 绑定到某区    | `recall`、`remember`（记忆技能的再导出）                       |

```python
from autumn import time_terr, math_terr, register_safe_builtins, register_builtins

# 按需挑选
autumn.register_terr(time_terr())
autumn.register_terr(math_terr())

# 或一次性接入安全集
register_safe_builtins(autumn)               # time + math + text + data

# 选择性接入 联网 + 文件系统 + 记忆
register_builtins(
    autumn,
    include_web=True,
    fs_root="/tmp/agent-ws",
    include_memory=True,
    memory_area="shared",
)
```

`autumn.builtin.mcp_catalog` 为 agent 最常用的官方 MCP 服务器提供了工厂函数：`mcp_filesystem`、`mcp_fetch`、`mcp_git`、`mcp_sqlite`、`mcp_brave_search`、`mcp_github`、`mcp_puppeteer`、`mcp_memory`。每个都返回一个未连接的 `StdioMCPClient`；把它传入 `Terr(mcps=[...])` 再 `await autumn.add_terr(...)` 即可连接并注册。

## 插件

```python
from autumn import Tool, ToolParameter, Agent, StdioMCPClient

# 自定义工具
tool = Tool("search", "Web search", search_fn, [ToolParameter("q", "string", "query")])
autumn.register_tool(tool)

# 带 ReAct 循环的 agent
agent = Agent("researcher", api=autumn.a2, tools=[tool])
result = await agent.run("Find recent papers on retrieval-augmented generation")

# MCP 服务器——它的所有工具自动注册
client = StdioMCPClient(["python", "-m", "my_mcp_server"])
mcp_tools = await autumn.add_mcp(client)

# 基于目录的热加载
Autumn(config, plugin_dirs=["./my_plugins"])
```

## 配置

```python
from autumn import AutumnConfig, WorkspacePrompts, StorageConfig, MissionRoute

AutumnConfig(
    a1=..., a2=..., a3=...,
    prompts=WorkspacePrompts(
        wp2_task="You are a meticulous task executor...",
        wp3_convert="Convert this mission into bullet steps...",
        # 七个槽位中的任意一个都可被覆盖。
    ),
    storage=StorageConfig(db_path="my_app_memory.db"),
    headless_mission_route="auto",   # 或 MissionRoute.DIRECT / MissionRoute.CONVERT
)
```

## 组件参考

| 组件             | 职责                                                            |
| ---------------- | --------------------------------------------------------------- |
| `Autumn`         | 入口；从配置装配一切                                             |
| `WP1Tot`         | 编排路由与最终校验                                              |
| `WP2Tas`         | 通过 A2 执行结构化任务                                          |
| `WP3Mis`         | 处理使命：直接作答或转化为任务                                   |
| `WP4Mem`         | 记忆管理工作区；A4 驱动的全区记忆管家                            |
| `Selector`       | 对输入分类；不确定时触发用户确认                                 |
| `Checker`        | 各工作区的输出校验器（规则 + 模型评估，最多重试 3 次）           |
| `Agent`          | 带 ReAct 工具调用循环的自主执行器                               |
| `Tool`           | 通过工具调用 API 暴露给模型的可调用对象                          |
| `Skill`          | 具名、可复用的能力                                              |
| `MCPClient`      | Model Context Protocol 客户端（自带 `StdioMCPClient`）          |
| `Mom1/2/3`       | 分层记忆；支持持久化 + 会话级存储                               |
| `PluginLoader`   | 从目录发现插件，或接受手动注册                                   |

## 目录结构

```
autumn/
├── core/
│   ├── api/          # ModelAPIInterface, A1/A2/A3/A4
│   ├── memory/       # Mom1/2/3, SharedZone, ProjectMemory, 后端 (Dict/SQLite/Hybrid)
│   ├── workspace/    # WP1Tot, WP2Tas, WP3Mis, WP4Mem
│   ├── components/   # Agent, Skill, Tool, Selector, Checker, MCP*
│   ├── config.py     # AutumnConfig, ModelConfig, WorkspacePrompts
│   ├── interaction.py# UserInteraction, CLIInteraction
│   └── framework.py  # Autumn（入口）
└── plugins/loader.py # PluginLoader
```

## HTTP 服务与桌面客户端

一个 FastAPI 桥接层把框架以 HTTP/SSE 暴露出来，任何客户端都能驱动它。`desktop/` 下的 SwiftUI macOS 应用是参考客户端。当它的服务器 URL 指向 localhost 且没有现成服务器响应时，它会用 `python -m autumn.server` 自动启动本地桥接。

```bash
pip install -e ".[server]"
python -m autumn.server            # 监听 127.0.0.1:8765

curl -X POST http://127.0.0.1:8765/models \
  -H 'Content-Type: application/json' \
  -d '{"api_key":"sk-...","base_url":"https://api.openai.com","protocol":"openai"}'

curl -X POST http://127.0.0.1:8765/process \
  -H 'Content-Type: application/json' \
  -d '{"input":"把这个想法变成任务清单","route":"convert"}'

curl -N 'http://127.0.0.1:8765/stream?input=写一段欢迎语&route=direct'

# 构建并打开桌面应用（macOS 上需要 Xcode + XcodeGen）：
bash ./script/build_and_run.sh
```

`/stream` 会把 `{"chunk": "..."}` 事件与最后一个 `{"trace": {...}}` 交织在一起，后者的结构与 `/trace` 相同。每个端点（`/process`、`/trace`、`/intent`、`/stream`）都接受一个可选的 `project_instructions` 字段，服务器会把它作为项目级前言拼接到用户输入之前——完整的端点参考与工作流见 [`desktop/README.md`](desktop/README.md)。

## 开发

```bash
pip install -e ".[dev]"
python -m pytest
```

## 开发历程

当前版本：**0.2.0**。Autumn 遵循语义化版本；在 `0.x` 阶段，次版本号的提升代表新增功能，且可能调整 API。

### 0.2.0 —— 记忆系统与项目智能

- **WP4 记忆管理工作区** —— 可选的 A4 模型获得了专属工作区，唯一职责是统管*每一块*记忆区（回忆合成、归并、遗忘、置顶、统计），按名字寻址，并维护自己的审计日志。通过 `GET /memory/stats` 及 `/memory/{area}/…` 系列端点暴露。
- **项目元数据** —— 每个项目现在携带结构化的**类型**、**简介**、**目标**（一个总目标 + 长期 + 短期）、**文件**清单，以及由 AI 推断的**环境**（terr、skill、tool、MCP、agent 通道）。WP4 通过 A4 起草简介与目标、推断环境；通过 `/projects/{id}/metadata|files|describe|goals|infer-environment` 管理。
- **按项目隔离的共享记忆** —— 每个项目 id 获得一块独立的区，但在该项目内部跨所有工作区与轮次*共享*。
- **记忆生命周期** —— 重要度与置顶、TTL/过期、时间衰减、A4 驱动的归并、批量 `forget`、跨所有区的 `stats`。
- **记忆模块重构** —— `MemoryEntry`、重要度加权淘汰、统一回忆（精确键 → 标签 → 语义）。
- **内置能力域（Terr）** —— 开箱即用的 `time`、`math`、`text`、`data`、`web`、`fs`、`memory` 域，外加常用 MCP 服务器目录。
- **A4 本地模型自动化** —— 应用内 Ollama 部署 + 一键配置 A4。
- **成本与调优** —— 每轮 USD 成本追踪，以及可调的 `BehaviorConfig`。
- **Web 部署** —— Cloudflare（Container + Worker + React SPA）与 Hugging Face Spaces 单容器目标。

### 0.1.0 —— 多模型协同内核

- 三模型工作流：A1/A2/A3 掌管 WP1/WP2/WP3，背靠分层记忆（Mom1/2/3），由严格的路由协议与每个工作区的 checker 协调。
- 多级选择器路由，带任务子分类。
- 实时流式输出，配事后顾问式 checker。
- 插件系统：skill、tool、ReAct agent（Hermes 循环）、MCP 客户端。
- Terr（域）能力域抽象，带启用/禁用控制。
- SwiftUI macOS 桌面客户端，带实时工作流追踪。

## 许可证

MIT。

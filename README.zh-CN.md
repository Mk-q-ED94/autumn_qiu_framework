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

**受治理的上行通道**——默认隔离是非对称的，但留有一条*受闸*的路径，让下层不至于被永久隔死：`Mom2`/`Mom3` 可以**申请**读取 `Mom1`，由 `A1` 裁决（批准/拒绝 + 收窄范围 + 脱敏），`A4` 调解出一个受限答案，`WP4` 全程审计。它以 `request_mom1_access` 技能的形式暴露给 agent 的 ReAct 循环；每一次裁决——无论批准还是拒绝——都会写入访问审计日志（`GET /memory/audit/access_log`）。一键关闭：`MOM1_ACCESS_ENABLED=false` 会在不咨询 `A1` 的情况下拒绝每一个请求。

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

**四维记忆（活性记忆）**——每条记忆在内容之外，还可选地携带另外三个正交维度，从被动记录升级为带有自身激活策略的单元（完整设计见 [`docs/rfc-4d-memory.md`](docs/rfc-4d-memory.md)）：

| 维度 | 回答的问题 | 角色 |
| ---- | ---------- | ---- |
| `aim`     | 这条记忆**为什么**存在 | 关联门——与当前轮的目标/线索不对齐时直接否决激活 |
| content   | 这条记忆**是什么**     | 载荷（即原有的条目正文） |
| `use`     | 该**怎么用**、用得如何 | 处理模式（`CONTEXT`/`REMIND`/`CONSTRAIN`/`SUMMARIZE`）+ 使用账本 |
| `trigger` | **何时**该触发         | 调度器——半衰期、生效/失效时间、冷却间隔、线索匹配 |

```python
from autumn.core.memory import Aim, Use, UseMode, Trigger

await autumn.mom1.append_history(
    "永远不要直接写生产数据库",
    use=Use(mode=UseMode.CONSTRAIN),                    # 怎么用：作为硬性规则注入
    aim=Aim(intent="部署安全", scope=["deploy"]),        # 为什么：按目标对齐做门禁
    trigger=Trigger(cues=["deploy", "release"]),        # 何时：线索命中时加权触发
)
```

回忆按 `activation = trigger.weight ×（importance × 衰减）× aim.align × (1 + use.utility)` 排序。淘汰则**刻意**不看 `aim`/`trigger`，只保留被证明有用的条目（`retention = 有效重要度 × (1 + utility)`）——高价值但暂时休眠的记忆不会仅仅因为不在当前上下文就被淘汰。

两个开关，**默认全关**——关闭时行为与经典的重要度×新近度模型完全一致，v1 旧记录也能原样加载（序列化带版本号 `_v=2`）：

- `FOURD_MEMORY_ENABLED`（`BehaviorConfig.fourd_memory_enabled`）——回忆与淘汰切换到四维激活打分。
- `FOURD_PUSH_ON_TURN`（`BehaviorConfig.fourd_push_on_turn`）——**push 激活**：每个 `process`/`stream` 轮次开始时，trigger/aim 闸门对当前轮打开的 `CONSTRAIN`/`REMIND` 记忆自动触发，以「活跃约束 / 提醒」块的形式追加到 WP2/WP3 的 system prompt；工作流追踪新增一个 `wp4.push` 阶段（桌面客户端中显示为 WP4 紫色），展示本轮触发了哪些记忆。

```python
# pull：检索 + use 账本回写，反复有用的记忆排名越来越靠前
hits = await autumn.wp4.activate("部署目标", area="shared")

# push 的手动接缝（开关关闭或无命中时返回 ""）
frag = await autumn.active_context(text="现在部署 v2")
```

**生产标注**——激活引擎只有在记忆真正带上维度后才能区分；未标注的数据打分与「重要度×新近度」完全一致。三种投喂方式：

- **A4 推断**——`await autumn.wp4.annotate_recent("mom1")` 扫描未标注条目，让 A4 把每条归类为「使用模式 + 目的 + 触发线索」。HTTP：`POST /memory/{area}/auto-annotate`。
- **Agent 声明**——`annotate_memory` 技能让 WP2/WP3 的 agent 给它刚存的条目打标（「这是一条约束」「部署时提醒」）。
- **用户 / UI**——`POST /memory/{area}/annotate` 给单条记忆设置维度（代码中为 `MemoryArea.annotate()`）；归并产生的摘要会自动标记为 `SUMMARIZE`。

**可观测性**——`GET /memory/4d/status` 报告排序/推送到底有没有启用（相对于休眠的默认态），`POST /memory/push/preview` 在*不回写账本*的前提下对一个假设轮次干跑 push 引擎，返回命中的记忆、它们的激活分数，以及会被注入的确切提示词片段。macOS 记忆视图把这些全部呈现：4D 状态徽章、一键自动标注、每条记忆的标注控件、推送预览模式，以及一个 Mom1 访问审计面板。

**运行时控制**——上述三个开关通常由环境变量设定，但 `autumn.configure_4d(memory_enabled=…, push_on_turn=…, mom1_access_enabled=…)` 可以实时切换（排序开关会传播到每个记忆区，包括已缓存的项目区）。HTTP：`POST /memory/4d/config`；macOS 客户端：**设置 → 记忆 → 4D 记忆引擎**。改动立即生效，重启后回到 `.env` 默认值。

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

| Terr         | 安全性        | 工具 / 技能                                                                          |
| ------------ | ------------ | ----------------------------------------------------------------------------------- |
| `time`       | 始终安全      | `now`、`parse_time`、`time_diff`、`time_add`、`time_today`                           |
| `math`       | 始终安全      | `calc`（AST 白名单）、`stats`                                                        |
| `text`       | 始终安全      | `count_text`、`regex_find`、`extract_urls`、`split_text`、`replace_text`             |
| `data`       | 始终安全      | `parse_json`、`to_json`、`parse_csv`、`to_csv`、`json_path`                          |
| `encoding`   | 始终安全      | `base64_encode/decode`、`hex_encode/decode`、`hash_text`、`url_encode/decode`、`uuid_generate` |
| `collection` | 始终安全      | `unique`、`flatten`、`chunk`、`frequencies`、`group_by`、`sort_records`              |
| `web`        | 需开启（联网）| `http_get`、`http_get_json`、`http_head`、`fetch_text`                               |
| `fs`         | 沙箱限制      | `read_file`、`write_file`、`list_dir`、`file_info`、`delete_file`                    |
| `memory`     | 绑定到某区    | `recall`、`remember`、`list_recent`、`pin_memory`                                    |

```python
from autumn import time_terr, math_terr, register_safe_builtins, register_builtins

# 按需挑选
autumn.register_terr(time_terr())
autumn.register_terr(math_terr())

# 或一次性接入安全集
register_safe_builtins(autumn)               # time + math + text + data + encoding + collection

# 选择性接入 联网 + 文件系统 + 记忆
register_builtins(
    autumn,
    include_web=True,
    fs_root="/tmp/agent-ws",
    include_memory=True,
    memory_area="shared",
)
```

`autumn.builtin.mcp_catalog` 为 agent 最常用的官方 MCP 服务器提供了工厂函数：

| 工厂函数                      | 服务器                                  | 所需凭据              |
| ----------------------------- | --------------------------------------- | -------------------- |
| `mcp_filesystem(root)`        | `@modelcontextprotocol/server-filesystem` | —                  |
| `mcp_fetch()`                 | `mcp-server-fetch`                      | —                    |
| `mcp_git(repo)`               | `mcp-server-git`                        | —                    |
| `mcp_sqlite(db_path)`         | `mcp-server-sqlite`                     | —                    |
| `mcp_brave_search(key)`       | `server-brave-search`                   | Brave Search API Key |
| `mcp_github(token)`           | `server-github`                         | GitHub PAT           |
| `mcp_puppeteer()`             | `server-puppeteer`                      | —                    |
| `mcp_memory()`                | `server-memory`                         | —                    |
| `mcp_postgres(conn_str)`      | `server-postgres`                       | 数据库连接字符串      |
| `mcp_slack(token, team)`      | `server-slack`                          | Slack Bot Token + Team ID |
| `mcp_gitlab(token)`           | `server-gitlab`                         | GitLab PAT           |
| `mcp_google_maps(key)`        | `server-google-maps`                    | Google Maps API Key  |
| `mcp_sequential_thinking()`   | `server-sequential-thinking`            | —                    |
| `mcp_time()`                  | `mcp-server-time`                       | —                    |
| `mcp_everything()`            | `server-everything`（参考/测试用）      | —                    |

每个工厂函数都返回一个未连接的 `StdioMCPClient`；把它传入 `Terr(mcps=[...])` 再 `await autumn.add_terr(...)` 即可连接并注册。

**服务端按需启用**：设置 `AUTUMN_BUILTIN_TERRS=safe` 可在服务器启动时自动注册所有始终安全的域（默认关闭）；设 `AUTUMN_BUILTIN_TERRS=all` 同时启用 `web` 域。

## 插件

```python
from autumn import Tool, ToolParameter, Agent, StdioMCPClient

# 自定义工具
tool = Tool("search", "Web search", search_fn, [ToolParameter("q", "string", "query")])
autumn.register_tool(tool)

# 带 ReAct 循环的 agent —— 每轮工具调用通过 asyncio.gather 并发执行
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
│   ├── memory/       # Mom1/2/3, SharedZone, ProjectMemory, dimensions（四维）, 后端 (Dict/SQLite/Hybrid)
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

当前版本：**0.2.1**。Autumn 遵循语义化版本；在 `0.x` 阶段，次版本号的提升代表新增功能，且可能调整 API。

### 未发布 —— 四维记忆（活性记忆）、客户端重设计与质量梳理

- **四个正交维度** —— `MemoryEntry` 在内容之外新增 `aim`（为什么——关联门）、`use`（怎么用——处理模式 + 使用账本）、`trigger`（何时——带权时间轴调度器）。序列化带版本号（`_v=2`）且完全向后兼容；v1 旧记录原样加载。
- **激活打分** —— 回忆/淘汰可按 `trigger.weight × 衰减后重要度 × aim.align × (1 + use.utility)` 排序，由 `FOURD_MEMORY_ENABLED` 开关守护（默认关闭 → 行为与之前完全一致）。
- **pull 引擎** —— `WP4.activate(query)` 闭合反馈环：检索命中会回写各自的 `use` 账本，反复有用的记忆排名更靠前、更晚被淘汰。
- **push 引擎与每轮自动注入** —— 在 `FOURD_PUSH_ON_TURN` 开关下，`CONSTRAIN`/`REMIND` 记忆在每轮开始时无查询地自动触发，以「活跃约束 / 提醒」块追加到 WP2/WP3 的 system prompt；`Autumn.active_context()` 暴露同一接缝供手动调用。push 默认不回写账本——被自动浮出 ≠ 被主动使用。
- **四维生产侧** —— 激活引擎终于有了可区分的信号：`MemoryArea.annotate()` 把维度合并到已有条目上（保留使用账本），`WP4.annotate_recent()` 用 A4 批量推断，`annotate_memory` 技能让 agent 主动声明，归并摘要自动标记为 `SUMMARIZE`。端点：`POST /memory/{area}/annotate` 与 `/auto-annotate`。
- **受治理的 Mom1 访问** —— `Mom2`/`Mom3` 保持默认隔离，但获得一条受闸的上行通道：A1 裁决被申请的 `Mom1` 读取（收窄范围 + 脱敏），A4 调解出受限答案，WP4 审计每一次裁决。以 `request_mom1_access` 技能与 `GET /memory/audit/access_log` 端点呈现；一键关闭 `MOM1_ACCESS_ENABLED=false`。
- **四维可观测性** —— `GET /memory/4d/status` 与 `POST /memory/push/preview` 让引擎可被审视（预览在不回写账本的前提下干跑 push）；macOS 记忆视图新增 4D 状态徽章、一键自动标注、每条记忆的标注控件、推送预览模式，以及 Mom1 访问审计面板。
- **运行时四维控制** —— `Autumn.configure_4d()` / `POST /memory/4d/config` 无需改环境变量或重启即可切换四维排序、每轮推送与 Mom1 通道（排序开关传播到每个记忆区，含已缓存的项目区）；macOS 设置 → 记忆 标签页实时暴露这三个开关。
- **追踪与管线条** —— 触发的 push 在工作流追踪中显示为 `wp4.push` 阶段；管线条新增紫色 4D brain 芯片，引擎触发时折叠摘要以「4D 推入」开头。
- **记忆浏览器重设计（macOS 客户端）** —— 记忆视图围绕四维系统重建：使用模式筛选芯片（约束 / 提醒 / 上下文 / 摘要，带实时计数——仅当记忆区存在四维条目时出现）、最新优先排序、每条记忆的置顶 / 相对时间 / 标签 / 重要度标识、统计条新增四维注解计数，以及把 `aim.scope` 与 `trigger.cues` 渲染为换行芯片的专属四维卡片。新增 `Autumn.colors.memory` 设计令牌统一各视图的四维视觉身份；v2 序列化记录的标题现在能正确解析（schema 默认的 `use.mode=context` 不再给每一行都打上徽章）。
- **可靠性与代码质量梳理** —— 包元数据修正为实际支持的依赖（`pydantic>=2,<3`，取消 FastAPI 上界锁定）；服务端迁移掉已被移除的 Pydantic v1 API（`.dict()`/`.json()` → `model_dump…`）；向量存储表名加入 SQL 注入校验；工具调用/结果配对使用 `zip(strict=True)`；SQLite 后端改用 `asyncio.get_running_loop()`；另有全模块 ruff 风格与导入清理（约 130 处修复）。
- 完整设计依据与分阶段计划见 [`docs/rfc-4d-memory.md`](docs/rfc-4d-memory.md)。

### 0.2.1 —— 性能优化、新内置域与扩充 MCP 目录

- **Agent 工具并发调度** —— ReAct 循环现在通过 `asyncio.gather` 并发执行同一轮的所有工具调用；独立工具不再串行等待，总延迟降为最慢单个工具的耗时。
- **记忆模块性能提升** —— 向量搜索改用 `heapq.nlargest`（O(N log k)）；查询范数只计算一次；SQLite 后端每线程缓存一个连接 + `synchronous=NORMAL`；嵌入接口新增 512 条 LRU 缓存。
- **新增始终安全 Terr 域** —— `encoding`（base64、hex、URL 编解码、哈希、UUID —— 8 个工具）和 `collection`（unique、flatten、chunk、frequencies、group_by、sort_records —— 6 个工具）；两者均加入 `SAFE_TERR_FACTORIES`。
- **MCP 目录扩充** —— 新增 7 个工厂函数：`mcp_postgres`、`mcp_slack`、`mcp_gitlab`、`mcp_google_maps`、`mcp_sequential_thinking`、`mcp_time`、`mcp_everything`。
- **服务端按需启用** —— `AUTUMN_BUILTIN_TERRS=safe|all` 可在启动及 `/config/apply` 时注册内置域（默认关闭）。
- **桌面客户端优化** —— 服务端错误信息在设置页内联展示；追踪与检查器视图显示成本合计；`AutumnChip` 统一路由标签与状态芯片；`Autumn.format` / `Autumn.colors` 令牌消除了重复的格式化辅助函数。

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

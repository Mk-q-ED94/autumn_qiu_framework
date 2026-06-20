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

## 平台集成

对于上表中需要凭据的平台，HTTP 服务可把「保存一次令牌」直接变成 agent 的能力——无需写代码、无需每次手动塞凭据。保存一次凭据，WP2 agent 在本会话内即获得该平台的工具：当请求需要时，它自行读写 issues、PR、文件与消息。

```text
GET    /integrations/catalog       # 可连接的平台 + 各自需要的字段（不含明文）
GET    /integrations/status        # 每个平台：是否已连接？暴露多少工具？最近错误？
POST   /integrations/connect       # { "id": "github", "args": { "token": "ghp_…" } }
DELETE /integrations/{id}           # 撤销：断开 MCP 服务、忘记令牌
```

`connect` 会启动对应的 MCP 服务、桥接其工具并注册为一个 Terr（因此也会出现在 `/terrs` 里、可启用/禁用）。对已连接的平台再次 `connect` 即可干净地轮换令牌。凭据只保存在服务器进程内，`/config/apply` 重建后自动恢复，**状态接口绝不回传明文**。目录：GitHub、GitLab、Slack、Brave Search、Google Maps、PostgreSQL。服务器主机需要 `npx` / `uvx` 来启动这些 MCP 二进制。

在 macOS 客户端中即 **设置 → 集成** 标签页：每个平台一个凭据表单，提供连接 / 更新 / 断开与实时状态。

## 安全

两道控制让 HTTP 桥可以安全地运行在单用户 localhost 之外：

- **API Key 鉴权** —— 设置 `AUTUMN_API_KEY` 后，除 `/health` 外的每个端点都需要该共享密钥
  （`Authorization: Bearer <key>` 或 `X-API-Key: <key>`），常量时间比较、逐请求读取，因此可
  在不重启的情况下轮换。不设置则保持开放，与之前一致，本地运行不受影响。若服务器绑定到
  `127.0.0.1` 以外却未设置密钥，启动时会发出警告。桌面客户端在 **设置 → 服务器 → 访问密钥**
  中携带该密钥。
- **平台访问默认只读** —— 连接 GitHub / GitLab / Slack / … 后，agent 只获得该平台的*读取*面。
  写类工具（创建 / 编辑 / 删除 / 合并 / 推送 / 发送 …）会被完全屏蔽，直到你在
  `POST /integrations/connect` 传入 `write_enabled: true`（即 设置 → 集成 标签页里的
  **允许写操作** 开关）并重新连接。状态接口会回报 `write_enabled` 及被屏蔽的写工具数量，
  授权始终可见——除非你刻意授予，最危险的能力根本不存在。

凭据只保存在服务器进程内（状态接口绝不回传）与客户端本地偏好设置中。为客户端引入基于
Keychain 的静态加密存储是下一步计划中的加固项。

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

当前版本：**0.3.2**。Autumn 遵循语义化版本；在 `0.x` 阶段，次版本号的提升代表新增功能，且可能调整 API。

### 0.3.2 — 2026-06-20 · 代码库记忆（省 token 代码图谱）+ 全自写 macOS 外壳

新增框架级的**代码库记忆**子系统——用代码图谱去省 agent 的 token；并完成 macOS 客户端从系统模板组件到全手写外壳的迁移。

- **代码库记忆——框架级的省 token 子系统。** 将外部的 `codebase-memory-mcp` 代码情报服务
  （MIT）深度接入框架，成为一等公民的底层能力（`autumn/core/codebase/`、`Autumn.codebase`），
  而不只是工具袋里多一件工具：
  - **主动注入架构地图。** 开启后框架会把代码库索引成知识图谱，执行器（**WP2**）在每个
    **CODE** 任务前自动注入一份图谱推导出的紧凑「架构地图」——A2 一开始就有方向，不必再烧
    token 逐文件重建结构。
  - **原生 `codebase` 能力域。** 图谱工具（`search_graph` / `trace_path` /
    `get_architecture` / `query_graph` / `get_code_snippet`）被注册为一等能力域，供 agent
    按需深挖；上游项目自述在结构探索上可省约 99% 的 token。
  - **一个开关，框架自有。** 由 `codebase_memory_enabled` 行为开关控制（默认关闭；
    `CODEBASE_MEMORY_ENABLED` / `CODEBASE_MEMORY_REPO`）。`Autumn.start_codebase_memory()`
    负责连接 MCP、注册能力域并在后台预热索引；开关打开时服务器自动启动，也可通过
    `GET`/`POST /config/codebase-memory` 与桌面端 **设置 → 高级** 实时切换。需主机安装
    `uvx`/`npx`；整层容错（二进制缺失时退化为「无额外上下文」，绝不打断一轮对话）。
- **全自写 macOS 外壳** —— macOS 客户端弃用了最后一批系统模板组件
  （`NavigationSplitView`、基于 `List` 的侧栏、系统工具栏与 `.inspector` 修饰符），改为
  手写 SwiftUI 外壳：用普通 `HStack` 做分栏 + 暖纸色侧栏（新增 `Autumn.colors.sidebar`
  令牌）+ 令牌化的 `AutumnNavItem` + 内容区内置标题栏 + 自定义滑出检视面板——与 WinUI
  端「自有外壳、非模板」的方向对齐。全程走 Paper & Clay 令牌，遵循 `accessibilityReduceMotion`。
- **测试** —— 新增 `tests/test_codebase_memory.py`（核心组件 + WP2 注入 + 框架装卸）与一个
  框架驱动的服务端端点测试；**1022 通过**，ruff 干净。

### 0.3.1 — 2026-06-17 · 客户端优化与适配

打磨桌面客户端，并把 MCP 目录变成一个真正能「了解并启用」服务器的地方——以及支撑它的服务端接口。叠加在 0.3.0 框架之上。

- **每个 MCP 的介绍、内联配置与配置教程** —— 能力域（Terr）页的 MCP 目录现在可展开：每个 MCP 显示用途、实时连接状态徽章、内联的凭据/路径表单（默认只读 + 写操作开关），以及带文档链接的分步配置教程。无需凭据的工具一键连接；需配置的填完表单即可连接。
- **通用 MCP 连接** —— 新增 `/mcps/status`、`/mcps/connect`、`/mcps/{id}`，可将目录里的*任意* MCP 上线（不再限于六个需凭据的平台），与平台集成共用同一运行时，所以连接状态在「设置」和「能力域」两处一致。`GET /mcps/catalog` 现在携带 category、表单字段与教程。
- **旧服务器自愈** —— 服务器在 `/health` 暴露 `api_revision`；桌面端检测到本地有一个「可连接但版本过旧」的服务器（例如 `git pull` 后还残留运行的旧进程）时，会从仓库**自动重启它**，且只杀掉*监听*该端口的进程。无法自动处理时（远程/非托管），能力域页给出明确的「请重启服务器」提示，并把裸的 404 翻译成可操作的信息。
- **桌面设计精修（macOS）** —— 动效统一到 `Autumn.motion` 令牌；所有循环动画遵循 `accessibilityReduceMotion`；按钮统一按下缩放 + 悬停态；窗口标题栏材质不再溢出遮挡「记忆 / 能力域 / 设置」工具条。
- **文档** —— `docs/local-build-test.md` 记录了框架、macOS、web、Windows 各端的「拉取 → 构建 → 测试」流程。
- **测试** —— 842 通过（新增 `tests/test_server_mcps.py`），ruff 干净。

### 0.3.0 — 2026-06-17 · 协作式多模型工作流 + 中央安全模块

把 A1–A4 流水线变成**双向协作工作流**：A1（组长）现在主导——制定计划、监督、委派——而不再只出现在路由与总检两端。每个特性都有开关；主开关 `COOPERATIVE_WORKFLOW`（默认关）可把整层回退到 0.2.x 行为。在 0.2.3 的四维记忆与 HTTP 桥安全之上构建。

- **按执行者重划 Task / Mission** —— TASK → A2（重型代码工作），MISSION → A3（其余所有通用工作：写作、分析、摘要、文档）；A3 仍可通过 convert 升级更重的 mission。
- **A1 主导流水线** —— A1 获得 WP4、项目记忆与 Mom1 访问代理的句柄，从而能监督执行、主导项目讨论，而非只在路由/总检两端出现。
- **A1 任务规划** —— 派发 TASK 前，A1 先草拟 3–6 步计划并作为 WP2 system 提示注入；以 `wp1.plan` trace 阶段呈现。由 `A1_TASK_PLANNING` 控制。
- **A1 监督** —— 每个 ReAct 步后 A1 复核 A2 的动作并可注入纠偏指导（与厂商无关）；以 `wp1.supervise` 阶段呈现。由 `A1_SUPERVISION` 控制。
- **能力感知路由** —— Selector 分类时会看到已启用 Terr 域的摘要，使路由反映 agent 真正能做的事。
- **A3 轻量工具集** —— A3 获得一个有界（≤4 步、白名单）的技能循环，可在回答前调用 recall / time 等，流式与非流式直答路径都支持。通过 `A3_LITE_SKILLS` 设置。
- **A4 认知委派** —— WP4 的重型认知操作（consolidate / evolve / extract_facts / synthesize_profile / annotate）与项目参数讨论优先交给强模型 A1，而非弱的本地 A4，并以体量阈值把小操作留在本地。由 `A4_DELEGATE_TO_A1`（默认开）控制。
- **A4 知识 Terr + 研究** —— 新增 `knowledge_terr`（web_search / fetch_document / knowledge_base_query）与有界的 `WP4.research()` 循环，赋予 A4 外部检索能力。由 `A4_KNOWLEDGE_TERR` 控制。
- **执行归档** —— 每轮的结果写入共享区（`wp4.push`），让团队积累可检索的历史。由 `ARCHIVE_EXECUTIONS` 控制。
- **中央安全模块** —— `autumn/core/security.py` 统一了 SSRF 防护、密钥脱敏、路径沙箱与资源限制（被网络 Terr 与 HTTP 桥共用），并扩充了防护（math DoS 边界、请求体大小限制、安全响应头、可配置 CORS）。
- **全模块优化 + 健壮性梳理** —— 记忆解码容错、API 重试/用量加固、网络 Terr 去重与重定向时的 SSRF 复检、框架接线修复。
- **测试** —— 983 通过（新增 `tests/test_cooperative_workflow.py`），ruff 干净。

### 0.2.3 — 2026-06-15 · 借鉴 EverOS 的四维记忆增强 + HTTP 桥安全加固

在 0.2.2 的「激活引擎」之上，沿**持久化 / 抽取**这条轴深化记忆子系统——至此四维记忆在**两条轴**（记忆如何持久与抽取、以及如何激活）上都已成形。所有特性均为**增量且可选**：在默认配置下行为与 0.2.2 完全一致。设计动机与上游对比见
[`docs/everos-4d-memory-takeaways.md`](docs/everos-4d-memory-takeaways.md)。

- **Markdown 即真相源后端** —— `STORAGE_BACKEND=markdown` 将每条记忆存为一份可读的 `.md` 文件，四维（aim/use/trigger）以 JSON frontmatter 序列化；写入原子化（tmp + `os.replace`），淘汰时同步删除文件。
- **混合召回（BM25 + 向量）** —— `LEXICAL_RECALL_ENABLED=true` 增加一层基于 SQLite FTS5、用 `bm25()` 排序的关键词索引，再以倒数排名融合（RRF）与语义向量结果合并，让专有名词、标识符与符号能与语义一起命中。FTS5 操作符做了防注入中和，环境缺少 FTS5 时优雅降级。
- **提示槽** —— 整合、召回综合、事实抽取、自演化与画像五类提示词外置到 `autumn/core/memory/prompts.py`，每次调用可通过 `system_prompt=` 覆写；默认值与此前内联字符串逐字节一致。
- **类型化记忆与原子事实抽取** —— 记忆按保留标签分类（`episode` / `atomic_fact` / `profile` / `summary` / `case`）；`MemoryArea.extract_facts(api)` 把原始对话拆成可被召回独立命中的离散事实。`DERIVED_KINDS` 守卫阻止各派生流程拿自己的产物再喂自己。HTTP：`POST /memory/{area}/extract-facts`。
- **异步索引** —— `ASYNC_INDEX=true` 把向量 + 词法索引移出写入路径,交给受跟踪的后台任务；追加立即返回,`framework.close()` 经 `flush_index()` 排空。
- **自演化** —— `MemoryArea.evolve(api)` 按 `aim.intent` 聚合非派生历史；反复出现且被强化（`use.count`）的集群,由 A4 提炼成一条置顶的 `case` 规则（`CONSTRAIN` 模式）——这是奖励循环的消费端,把被验证有用的记忆升格为可被 push 推送的常驻规则。对同一 intent 幂等。HTTP：`POST /memory/{area}/evolve`。
- **用户画像轨道** —— `set`/`get`/`synthesize_profile(scope=…)` 为每个 scope 维护一条置顶画像（`scope:<id>` 标签）,采用覆写（而非追加）语义；`synthesize_profile` 经 A4 把近期历史折叠进常驻模型。HTTP：`GET`/`POST /memory/{area}/profile`。
- **WP4 接口** —— A4 的策展工作区新增 `extract_facts`、`evolve`、`get_profile`、`synthesize_profile`,均带模型守卫与审计日志。
- **安全加固（HTTP 桥）** —— 详见下方[安全](#安全)章节:
- **API Key 鉴权** —— 设置 `AUTUMN_API_KEY` 即可要求除 `/health` 外的每个端点都携带
  共享密钥（Bearer 或 `X-API-Key`，常量时间比较，可不重启轮换）。不设置则对本地单用户运行保持
  完全开放；服务器绑定到 localhost 以外却未设置密钥时会发出警告。桌面客户端在 设置 → 服务器
  中填入并自动携带。
- **平台集成默认只读** —— 已连接的平台现在只把读类工具暴露给 agent；写类工具（创建 / 编辑 /
  删除 / 合并 / 推送 / 发送 …）在用户授予写权限（`write_enabled`）并重新连接前一律屏蔽。状态接口
  回报 `write_enabled` 与 `blocked_tool_count`，集成标签页新增每个平台的写权限开关——除非刻意授予，
  最危险的能力根本不存在。
- **测试** —— 共 907 通过（四维记忆 P1–P3,外加 API Key 鉴权与集成写权限门控两组测试），ruff 干净。

### 0.2.2 — 2026-06-13 · 四维记忆（活性记忆）、客户端重设计、平台集成与质量梳理

- **平台集成** —— 只需保存一次凭据（GitHub、GitLab、Slack、Brave、Google Maps、Postgres），WP2 agent 在本会话内即获得该平台的工具：自行读写 issues、PR、文件与消息，无需每次手动提供凭据。服务端启动对应的 MCP 服务并注册为一个 Terr —— `GET /integrations/catalog`、`/integrations/status`、`POST /integrations/connect`、`DELETE /integrations/{id}`。凭据只保存在服务器进程内，`/config/apply` 重建后自动恢复，状态接口绝不回传明文。macOS 设置 → 集成 标签页提供连接 / 更新 / 断开与实时状态。
- **「纸感陶土」客户端重塑** —— 桌面视觉语言从暖橙色阶转向由单一陶土强调色统领的冷静中性画布（Claude / ChatGPT / Codex 那种克制的单强调色方向）：随主题自适应的表面、干净的系统无衬线字体、压扁的阴影与发丝级描边。全部走设计令牌，一次性重塑所有视图。
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

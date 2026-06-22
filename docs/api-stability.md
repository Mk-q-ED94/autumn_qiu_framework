# API Stability — 1.0 冻结边界

> 状态：**规划中（Planning）**· 当前版本：0.3.4（0.x，无向后兼容承诺）  
> 目标：在走向 1.0 之前，明确**哪些表面将被冻结、哪些仍可演进、哪些根本不算契约**。

本文是 Autumn 公开 API 的稳定性分级。它回答一个问题：**作为嵌入方 / 客户端作者，
我可以依赖什么？** 与 `docs/http-sse-contract.md`（描述 HTTP 面*是什么*）互补——本文描述
每个表面*能不能被依赖*。

---

## 分级语义

| 级别 | 标记 | 含义 | 变更政策 |
|------|------|------|----------|
| **稳定** | 🟢 Stable | 面向嵌入方/客户端的核心契约 | 1.0 冻结。0.x 内若必须破坏，提供一个 minor 的弃用期 + changelog |
| **实验** | 🟡 Experimental | 已可用但仍在打磨的子系统 | 任意 minor 可变；接近 1.0 时逐步收敛进 🟢 |
| **内部** | 🔴 Internal | 实现细节，技术上可访问但不是契约 | 随时可变，恕不通知。依赖它=自担风险 |

**0.x 期间的总原则**（SemVer 0.x：minor 允许破坏）：
- 🟢 表面：尽量不破坏；若破坏，`README` changelog 显式标注 + 至少一个 minor 的弃用别名。
- 🟡 表面：可能在任意 minor 调整签名/语义；变更进 changelog，但不保证弃用期。
- 🔴 表面：无任何承诺。

**1.0 之后**：🟢 全面冻结（破坏需 major）；🟡 要么升级为 🟢、要么明确标注仍为实验。

---

## 1. Python 包 API（`import autumn`）

只有从顶层 `autumn` 包导出的名字（见 `autumn/__init__.py` 的 `__all__`）才在契约内。
**深层导入** `autumn.core.*` / `autumn.builtin.*` 中*未*被顶层重导出的部分一律视为 🔴。

### 1.1 🟢 Stable — 嵌入方核心

| 符号 | 类型 | 说明 |
|------|------|------|
| `Autumn` | class | 框架入口（方法分级见 §2） |
| `AutumnConfig` | dataclass | 顶层配置；构造签名与字段稳定 |
| `ModelConfig` | dataclass | 模型槽配置（`api_key/base_url/model/protocol`） |
| `BehaviorConfig` | dataclass | 行为开关（**字段为加法式扩展**，见 §3） |
| `StorageConfig` | dataclass | 存储后端配置 |
| `WorkspacePrompts` | dataclass | 各工作区提示词覆盖 |
| `Protocol` · `InputType` · `TaskType` · `MissionRoute` · `Role` | enum | 值集稳定（见契约文档 §14） |
| `Message` | dataclass | `{role, content}`，LLM 消息单元 |
| `Terr` · `Skill` · `Tool` · `ToolParameter` · `Agent` | class | 能力域/工具的构造 API（添加能力的主路径） |
| `MCPClient` · `StdioMCPClient` · `mcp_to_tools` | class/fn | MCP 接入 |
| `register_safe_builtins` · `register_builtins` | fn | 一次性注册内置 Terr 集 |
| `time_terr` · `math_terr` · `text_terr` · `data_terr` · `web_terr` · `fs_terr` · `memory_terr` · `knowledge_terr` | factory | 内置 Terr 工厂；**工厂签名**稳定，内部工具集可加法扩展 |

### 1.2 🟡 Experimental — 可用但可能调整

| 符号 | 说明 |
|------|------|
| `EmbeddingConfig` | 向量嵌入配置；维度/协议假设仍可能随后端演进 |
| `WorkflowRun` · `WorkflowStage` | trace 结构。**字段为加法式**：现有字段稳定，但会新增字段；按名取用、忽略未知字段 |
| `AgentStep` · `ToolCall` | ReAct 步骤结构，随 WP2 演进 |
| `Selector` · `Checker` | A1 内部组件；暴露用于高级定制，签名可能变 |
| `EmbeddingInterface` · `HermesAPIInterface` | 自定义模型/嵌入后端的扩展点 |
| `UserInteraction` · `CLIInteraction` | 交互通道抽象 |
| `SearchResult` | 知识检索返回结构 |

---

## 2. `Autumn` 方法

实例化（`Autumn(config)`）稳定。方法分级如下。

### 2.1 🟢 Stable — 核心管线与注册

| 方法 | 签名要点 | 说明 |
|------|----------|------|
| `process(input, *, mission_route, input_type, task_type)` | → `str` | 同步单次推理 |
| `process_with_trace(...)` | → `WorkflowRun` | 同步 + trace |
| `stream(...)` | → async iter[str] | 流式文本 |
| `stream_with_trace(...)` | → async iter[str \| WorkflowRun] | 流式 + 末帧 trace |
| `classify_intent(...)` | → `(SelectorResult, route)` | 仅分类 |
| `describe_terrs()` | → `list[dict]` | Terr 自省（驱动 `/terrs`） |
| `set_terr_enabled(name, enabled)` | → `dict` | 启停 Terr |
| `register_tool` · `register_skill` · `register_agent` | → None | 注册单个能力 |
| `register_terr(terr)` · `add_terr(terr)` | sync / async | 注册能力域（`add_terr` 跑 MCP connect 管线） |
| `add_mcp(client)` | → `list[Tool]` | 接入 MCP 客户端 |
| `end_session()` · `close()` | async | 生命周期；`close()` 容错释放所有资源 |

> **关键参数顺序与关键字**：上述方法的*位置参数 `input`* 与*关键字参数*
> （`mission_route`/`input_type`/`task_type`）属于冻结契约。

### 2.2 🟡 Experimental — 构建器与子系统

| 方法 | 说明 |
|------|------|
| `configure_4d(...)` | 4D 记忆运行时配置（子系统仍实验，见 §4） |
| `start_codebase_memory(repo)` · `stop_codebase_memory()` | Codebase Memory 层开关（实验子系统） |
| `add_memory_skills(area)` · `add_mom1_access_skill(area)` | 把记忆技能挂到某区；挂载点语义可能调整 |
| `active_context(...)` | 组装当前上下文快照；结构可能演进 |
| `project_zone(project_id)` · `project_scope(project_id)` | 项目作用域访问 |
| `open_terr(terr)` | 临时打开 Terr 的上下文管理器 |

### 2.3 🔴 Internal — 不是契约

| 属性 | 为什么内部 |
|------|-----------|
| `Autumn.a1` · `a2` · `a3` · `a4` | 模型 API 接口对象，内部布线 |
| `Autumn.mom1` · `mom2` · `mom3` · `shared` | 原始记忆区对象。**外部应走 HTTP 记忆端点或记忆技能**，不要直接持有 |
| `Autumn.wp1` · `wp2` · `wp3` · `wp4` | 工作区对象。其方法（含项目协调转发器）是内部布线，签名随时变 |
| `Autumn.plugins` | `PluginLoader` 实例 |
| 任何 `_` 前缀的方法/属性 | 私有 |

> ⚠️ 服务端 `app.py` 通过 `autumn.wp1` / `autumn.wp4` 调用工作区方法——那是**同仓内的紧耦合**，
> 不构成对外承诺。第三方嵌入方不应复制这种访问。

---

## 3. `BehaviorConfig` 字段

字段集**加法式扩展**：新增带默认值的开关不算破坏；删除/改默认值才算。

### 3.1 🟢 Stable 开关

`agent_max_steps` · `checker_retries` · `confirm_threshold` · `history_limit` ·
`cooperative_workflow`（总开关）· `memory_decay_half_life`

### 3.2 🟡 Experimental 开关（默认关，子系统仍在收敛）

`fourd_memory_enabled` · `fourd_push_on_turn` · `lexical_recall_enabled` ·
`async_index` · `archive_executions` · `codebase_memory_enabled` · `codebase_memory_repo`

> 这些开关对应的子系统（4D push、词法召回、后台索引、codebase memory）仍是 🟡；
> 开关名可能稳定，但**行为语义**可能随子系统调整。

### 3.3 配置入口

`AutumnConfig.from_env()` · `ModelConfig.from_env(prefix)` · `BehaviorConfig.from_env()` ·
`EmbeddingConfig.from_env()` — 🟢 Stable（环境变量名是契约的一部分）。

---

## 4. HTTP / SSE 端点

完整描述见 `docs/http-sse-contract.md`。稳定性分级：

### 4.1 🟢 Stable — 核心契约（三端共依赖）

| 端点 | 说明 |
|------|------|
| `GET /health` | 探针 + `api_revision` 门控 |
| `POST /config/apply` | 配置模型槽 |
| `POST /models` | 列模型（连接测试） |
| `POST /process` · `POST /trace` · `POST /intent` | 同步推理 / trace / 意图 |
| `GET /stream` | **SSE 帧格式冻结**：`{chunk}` / `{trace}` / `{error}` / `[DONE]` / `: ping` 心跳 |
| `GET /terrs` · `PATCH /terrs/{name}` | Terr 自省与启停 |
| `POST /session/end` | 会话结束 |

> SSE 的帧键名（`chunk`/`trace`/`error`）、`[DONE]` 终止符、`: ping` 心跳、断线计费保护
> 语义——这一整套是冻结契约。

### 4.2 🟡 Experimental — 子系统端点

| 端点组 | 为什么实验 |
|--------|-----------|
| `/memory/{area}/consolidate \| extract-facts \| evolve \| profile \| auto-annotate` | A4 认知操作，随记忆引擎演进 |
| `/memory/{area}/annotate` · `/memory/4d/*` · `/memory/push/preview` | 4D 标注/推送子系统 |
| `/memory/audit/access_log` | Mom1 审计面 |
| `/projects/{id}/describe \| goals \| infer-environment` | A1 项目智能（0.3.3 刚从 A4 迁来，仍在稳定） |
| `/mcps/*` · `/integrations/*` | 内联连接面（`api_revision=1` 引入，仍会增长） |
| `/config/codebase-memory` | Codebase Memory 开关（实验子系统） |
| `/ollama/*` | 本地 Ollama 辅助面，绑定外部 Ollama API 形态 |

> `/projects/{id}/metadata`、`/projects` 列表/删除等**基础 CRUD** 接近 🟢，但因项目元数据
> 模型（`ProjectMeta`/`ProjectEnvironment`）仍可能加字段，暂列 🟡。

---

## 5. 内置 Terr 的工具/技能名

工具/技能的**名字与参数**是模型可见契约的一部分，但比代码 API 宽松：

- 🟢 已文档化的工具名（如 `http_get` · `http_head` · `web_search` · `recall` · `remember`）
  及其核心参数稳定。
- 🟡 工具集**加法式扩展**——某个 Terr 可能新增工具；现有工具的新增*可选*参数不算破坏。
- 🔴 工具的内部实现、返回字符串的精确措辞——不是契约。

---

## 6. 走向 1.0 的收敛清单

把 🟡 收敛/定级为 🟢 的前置条件：

- [ ] **4D push 引擎**（§4.1 P2 #6）：push 路径有端到端用例后，`fourd_*` 开关与
  `/memory/4d/*` 升 🟢。
- [ ] **Codebase Memory**：`start/stop_codebase_memory` + `/config/codebase-memory`
  在真实 `uvx`/`npx` 环境验收后定级。
- [ ] **项目智能端点**：`ProjectMeta` 字段集冻结后，`/projects/*` 升 🟢。
- [ ] **trace 结构**：`WorkflowRun`/`WorkflowStage` 字段集冻结后升 🟢（客户端已在解析）。
- [ ] **`/mcps` · `/integrations`**：连接面定稿、`api_revision` 收敛后升 🟢。
- [ ] 决定 `EmbeddingConfig` 是否进 🟢（取决于是否承诺向量后端形态）。

满足以上后，发布 `docs/api-stability.md` 的 **1.0 冻结版**，并在 `README` 写明
向后兼容承诺正式生效。

---

> 维护约定：任何新增公开符号/端点，落地时在本文归级（🟢/🟡/🔴）。升级 🟡→🟢 需在
> `README` changelog 记录，并在 §6 勾掉对应项。

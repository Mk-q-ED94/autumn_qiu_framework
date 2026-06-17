# RFC: 合作型多模型工作流（Cooperative Multi-Model Workflow）

> 状态：**已实现（Implemented）**· 目标里程碑：0.3.0
> 范围：`autumn/core/workspace/{wp1,wp2,wp3,wp4}` · `autumn/core/components/{selector,agent}.py`
>       `autumn/core/framework.py` · `autumn/core/config.py` · `autumn/builtin/knowledge_terr.py`
>
> 本文定义 0.3.0 的核心主题：让 A1/A2/A3/A4 从「分工型」单向流水线升级为
> **具备主动交互能力的合作型工作流**。四个模型有清晰的角色分工，A1 作为组长
> 驱动整体协调，关键节点允许直接的模型间消息传递。

---

## 实现状态（Implementation Status）

全部 Phase 已落地，由 `COOPERATIVE_WORKFLOW` 总开关统一门控（默认开；置 false 退回 0.2.x）。

| Phase | 功能 | 开关（env） | 关键代码 |
|-------|------|-------------|----------|
| 0 | A1 全模块连接 | 始终 | `WP1Tot.__init__(wp4, projects, mom1_access)` |
| 1 | 任务边界重定义 | 始终 | `selector.py` 提示词 |
| 1 | 能力感知路由 | 始终 | `Selector(capability_provider=...)` + `Autumn._capability_digest` |
| 2 | A3 Lite Toolset | `A3_LITE_SKILLS` | `WP3Mis(skill_provider=...)` |
| 3 | A1 任务计划 | `A1_TASK_PLANNING` | `WP1Tot._plan_task` → `plan_hint` |
| 3 | A1 执行监督 | `A1_SUPERVISION` | `Agent.run(supervisor=...)` + `WP1Tot._build_supervisor` |
| 3 | 执行归档 | `ARCHIVE_EXECUTIONS` | `WP4Mem.record_execution_summary` |
| 4 | A4→A1 认知委托 | `A4_DELEGATE_TO_A1` + `A4_DELEGATION_THRESHOLD` | `WP4Mem._cognitive_api` |
| 4 | A4 外部检索引擎 | `A4_KNOWLEDGE_TERR` | `knowledge_terr` + `WP4Mem.research` |
| 5 | 项目讨论归 A1 | `A4_DELEGATE_TO_A1` | `draft_*`/`infer_environment` → `_cognitive_api(0)` |

测试：`tests/test_cooperative_workflow.py`（21 例）+ 全量回归 928 passed。

---

## 1. 现状与问题

### 1.1 当前工作流是单向流水线

```
用户输入 → A1(选路) → A3(direct) → A1(check) → 用户
           ↓
           A3(convert) → A2(task loop) → A1(check) → 用户
```

A1 只在**起点**（Selector 分类）和**终点**（Checker 校验）出现。中间过程
A1 完全不知道执行情况：A2 卡住了它不知道；A3 无工具但收到工具型请求它不知道；
A4 加工完记忆没人问它。这是「分工」而非「合作」——四个模型之间没有对话，只有
A1 拍板后各干各的。

### 1.2 具体断点（代码级证据）

| 问题 | 位置 | 现状 |
|------|------|------|
| A1 无法感知执行进度 | `wp1.py:115-133` ctor | 只持有 `wp2`/`wp3` 引用，无 WP4、无项目上下文 |
| A1 无法介入执行中途 | `wp1.py:135-450` | `process_with_trace` 是一次性的直线调用 |
| A3 零工具访问 | `wp3.py:48-86` | 全是裸 `api.complete()`，无 Skill/Tool/Agent |
| A4 的工作 A1 不知道 | `framework.py` wiring | WP4 未传入 WP1；A1 在路由决策时不知记忆状态 |
| 项目参数讨论走 A4 | `wp4.py:draft_description/draft_goals` | A4 是本地弱模型，缺乏对话推理能力 |
| task/mission 边界模糊 | `selector.py` + `types.py` | `InputType.TASK` 含义宽泛，写作/数据分析也走 A2 |

### 1.3 角色失位

- **A4（本地弱模型）** 承担着「项目参数讨论」这种需要强推理的交互，反而将
  「需要外部知识/检索工具」的记忆加工任务做得粗糙。
- **A3** 没有工具，但 Selector 有时会把需要文件读写的写作任务路由给它。
- **A1** 作为「组长」却在执行过程中处于空转状态，既没有监督能力也没有干预路径。

---

## 2. 角色重定义

0.3.0 明确四个模型的职责边界。

### 2.1 A1 — 项目组长（Orchestra）

**职责**：协调、计划、监督、验收；必要时直接参与。

| 能力 | 现在 | 0.3.0 目标 |
|------|------|-----------|
| 路由 | Selector 二段分类 | 同上 + 能力感知路由（知道有哪些 Terr） |
| 计划 | 无 | 对复杂 task 生成步骤计划，拆分子任务 |
| 监督 | 无 | 持有 WP4 引用；可查记忆状态；可发中间指令 |
| 验收 | Checker 终点校验 | 同上 + 可将不合格结果重新派发 |
| 干预 | 无 | 在 A2 执行超出预期时注入补充指令 |
| 项目讨论 | 无（走 A4） | 由 A1 主导项目参数澄清对话 |
| WP4 连接 | 无 | A1 ctor 接收 `wp4: WP4Mem \| None` |

**A1 不做**：具体的代码/文档生成、记忆加工、向量检索。

### 2.2 A2 — 重型执行者（Heavy Task）

**职责**：长程、繁重的代码工作。

**mission/task 重定义**：
- `task`（A2 执行）= 需要 ReAct 循环、多步工具调用的繁重代码类工作
  （调试、大幅重构、跨文件变更、测试套件构建等）
- `mission`（A3 执行）= 其它所有通用任务：问答、写作、数据分析、简单代码说明、
  结构化文档生成——**包括之前错误地推给 A2 的非代码结构化工作**

A2 的 ReAct Agent 不变；减少它处理简单会话任务的次数，让它专注于真正需要
迭代执行的工作。

### 2.3 A3 — 通用执行者（Mission）

**职责**：通用任务执行，包括所有非重型代码工作。

**0.3.0 新增**：A3 获得一个受限工具集（Lite Toolset），不是 A2 的完整 ReAct 工具袋，
而是适合 mission 路径的能力域：

| 工具类型 | 示例 | 适用场景 |
|----------|------|---------|
| Memory skills | `recall` / `remember` | 任意 mission 均可调用 |
| Time/format | `get_time` / `format_json` | 写作/数据辅助 |
| Search（可选）| `web_search` | 问答类 mission |
| File read（可选）| `read_file` | 写作前参考上下文 |

A3 **不获得**：代码执行、shell、完整文件系统写入——需要这些的请求应由
Selector 路由至 A2（task）。

### 2.4 A4 — 记忆专家（Memory Specialist）

**职责**：记忆加工；配合 A1 的记忆状态查询；不再承担项目讨论。

**0.3.0 新增两条增强路径**：

#### 路径 A：强模型委托（Strong-Model Delegation）

当 A4 面对高复杂度的认知操作时（综合对话、多步推理、策略分析），可以将该操作
**委托给 A1 的 api** 执行，A4 只做前处理和结果写入：

```python
# wp4.py 新增
async def delegate_to_a1(self, prompt: str) -> str:
    """Ask A1 to perform a cognitively heavy memory operation."""
    if self._a1_api is None:
        raise RuntimeError("A1 api not wired — cannot delegate")
    return await self._a1_api.complete([
        Message(role=Role.SYSTEM, content=MEMORY_DELEGATION_SYSTEM),
        Message(role=Role.USER, content=prompt),
    ])
```

WP4 ctor 增加 `a1_api: ModelAPIInterface | None = None` 参数；`framework.py`
在构造 WP4 时把 A1 的 api 传入。

#### 路径 B：外部检索引擎（Retrieval/Knowledge Terr）

注册一个 `knowledge_terr`，为 A4（以及 A2/A3）提供外部知识获取能力：

```
knowledge_terr
  ├── web_search       # 联网搜索（wraps Terr builtin）
  ├── document_fetch   # 按 URL 读取文档
  └── knowledge_base_query   # 本地向量库的独立入口（独立于 Mom 区域）
```

A4 在做记忆综合（`evolve`/`consolidate`）时可以主动调用 `knowledge_terr` 补充
外部信息，而非只依赖已有记忆条目。

---

## 3. 合作机制设计

用户答复：**混合机制**——A1 编排为主干，关键节点允许直接模型间消息。

### 3.1 A1 编排主干（Orchestration Backbone）

A1 的 `process_with_trace` 升级为多阶段编排循环：

```
┌─────────────────────────────────────────────────────────┐
│                     A1 编排循环                          │
│                                                         │
│  1. [Classify]  Selector → input_type / task_type       │
│  2. [Plan]      对 task 输入生成执行计划（可选）           │
│  3. [Dispatch]  路由到 A3(mission) 或 A2(task)           │
│  4. [Supervise] 执行中可注入补充指令（agent channel）      │
│  5. [Review]    Checker 校验；不合格可重新 Dispatch        │
│  6. [Archive]   通知 WP4 记录本次执行摘要                  │
└─────────────────────────────────────────────────────────┘
```

关键变化：
- 步骤 2（Plan）：对 `InputType.TASK` 且复杂度评分高的输入，A1 先生成结构化计划
  （steps list），作为 WP2 ReAct 的初始 system hint。
- 步骤 5（Supervise）：`WP2Tas.run_agent()` 暴露一个 `supervise_channel` 回调；
  A1 可在 WP2 每完成一个 step 后收到进度通知，并可注入补充指令。
- 步骤 6（Archive）：执行结束后 A1 调用 `wp4.record_execution_summary()`，
  A4 决定是否存入记忆。

### 3.2 关键节点直接消息（Direct Agent Messaging）

在以下三个关键节点，允许模型间直接通信，不走 A1 中转：

| 节点 | 发送方 | 接收方 | 内容 | 触发条件 |
|------|--------|--------|------|---------|
| WP2→WP4 记忆写入 | A2 | A4 | 执行过程中发现的事实/规则 | A2 ReAct 产出明确的 remember 指令 |
| WP3→WP4 记忆写入 | A3 | A4 | mission 结论摘要 | A3 完成 direct 回复后 |
| WP4→WP1 记忆推送 | A4 | A1 | 当前 session 的关键记忆摘要 | 每次 turn 开始前（已有 push 引擎） |

这三条直接通道**不引入新的异步协议**，而是通过「在 WP1 ctor 中把 wp4 引用
传给 WP2/WP3」的方式实现同步调用。

### 3.3 项目讨论归 A1

`WP4.draft_description` / `draft_goals` / `infer_environment` 这三个方法：
- A4 继续做**机械解析**（从文本提取键值）
- **对话推理**部分移交 A1：用户澄清项目参数时，`framework.py` 的
  `setup_project()` 系列方法调用 `wp1.api.complete()` 而非 `wp4.api.complete()`

实现方式：`ProjectMemory` 和 `AutumnConfig` 的项目参数收集入口保持不变；
`framework.py:Autumn.setup_project()` 在组装 prompt 后使用 A1 api。

---

## 4. 实现计划

### Phase 0（基础连接）— WP1 ctor 扩展

**文件**：`autumn/core/workspace/wp1.py`, `autumn/core/framework.py`

```python
class WP1Tot(WorkspaceBase):
    def __init__(
        self,
        api,
        memory,
        wp2: WP2Tas,
        wp3: WP3Mis,
        wp4: WP4Mem | None = None,          # NEW
        projects: ProjectMemory | None = None,  # NEW
        mom1_access = None,                  # NEW (Mom1AccessBroker)
        interaction: UserInteraction | None = None,
        ...
    ):
        ...
        self.wp4 = wp4
        self.projects = projects
        self.mom1_access = mom1_access
```

`framework.py:Autumn._build_wp1()` 传入 `wp4`, `projects`, `mom1_access`。

**影响**：WP1 获得全模块视图；后续所有功能基于此基础。

### Phase 1（任务边界重定义）— Selector + 类型系统

**文件**：`autumn/core/types.py`, `autumn/core/components/selector.py`,
`autumn/core/workspace/wp1.py`

1. `InputType` 语义明确：`TASK` = 重型代码工作；`MISSION` = 通用任务（现有
   direct/convert 子路由不变）。
2. Selector 系统提示更新：加入任务边界说明，让模型知道写作/数据分析应分为
   `MISSION` 而非 `TASK`。
3. Selector 加入能力感知（援引 Terr/MCP RFC §4.2）：`capability_digest()` 作为
   可选前缀注入 Selector 提示。

### Phase 2（A3 Lite Toolset）— WP3 工具接入

**文件**：`autumn/core/workspace/wp3.py`, `autumn/core/framework.py`

`WP3Mis` 增加 `skills: list[Skill] | None = None` 参数；当有 skill 时，
`answer_directly` 使用带 tool_use 的 complete（单轮，非 ReAct 循环），
`convert_to_task` 不变。

`framework.py` 注册 A3 lite skills 时从已注册 Terr 中挑选安全子集
（由配置 `a3_skills` whitelist 控制）。

### Phase 3（A1 计划与监督）— Orchestration Loop

**文件**：`autumn/core/workspace/wp1.py`, `autumn/core/workspace/wp2.py`

1. `WP1Tot._plan_task(user_input, sel) -> str | None`：对复杂 task 生成步骤计划。
2. `WP2Tas.run_agent()` 接受 `plan_hint: str | None` 参数，注入到 system。
3. `supervise_channel` 回调（可选）：WP2 每步完成后 yield 给 WP1，WP1 可注入
   追加指令（`agent.inject_message()`）。
4. WP1 编排循环完成后调用 `self.wp4.record_execution_summary()`（Phase 0 依赖）。

### Phase 4（A4 增强）— Delegation + Retrieval

**文件**：`autumn/core/workspace/wp4.py`, `autumn/builtin/knowledge_terr.py`（NEW）

1. `WP4Mem.__init__` 增加 `a1_api` 参数；`delegate_to_a1()` 方法。
2. `consolidate` / `evolve` 在 A4 弱模型下自动走 delegation 路径（超出
   `delegation_threshold` 的操作改用 `a1_api`）。
3. `knowledge_terr` builtin：`web_search` + `document_fetch`，注册到 A4 的
   可用技能列表（A4 作为调用方，而非 A2）。
4. `framework.py` 在构造 WP4 时传入 A1 api + knowledge_terr 引用。

### Phase 5（项目讨论迁移）— Project to A1

**文件**：`autumn/core/framework.py`, `autumn/core/workspace/wp4.py`

`Autumn.setup_project()` / `draft_project_goals()` 系列方法改用 `self.wp1.api`
（A1）而非 `self.wp4.api`（A4）做对话推理部分；A4 仍做解析和写入。

---

## 5. 配置项（新增）

在 `BehaviorConfig`（`autumn/core/config.py`）中新增：

```python
# 0.3.0 合作型工作流
cooperative_workflow: bool = True    # 总开关；false = 退回 0.2.x 行为
a1_task_planning: bool = True        # Phase 3: A1 为复杂 task 生成计划
a3_lite_skills: list[str] = []       # Phase 2: A3 允许调用的 skill 白名单
a4_delegation_threshold: int = 2000  # Phase 4: prompt 超过多少 tokens 走 delegation
a4_knowledge_terr: bool = False      # Phase 4: 是否为 A4 注册 knowledge_terr
```

`.env.example` 中对应暴露：

```bash
COOPERATIVE_WORKFLOW=true
A1_TASK_PLANNING=true
A3_LITE_SKILLS=recall,remember,get_time
A4_DELEGATION_THRESHOLD=2000
A4_KNOWLEDGE_TERR=false
```

---

## 6. 不做的事（范围约束）

本 RFC 不包含：

- **Terr 能力感知路由的完整实现**：已由 `rfc-terr-mcp-workflow.md` 覆盖，作为
  Phase 1 能力感知 Selector 的前置依赖之一，两个 RFC 共用 §4.2 设计。
- **A2 ReAct 循环的结构性修改**：WP2 的 Agent 逻辑（步数、工具调度）不变；
  只增加 `plan_hint` 和 `supervise_channel` 两个接入点。
- **异步消息总线 / 事件队列**：直接消息通道通过同步引用实现，不引入 broker。
- **A4 换用强模型**：delegation 路径复用 A1 api；A4 的 ModelConfig 不变。
- **WP2/WP3 的记忆区域（Mom2/Mom3）归属变更**：记忆区归属不动。

---

## 7. 开放问题

| # | 问题 | 当前倾向 |
|---|------|---------|
| 7.1 | A1 计划的粒度：单句概要 vs 编号步骤列表 | 编号步骤列表，注入 WP2 system hint |
| 7.2 | Supervise channel 默认开还是关？ | 默认关，由 `a1_task_planning=true` 隐式开启 |
| 7.3 | A3 Lite Skills 由框架自动推断还是纯白名单？ | 先用白名单（更可控），后续可以自动化 |
| 7.4 | delegation_threshold 的单位：tokens 还是 chars？ | chars（避免 tokenizer 依赖），默认 2000 |
| 7.5 | WP4→WP1 的执行摘要写 Mom1 还是 shared？ | shared；Mom1 是 A1 私有，摘要应跨 WP2/WP3 可见 |

---

## 8. 实现顺序与里程碑

```
Phase 0: WP1 全模块连接        ← 所有后续 Phase 的依赖
Phase 1: Selector 任务边界修正  ← 独立，可与 Phase 2 并行
Phase 2: A3 Lite Toolset       ← 依赖 Phase 0
Phase 3: A1 计划与监督          ← 依赖 Phase 0 + Phase 1
Phase 4: A4 工具增强            ← 依赖 Phase 0
Phase 5: 项目讨论迁移           ← 依赖 Phase 0（最低优先级）
```

所有 Phase 均在 `claude/v0.3.0` 分支完成，通过 pytest 全量测试后合并 `main`。

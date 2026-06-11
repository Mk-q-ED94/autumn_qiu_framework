# RFC: 四维记忆（4D Memory）

> 状态：草案（Draft） · 范围：`autumn/core/memory` · 不改核心代码，仅定义设计
>
> 本文提出把 Autumn 的记忆从「被压扁成单一权重的被动存储」重构为**四个正交维度
> 的活性记忆单元**：aim（为什么）、content（是什么）、use（怎么用）、time（何时
> 触发）。time 维是关键——它把记忆从「被查到才出现」（pull）升级为「条件满足就
> 激活」（push），并由它来调度前三维的逻辑。

---

## 1. 背景与动机

### 1.1 现状：记忆被压扁成一个标量

今天一条记忆是 `MemoryEntry`（`autumn/core/memory/base.py:26`），字段有 `content`、
`importance`、`tags`、`meta`、`timestamp`、`expires_at`。检索与淘汰几乎只看一个数：

- `recall` 按 `(-importance, -timestamp)` 排序（`base.py:418`）——重要度是主键，时间只是 tiebreak；
- `_evict` 按 `effective_importance` 保留高分项（`base.py:142`）；
- `effective_importance(now, half_life)` 让重要度随年龄半衰减（`base.py:67`）。

也就是说，「这条记忆为何存在」「该怎么用」「被用过没有」全都塌缩进了 `importance`
这一个标量，或者塞进无结构的 `tags`/`meta`。系统**没有**任何关于「用途」「使用方式」
「使用历史」的一等概念。

### 1.2 现状：记忆是纯拉取（pull）

`recall(query, k)`（`base.py:362`）是唯一的取记忆入口——必须有人拿 query 主动来搜，
记忆才会出现。没有任何机制让一条记忆「在合适的时刻自己冒出来」：

- 不能表达「这条提醒应该在每次进入某 mission 时触发」；
- 不能表达「这条约束在改动部署配置时必须被强制注入」；
- 不能表达「这条偏好用过三次都有用，应该更主动地参与上下文」。

四维记忆要补的正是这两个缺口：**把单标量拆成四个正交维度**，并**把 time 维做成
主动触发器**。

---

## 2. 概念：四维记忆

每条记忆不再是被动记录，而是一个带激活策略的单元，由四个维度构成：

| 维度 | 一句话 | 角色 | 类比 |
|------|--------|------|------|
| **aim**（目的） | 这条记忆**为什么**存在 | **关联门**：判断它是否与当前目标/上下文对齐 | WHY |
| **content**（内容） | 这条记忆**是什么** | **载荷**：被激活后提供的数据 | WHAT |
| **use**（使用） | 这条记忆**该怎么用**、**用得如何** | **处理器 + 使用账本**：激活后如何应用，以及历史使用反馈 | HOW |
| **time**（时间） | 这条记忆**何时、何种情况**该触发前三维 | **调度器**：带权时间轴上的触发条件 | WHEN |

核心关系：**time 是指挥，aim 是门禁，content 是数据，use 是动作 + 反馈**。
time 维决定「该不该响、响多强」，aim 维决定「对不对路」，命中后用 use 维规定的方式
把 content 应用到当前轮，并把这次使用回写进 use 维的账本。

激活打分（直觉式）：

```
activation(e, now, ctx) = w_time(e.trigger, now, ctx)  # 该不该触发，权重多少
                        × align(e.aim, ctx)          # 目的是否对齐（0 则否决激活）
                        × (1 + utility(e.use))       # 历史使用效用（增益，非门禁）

若 activation > 0：按 e.use.mode 把 e.content 施加到当前轮，并 e.use.touch()
```

这把今天的 `recall`（importance×timestamp 两因子）推广为**四因子、且可被时间主动
触发**的模型。query 检索只是其中一种 `ctx`；turn 边界、定时、情境事件都是 `ctx`。

---

## 3. 与现有架构的对应

| 维度 | 现有雏形 | 全新部分 |
|------|----------|----------|
| aim | `tags` / `meta`（无结构） | 结构化 `Aim`，可绑定 `ProjectGoals`（`project.py:54`）/ workspace / intent |
| content | `content` / `text` + 向量索引 ✓ | 基本沿用 |
| use | 无 | **处理协议**（mode）+ **使用统计**（count/last_used/reward）——完全新增 |
| time | `effective_importance(half_life)` 衰减、`expires_at` TTL | 从「衰减权重」升级为「**触发条件**」：定时 / 周期 / 情境线索 + 权重 |
| 激活引擎 | 无（只有 pull `recall`） | 每轮/按事件评估 time 触发、点燃 aim→content→use 的引擎（落在 WP4） |

结论：数据结构上 **content 基本已有、time 有一半**；真正要新建的是 **aim 结构化、
use 双重语义、time 的触发语义，以及一个激活引擎**。

---

## 4. 数据模型

> 设计原则：所有新字段都有默认值，使旧 `MemoryEntry` 反序列化后**行为与今天完全
> 一致**（aim 空、use 为纯 context、time 退化为现有衰减）。向后兼容是硬约束。

```python
# autumn/core/memory/dimensions.py  （新文件，纯数据 + 纯函数，无 I/O）

from dataclasses import dataclass, field
from enum import Enum

# ── aim 维：为什么存在 ──────────────────────────────────────────────
@dataclass
class Aim:
    """记忆的目的——用作激活时的关联门。"""
    intent: str = ""                 # 自由意图标签，如 "user_preference" / "deploy_fact"
    goal_ref: str | None = None      # 绑定 ProjectGoals(master/long/short) 或 workspace id
    scope: list[str] = field(default_factory=list)  # 适用上下文（tag/关键词）

    def align(self, ctx: "ActivationContext") -> float:
        """0=完全不相关（否决激活），1=完全对齐。具体打分见 §5.2。"""
        ...

# ── use 维：怎么用 + 用得如何（两者都要）────────────────────────────
class UseMode(str, Enum):
    CONTEXT   = "context"    # 注入到当前轮的 prompt 上下文
    REMIND    = "remind"     # 作为显式提醒浮出
    CONSTRAIN = "constrain"  # 作为规则/护栏强制注入
    SUMMARIZE = "summarize"  # 喂给 consolidate 做整合

@dataclass
class UseStats:
    """使用账本——回答『用得如何』。"""
    count: int = 0               # 被激活/命中的次数
    last_used: float | None = None
    reward: float = 0.0          # 反馈信号（命中后是否有用），可正可负

@dataclass
class Use:
    """记忆的使用方式（处理协议）+ 使用统计。"""
    mode: UseMode = UseMode.CONTEXT
    weight: float = 1.0          # 该方式的应用强度
    template: str | None = None  # 可选的格式化/指令模板
    stats: UseStats = field(default_factory=UseStats)

    def utility(self) -> float:
        """历史使用效用，参与激活打分。越常用且反馈越正 → 越高。见 §5.3。"""
        ...

    def touch(self, now: float, reward: float = 0.0) -> None:
        """记一次使用：count+1、更新 last_used、累计 reward。"""
        ...

# ── time 维：何时触发（带权时间轴）──────────────────────────────────
@dataclass
class Trigger:
    """带权时间轴上的触发条件。综合衰减/定时/周期/情境线索给出触发权重。"""
    half_life: float | None = None     # 衰减半衰期（沿用现有语义）
    not_before: float | None = None    # 定时：最早可激活时间
    expires_at: float | None = None    # TTL（从 MemoryEntry 迁入）
    every: float | None = None         # 周期：每隔 N 秒可再次触发
    cues: list[str] = field(default_factory=list)  # 情境线索（匹配 ctx 即加权）
    base_weight: float = 1.0

    def weight(self, created_at: float, now: float, ctx: "ActivationContext",
               last_used: float | None = None) -> float:
        """返回 0..N 的触发权重；0 表示此刻不应触发。见 §5.1。
        取标量（created_at/last_used）而非 entry，保持本模块与存储层解耦。"""
        ...
```

`MemoryEntry` 的演进（保留现有字段，新增三块；`importance` 保留为 time/use 的一个
输入而非唯一权重）：

```python
@dataclass
class MemoryEntry:
    id: str
    content: Any                 # content 维（已有）
    timestamp: float             # 创建时间（已有）
    importance: float = 1.0      # 保留：作为 time.base_weight 与 pin 的来源
    tags: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    # —— 四维新增 ——
    aim:     Aim     = field(default_factory=Aim)
    use:     Use     = field(default_factory=Use)
    trigger: Trigger = field(default_factory=Trigger)  # time 维（避开 stdlib time 命名）
```

> 迁移：现有 `expires_at` 并入 `Trigger.expires_at`；`importance>=PIN_THRESHOLD`
> 的「置顶」语义映射为 `Trigger.half_life=None`（不衰减）+ 高 `base_weight`。
> `to_dict/from_dict` 增加 `_v=2`，遇到旧记录（无 aim/use/time）按默认值补齐。

---

## 5. 激活机制

激活是四维模型的引擎。它统一了两种取记忆方式：

- **pull（拉取）**：用户/工作区拿 query 来搜 → query 进入 `ActivationContext`；
- **push（触发）**：每轮开始或某事件发生 → turn/event 进入 `ActivationContext`。

```python
@dataclass
class ActivationContext:
    """一次激活评估的上下文。pull 与 push 共用同一结构。"""
    now: float
    query: str | None = None        # pull 模式有；push 模式可空
    goal: str | None = None         # 当前目标/mission/project
    cues: list[str] = field(default_factory=list)  # 当前情境关键词
    workspace: str | None = None    # mom1/mom2/mom3/...
```

### 5.1 time 维：触发权重 `w_time`

```
w_time = 0                                   若 now < not_before（未到点）
       = 0                                   若 expires_at 已过（已死）
       = 0                                   若设了 every 且距 last_used 不足 every（冷却中）
否则:
  w = base_weight
  w *= decay(now - timestamp, half_life)     有 half_life 则按年龄衰减，否则 1
  w *= (1 + cue_match(cues, ctx.cues))        情境线索命中则加权
  return w
```

`decay(age, h) = 0.5 ** (age/h)`，与现有 `effective_importance` 一致（`base.py:67`），
保证不配置触发字段时 time 维退化为今天的行为。

### 5.2 aim 维：关联门 `align`

`align` 返回 `[0,1]`，**为 0 直接否决激活**（即便 time 维想触发）：

```
align = 1.0                          若 aim 为空（无目的约束 → 永远对齐，兼容旧数据）
      = 1.0                          若 ctx.goal 命中 aim.goal_ref
      = jaccard(aim.scope, ctx.cues) 否则按 scope 与情境的重叠度
```

> 与 Mom1 受控访问（另一分支 `claude/mom1-access-control`）的协同：aim.goal_ref 可
> 携带 workspace 归属，激活引擎据此天然遵守 WP1/2/3 的可见性边界。

### 5.3 use 维：效用 `utility`（两者都要）

use 维**既**规定「怎么用」（`mode`/`template`，在激活后施加），**又**贡献「用得如何」
（`stats`，在激活前打分）：

```
utility = log1p(count) * (1 + clamp(reward, -0.5, +1.0))
```

含义：被用得越多、反馈越正 → 效用越高 → 越容易再次被激活（正反馈）；反馈为负则抑制。
首次出现（count=0）效用为 0，不靠使用历史，仅靠 time×aim 决定是否激活。

### 5.4 激活循环（落在 WP4）

WP4（`workspace/wp4.py`）是激活引擎的自然归宿：它已持有全部 zone 且掌管 A4，并有
审计日志。

- **pull（P3 已实现）**：`WP4.activate(query, area, tags, k, reward, reinforce)`
  调 zone 的 `recall`（开关开时即 §6 的四因子排序），命中后通过
  `MemoryArea.reinforce(ids, reward)` **回写 `use.touch()`**，闭合正反馈环。返回的
  每个 entry 自带 `use.mode`，告诉调用方如何施加。`recall` 保持纯读，强化收敛到
  `reinforce` 这一个加锁写回原语；KV/向量合成 id 不匹配历史项，自然被忽略，可安全
  传整批 recall 结果。

  ```python
  entries = await zone.recall(query, k=k, tags=tags)      # 4D 排序（开关开时）
  if reinforce and entries:
      await zone.reinforce([e.id for e in entries], reward=reward)  # use.touch 回写
  await self._log("activate", area, {"query": query, "hits": len(entries)})
  return entries
  ```

- **push（P4 待做）**：在 WP1 每轮开始（`wp1.py:130` `process_with_trace` 入口）插一个
  无查询的 history 扫描版 activate（`trigger.weight` 闸门 + `aim.align` 否决 +
  `use.utility` 增益），把 CONSTRAIN/REMIND 类记忆注入到当轮 prompt。**默认关闭**，
  由配置开关启用，避免给现有流程加成本。

> **reward 来源**：P3 先把 `reward` 作为参数（默认 0.0，仅记一次使用）。后续可由
> Checker 通过/失败信号自动驱动——通过则 +reward、失败则 -reward，形成「有用的记忆
> 自动上浮、误导的记忆自动下沉」的闭环。

### 5.5 use.mode 的施加语义

| mode | 激活后做什么 |
|------|--------------|
| `CONTEXT` | 把 content 追加进当前轮上下文（等价今天 recall 的注入） |
| `REMIND` | 作为显式「提醒」段落浮出（可在 trace 里单列一个 stage） |
| `CONSTRAIN` | 作为硬规则注入到 system 段，参与 Checker 校验 |
| `SUMMARIZE` | 标记为 consolidate 的优先候选，喂给 A4 整合（`base.py:486`） |

---

## 6. 对 recall / evict 的改造（P2 已实现）

两处改造统一由 `BehaviorConfig.fourd_memory_enabled` 开关控制，经各 zone 构造参数
`fourd_enabled` 透传到 `MemoryArea`（与 `decay_half_life` 同一套路径）。**开关关 =
与今天逐字节一致。**

- **recall**（`MemoryEntry.activation`）：开关开时排序键从 `(-importance, -timestamp)`
  改为 `(-activation, -timestamp)`，其中
  `activation = trigger.weight × (importance×decay) × align × (1 + utility)`。
  - **有查询上下文**：用 `ActivationContext(query, cues=tags)` 评估；trigger 闸门 +
    cue 加权、aim 关联门（0 否决并沉底）、use 效用增益都生效。
  - KV/向量命中是**空维度合成项** → 退化为各自的 importance，故 KV 仍最高优先、
    向量项行为不变；只有带注解的真实历史项会重排。
  - `recall` 保持**纯读**：`use.touch()` 正反馈（P3 已实现）收敛到独立的加锁写回
    原语 `MemoryArea.reinforce(ids, reward)`，由 `WP4.activate` 在命中后调用（见 §5.4），
    避免在每次读路径都强制写回。
- **_evict**（`MemoryEntry.retention_score`）：开关开时保留键从 `effective_importance`
  改为 `retention_score = effective_importance × (1 + utility)`——**上下文无关**，
  刻意**不**用 `align`/`trigger`：那两维管「何时相关」，不该决定「是否值得留存」
  （否则一条暂不匹配当前上下文的高价值记忆会被误删）。`is_pinned` 仍无条件保留。
  效果：常被有效使用的记忆即使 importance 普通也更难被淘汰。

两处都保证：**不设任何四维字段时，打分退化为今天的结果**（align=1、utility=0、
trigger.weight=1 → recall 退化为 importance×decay、evict 退化为 effective_importance），
现有测试在开关关/开（且数据未注解）两种情形下都不受影响。

---

## 7. 配置与开关

`BehaviorConfig`（`config.py:105`）新增（全部默认保守，关掉即等于今天）：

```python
fourd_memory_enabled: bool = False     # 总开关：启用四维打分（recall/evict）
fourd_push_on_turn:  bool = False      # 每轮主动触发（CONSTRAIN/REMIND 注入）
use_reward_decay:    float = 0.0       # reward 随时间衰减的半衰期，0=不衰减
```

环境变量 `FOURD_MEMORY_ENABLED` / `FOURD_PUSH_ON_TURN` / `USE_REWARD_DECAY`，
经 `_to_bool`/`_to_float` 解析（与现有 knob 一致）。

---

## 8. 向后兼容与迁移

1. **数据**：`MemoryEntry.to_dict/from_dict` 增加版本位 `_v=2`（P1 已实现）。旧记录
   （无 aim/use/trigger）与无 `_m` 的 legacy 记录都按默认值补齐。`expires_at` 暂仍留在
   `MemoryEntry` 上（`is_expired` 不变）；`Trigger.expires_at` 独立存在，待触发引擎接入
   时再统一，避免本阶段动 TTL 语义。
2. **行为**：四维总开关默认 `False`。开关关闭时 recall/evict 走原路径，激活引擎不挂载。
3. **API**：`append_history` 增加可选参数 `aim=/use=/trigger=`，不传则用默认——现有
   调用点（`wp1.py:170`、`wp4.py` 等）零改动。
4. **测试**：现有测试在开关关闭下全绿（P0–P2 实测 666 通过）；四维行为另起测试文件覆盖。

---

## 9. 分阶段落地

| 阶段 | 内容 | 风险 | 状态 |
|------|------|------|------|
| **P0** | 本 RFC + `dimensions.py` 纯数据/纯函数 + 单元测试（不接 recall） | 极低 | ✅ 已完成 |
| **P1** | `MemoryEntry` 扩展 + 序列化版本化 + 默认值兼容；现有测试全绿 | 低 | ✅ 已完成 |
| **P2** | recall/evict 切到四因子打分（开关后）；新增打分测试 | 中 | ✅ 已完成 |
| **P3** | WP4 `activate()` + pull 接入；use.touch 正反馈闭环 | 中 | ✅ 已完成 |
| **P4** | push（每轮触发，CONSTRAIN/REMIND 注入）+ trace 可视化 + 客户端 UI | 中高 | ⏳ 待做 |

每阶段独立可合并、可回滚；P0/P1 不改变任何运行时行为，P2 起的行为变化全部由
`fourd_memory_enabled` 开关守护（默认关）。

---

## 10. 开放问题

1. **push 的成本**：每轮对一个 zone 全量评估 time 触发是 O(N)。N 受 `history_limit`
   （默认 50）限制，单 zone 可接受；但若扩展到跨 zone/项目，需要按 `not_before`/
   `every`/`cues` 建桶索引，避免全表扫描。P4 再优化。
2. **reward 从哪来**：谁给「这次使用有用吗」的反馈？候选：Checker 通过/失败信号、
   用户显式反馈、下一轮是否复用同一记忆。建议 P3 先接 Checker 信号，自动闭环。
3. **aim.goal_ref 的命名空间**：与 `ProjectGoals`、workspace、terr 的 id 如何统一？
   建议用 `"<kind>:<id>"`（如 `goal:master`、`ws:mom2`、`terr:time`）。
4. **CONSTRAIN 的强制程度**：仅注入 system 段，还是参与 Checker 硬校验、不满足就重试？
   关系到 `checker.py` 的改动面，P4 再定。
5. **time 与 use 的耦合**：`every` 的冷却用 `use.stats.last_used` 判断——这让 time 维
   依赖 use 维的账本。需确认这种「触发节流」是期望语义（本 RFC 假设是）。

---

## 11. 附：端到端示例

```python
# 存：一条"部署约束"记忆——目的是守护 mission "ship-v2"，每次改部署配置时强制注入
await mom1.append_history(
    "生产库必须走只读副本，不得直连主库",
    aim=Aim(intent="deploy_guardrail", goal_ref="goal:ship-v2", scope=["deploy", "db"]),
    use=Use(mode=UseMode.CONSTRAIN, weight=2.0),
    trigger=Trigger(cues=["部署", "数据库", "deploy", "db"], half_life=None),  # 不衰减
)

# 取（push）：进入一轮"修改部署配置"的任务时，激活引擎自动触发
ctx = ActivationContext(now=time.time(), goal="goal:ship-v2", cues=["部署", "db"],
                        workspace="mom2")
fired = await wp4.activate(ctx, area="mom1")
# → 这条 CONSTRAIN 记忆被注入当轮 system 段，use.count+1
```

对照今天：上面这条记忆只能靠某人恰好 `recall("部署")` 才可能被搜到，且无法表达
「强制约束」「改部署时才触发」「越用越稳」——这正是四维要解决的。

---

## 12. 决策记录

- **use 维语义**：采纳「两者都要」——既是处理协议（mode/template，激活后施加），
  又是使用账本（stats，激活前打分 + 命中后回写）。
- **time 维角色**：采纳「主动触发器」——决定何时何种情况触发前三维，而非仅作衰减
  权重；现有衰减是其退化形态。
- **落地形态**：先出本 RFC，不改核心代码；按 §9 分阶段推进。

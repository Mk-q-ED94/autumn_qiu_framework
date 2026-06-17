# RFC: 让 Terr 域与 MCP 深度参与工作流（Terr/MCP-in-the-loop）

> 状态：草案（Draft）· 目标里程碑：0.3.0 · 范围：`autumn/core/workspace/{wp1,wp2,wp3}`,
> `autumn/core/components/{selector,agent,terr}`, `autumn/core/framework.py`,
> `autumn/server/integrations.py`
>
> 本文提出把 **Terr（能力域）** 和 **MCP 集成** 从「只挂在 WP2 上的一个常开工具袋」
> 升级为**贯穿路由的一等能力抽象**：让 A1 在路由时就「看见」有哪些能力域、让 A3 的
> mission 路径不再静默吞掉需要工具的请求、并让工具暴露随回合自适应而非全量铺平。

---

## 1. 背景与动机

CLAUDE.md 对 Terr 的描述是：

> 一个 **Terr（域）** 把相关的 tools/skills/MCP 客户端打包成**一个能力域**，一次调用注册。
> 模型看到扁平的 tool/skill schema；**Terr 的描述会被surfaced 进系统提示**。

代码层面这条链路是**接通的**，但只接到了 WP2 一处。对照设计原意——Terr 作为「路由
可以推理的能力抽象」——目前的实现是**浅的**：它只是被拍平成 WP2 的一个常开工具袋，
工作流的其它环节（A1 路由、A3 mission）对它完全无感知。下面三个断点是这次重构要修的。

### 1.1 断点一：Terr 的「域」身份在注册时被拍平

`Terr` 构造时把 `name`/`description` 盖到每个子 tool/skill 上
（`terr.py:37-39` 的 `source_terr` / `source_terr_description`），随后注册时所有
tool/skill 被打散进一个扁平字典 `PluginLoader._registry`（`loader.py:28`）。完整的
`Terr` 对象虽然保留在 `_terrs`（`loader.py:40`），但运行时**从不**用它来组装 prompt——
只有桌面端的 `describe_terrs()` UI 读它（`framework.py:374-406`）。域分组在进入工作流
的那一刻就丢了；运行时只能靠每个 callable 上的 `source_terr` 反查归属。

### 1.2 断点二：Terr 描述只到 A2，A1/A3 看不到

把 Terr 描述送进系统提示的唯一位置是 `Agent._build_system`（`agent.py:158-162`，
那段 "Loaded capability domains"），而**全框架只有 WP2 会构造 `Agent`**
（`wp2.py:236-243`）。

- **A1（Selector/路由）**只做纯文本分类（`selector.py:6-101`、`wp1.py:25-32`），
  提示里**零** Terr/工具信息。它在判定 direct/convert、task/mission 时，
  **完全不知道连了什么集成、有哪些能力域**。
- **A3（WP3/mission）**全是裸 `api.complete()`（`wp3.py:48-86`），**没有任何工具访问**。

### 1.3 断点三：工具暴露不随回合变化，task-type 只改措辞

`ToolProvider` 的签名是 `Callable[[], tuple[list[Tool], list[Skill]]]`
（`wp2.py:19`）——**不接任何参数**，结构上就不可能感知当前回合 / 任务 / 路由结果。
每个 WP2 回合拿到的是「所有已启用 Terr 的工具全集」（`_collect_plugins`，
`framework.py:443-460`）。所谓 CODE / SEARCH / WRITE / DATA / GENERAL 的 task-type
hint（`wp2.py:21-27`）**只往提示里追加一句话，不启用/禁用任何工具**。唯一真正的过滤是
人工在 UI 上整体开关某个 Terr（`PATCH /terrs/{name}` → `framework.py:604-609`），
跟路由器毫无关系，是运维配置而非回合自适应。

### 1.4 后果：mission 误判会静默吞掉整类请求

断点二、三叠加产生一个**静默失败**：用户问「帮我看一下我的 GitHub PR」，若 A1 把它
判成 **mission**，就交给 A3——而 A3 没有任何工具，只能凭空「对话式」作答，
**连好的 GitHub MCP 工具一个都用不上**。能否用上工具完全取决于 A1 有没有恰好分类成
task，而 A1 做这个判断时手里**连「有哪些工具可用」的信息都没有**。这正是「Terr/MCP
没有深度参与工作流」的根因。

---

## 2. 目标

1. **A1 可见能力**：路由判定时，Selector / 路由提示中带一份精简的能力域摘要，让
   「是否存在相关工具」成为 task/mission 与 direct/convert 判定的输入。
2. **A3 不再吞工具**：mission 路径在识别到「需要外部能力」时，能回退到 convert→WP2，
   不再让需要工具的请求落进无工具的死路。
3. **回合自适应的工具门控**：`ToolProvider` 能接收回合上下文，让路由结果驱动「这一回合
   启用哪些 Terr / 工具子集」，真正实现 Terr 作为路由抽象——同时保留「全量」作为安全默认。
4. **不破坏现状**：以上都要可开关、默认行为与今天等价或更优，老用法零改动可跑。

非目标：本 RFC 不引入工具的语义向量召回 / 学习式选择（留待后续）；不改 MCP bridge 的
传输层；不动 4D 记忆。

---

## 3. 与现有架构的对应

| 现状 | 问题 | 本 RFC 的改法 |
|------|------|---------------|
| `Terr` 注册即拍平进 `_registry`，域身份只剩 `source_terr` 反查 | A1/A3 无法把「域」当作推理单元 | 暴露一个稳定的 `capability_digest()`：从 `_terrs` 派生「域名 + 描述 + 代表性工具」摘要 |
| `Selector` 只收 `api`（`wp1.py:112`） | 路由对能力无感知 | 给 Selector / 路由提示注入 `capability_digest()` |
| `WP3Mis` 纯 `api.complete` | mission 路径无工具、无回退 | 增加「需要工具则 convert」的判定与回退路径 |
| `ToolProvider = Callable[[], ...]`（`wp2.py:19`） | 工具暴露不随回合变化 | 改为 `Callable[[ToolContext], ...]`，`_collect_plugins` 按上下文过滤；旧的无参形态保留兼容 |
| `is_terr_enabled` 仅人工全局开关（`loader.py:49`） | 没有回合级门控 | 在全局开关之上叠加「本回合相关 Terr 集合」的软门控 |

---

## 4. 设计

### 4.1 能力摘要 `capability_digest()`

在 `Autumn` 上新增一个方法，从 `_terrs`（而非扁平 registry）派生路由可读的摘要：

```python
@dataclass
class CapabilitySummary:
    terr: str                 # 域名
    description: str          # Terr.description
    sample_tools: list[str]   # 代表性工具名（截断，避免提示膨胀）
    enabled: bool             # 当前是否启用（沿用 is_terr_enabled）

def capability_digest(self, *, enabled_only: bool = True) -> list[CapabilitySummary]:
    ...
```

- 只读、便宜、无副作用；可在每次路由前调用。
- 是 A1 看见能力的**唯一**数据源，避免把几十个工具 schema 灌进路由提示。
- 渲染成提示时做长度预算（域数量上限 + 每域工具名上限），防止 token 膨胀。

### 4.2 A1：把能力摘要喂给路由（断点二的主修）

- `Selector` 构造时可选接收 `capabilities: list[CapabilitySummary]`（`wp1.py:112` 处装配），
  其分类提示（`selector.py`）加一节「Available capability domains」，并明确：
  *当请求明显需要某个域的能力时，倾向判为 task（→WP2，可调用工具），而不是 mission*。
- `_AUTO_ROUTE_SYSTEM`（`wp1.py:25-32`）的 direct/convert 判定同样注入摘要：
  *若 direct 回答需要外部能力而当前直答路径无工具，则倾向 convert*。
- 纯分类语义不变，只是多了一个输入维度；无能力连接时摘要为空，行为回落到今天。

### 4.3 A3：mission 不再静默吞工具（断点二的兜底）

- `WP3Mis.answer_directly` / `convert_to_task`（`wp3.py:48-86`）增加一个轻判定：
  当 mission 实际需要工具时，返回「建议转 task」的信号，由 WP1 据此回退到 convert→WP2。
- 这样即便 A1 误判成 mission，请求也能被纠回有工具的路径，而不是凭空作答。
- 该回退默认开启，可由 `BehaviorConfig` 开关关闭（保守用户可保留纯对话 mission）。

### 4.4 回合自适应工具门控（断点三）

把 `ToolProvider` 从无参升级为接收一个轻量上下文：

```python
@dataclass
class ToolContext:
    task_type: TaskType | None = None
    relevant_terrs: frozenset[str] | None = None   # None = 不限制（=今天的全量行为）
    query: str | None = None

ToolProvider = Callable[[ToolContext], tuple[list[Tool], list[Skill]]]
```

- `_collect_plugins(ctx)`（`framework.py:443-460`）在现有「Terr 全局启用」过滤之上，
  再叠加 `ctx.relevant_terrs` 软门控：给定集合则只收这些域的工具；为 `None` 时**完全等价
  于今天的全量行为**（这是默认与安全网）。
- `relevant_terrs` 由 A1 的路由结果填充（基于 §4.2 的能力摘要），实现「分类→选域→给工具」。
- **向后兼容**：保留对无参 `ToolProvider` 的支持（WP2 调用处做 arity 适配），老插件 / 测试零改动。

### 4.5 数据流（目标态）

```
用户输入
  └─ WP1/A1: Selector(capability_digest) ──► task? mission?
        ├─ task    ──► relevant_terrs 选域 ──► WP2: _collect_plugins(ToolContext)
        │                                         └─ Agent 只拿到相关域的工具（+全量兜底）
        └─ mission ──► WP3/A3: 需要工具? ──是──► 回退 convert ──► WP2（同上）
                                     └──否──► 对话直答（同今天）
```

---

## 5. 配置与开关

在 `BehaviorConfig`（`autumn/core/config.py`）下新增（命名待定）：

| 开关 | 默认 | 作用 |
|------|------|------|
| `route_capability_aware` | `true` | A1 路由是否注入能力摘要（§4.2） |
| `mission_tool_fallback` | `true` | A3 识别到需要工具时回退 convert（§4.3） |
| `turn_scoped_tools` | `false` | 是否启用回合级 Terr 门控（§4.4）；关闭=全量铺平（今天） |

`turn_scoped_tools` 初期默认 **关**，先把 §4.2/§4.3（低风险、堵洞）落稳，门控作为可选增强
灰度推进。

---

## 6. 向后兼容与迁移

- `capability_digest()` 是纯新增，不影响任何现有调用。
- `ToolProvider` 升级为接受 `ToolContext`，但 WP2 调用处对「无参 provider」做兼容适配；
  `_collect_plugins` 在 `relevant_terrs=None` 时与今天逐字节等价。
- 三个新开关默认值保证：未配置时 §4.2/§4.3 生效（更优）、§4.4 关闭（与今天一致）。
- 桌面端 / web 端的 Terr 开关（`PATCH /terrs/{name}`）语义不变，仍是全局基线，回合门控叠加其上。

---

## 7. 分阶段落地

| 阶段 | 内容 | 风险 | 验收 |
|------|------|------|------|
| **P0** | `capability_digest()` + `CapabilitySummary`，单测覆盖 | 极低（纯新增只读） | 摘要正确反映已注册/启用 Terr |
| **P1** | A1 能力感知路由（§4.2）：Selector + 路由提示注入摘要 | 低 | 「看我的 GitHub PR」类请求稳定判为 task |
| **P2** | A3 工具回退（§4.3）：mission→convert 兜底 | 低 | mission 误判不再静默吞工具 |
| **P3** | 回合级工具门控（§4.4）：`ToolContext` + provider 升级，默认关 | 中（触及 WP2 热路径） | 开关开启时只暴露相关域；关闭时与今天等价 |

P0–P2 是堵洞主线（投入产出比最高）；P3 是接近设计原意的增强，灰度推进。

---

## 8. 开放问题

1. **能力摘要的粒度**：路由提示里放「域 + 描述」够不够，还是要带代表性工具名？过细会膨胀
   token，过粗会让 A1 选不准。倾向「域名 + 一句描述 + ≤3 个代表工具名」，可配上限。
2. **`relevant_terrs` 的判定主体**：复用 Selector 一次产出（省一次调用），还是独立一步？
   倾向复用，把「选域」做成 Selector 输出结构的一个可选字段。
3. **多域请求**：一个请求跨多个域（先搜后写）时，`relevant_terrs` 取并集即可，但要防止
   退化成「几乎全量」让门控失去意义——需要一个「不确定就放宽到全量」的保守回退。
4. **全量兜底的边界**：P3 门控误把相关域漏掉时如何兜底？倾向「Agent 循环中若模型明确需要
   某未暴露能力，可触发一次性放宽」——但这增加复杂度，可能留到 0.3.x。
5. **与 4D push 的关系**：WP3 的 `turn_context`（4D 推送）已经会往 mission 提示注入记忆；
   能力摘要与它的注入点/预算如何协调，避免提示拥挤。

---

## 9. 决策记录

- **为什么不直接给 A3 工具？** 给 A3 挂 Agent 会让两个执行器职责重叠、提示与 trace 复杂化。
  让 mission 在需要工具时**回退到 WP2** 更干净，符合现有「WP2 是唯一执行器」的分工。
- **为什么回合门控默认关？** WP2 的工具组装是热路径且是当前行为的事实契约；先用零风险的
  §4.2/§4.3 堵住最痛的洞，门控作为可选增强灰度，避免一次性改动过大。
- **为什么用能力摘要而非把工具 schema 灌给 A1？** 路由只需要「有没有相关域」这一粗粒度信号；
  灌全量 schema 会让路由提示爆炸且拖慢分类。摘要是路由层正确的抽象粒度。

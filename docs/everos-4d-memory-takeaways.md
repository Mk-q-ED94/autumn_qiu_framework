# EverOS 对 Autumn 4D 记忆的可取之处

> 调研对象：[`EverMind-AI/EverOS`](https://github.com/EverMind-AI/EverOS) v1.0.0（⭐7.4k，Apache-2.0）
> 对照对象：Autumn 4D 记忆（`autumn/core/memory/`、`docs/rfc-4d-memory.md`）
> 结论先行：**EverOS 强在「持久化与抽取」，Autumn 强在「激活语义」。两者互补，不是替代关系。**
> 下面的建议主要落在 Autumn 较弱的持久化/抽取轴上，不动 Autumn 已领先的 4D 激活模型。

---

## 0. TL;DR

| 维度 | EverOS | Autumn 现状 | 谁更强 |
|------|--------|------------|--------|
| 存储可读性 | Markdown 即真相，可 grep/Git/Obsidian | dict / sqlite 后端，不可读 | **EverOS** |
| 检索 | BM25 + 向量 + 标量，一次查询 | 向量 + tag + KV（**无词法/BM25**） | **EverOS** |
| 记忆类型 | Episode/AtomicFact/Foresight/Profile/Case/Skill | 扁平 `MemoryEntry` + tags | **EverOS** |
| 双轨 | 用户记忆 vs Agent 记忆 分轨抽取 | 按 workspace 分区（Mom1/2/3/shared） | 各有侧重 |
| 索引一致性 | cascade 守护进程，最终一致 + LSN 崩溃恢复 | 写路径内联索引（`auto_index`） | **EverOS** |
| 自进化 | 重复模式→可复用 skill | 仅 consolidate（摘要） | **EverOS** |
| 提示词管理 | 三层 prompt slot 覆盖 | consolidate 提示词硬编码 | **EverOS** |
| 算法边界 | everalgo：纯函数、无 I/O、无内联 prompt | `dimensions.py` 已纯；抽取逻辑混在 `base.py` | 部分领先 |
| **激活语义** | 以拉取为主（search） | **aim 门 / use 模式 / time 触发 + push 主动注入** | **Autumn** |
| **主动触发（push）** | 无 | CONSTRAIN/REMIND 每轮自动浮出 | **Autumn** |
| **跨域访问控制** | scope 过滤 | Mom1 受控访问（A1 裁决 + A4 中介） | **Autumn** |
| **使用反馈闭环** | 弱 | `use.reward` → utility 正反馈 | **Autumn** |

---

## 1. 值得借鉴（按优先级）

### P1-A · Markdown 即真相（最大收益）

**EverOS 做法**：所有记忆持久化为 `.md` 文件 + frontmatter，可读、可编辑、可 grep、可
Git 版本化、可在 Obsidian 打开。SQLite 存状态、LanceDB 存索引，**两者都可从 md 重建**。

**Autumn 现状**：`DictBackend` / `sqlite_backend` 存的是不透明序列化数据
（`base.py` 的 `to_dict`/`from_dict`）。用户无法直接查看或编辑自己的记忆。

**为什么值得**：可读记忆带来信任、可调试、可手改、可纳入版本控制——对一个「四维活性
记忆」尤其重要，因为 aim/use/trigger 的注解正适合落在 frontmatter 里被人看见和修正。

**映射到 Autumn**：
- 新增 `autumn/core/memory/backends/markdown_backend.py`，实现 `MemoryBackend` ABC
  （`get/set/delete/keys/clear`），一个 entry 一段，frontmatter 携带 `aim/use/trigger`：
  ```markdown
  ---
  id: a1b2c3
  importance: 1.0
  tags: [deploy, db]
  aim: {intent: deploy_guardrail, goal_ref: "goal:ship-v2", scope: [deploy, db]}
  use: {mode: constrain, weight: 2.0, stats: {count: 3, reward: 1.0}}
  trigger: {cues: [部署, db], half_life: null}
  ---
  生产库必须走只读副本，不得直连主库
  ```
- 目录沿用现有 zone 命名：`<root>/{mom1,mom2,mom3,shared}/entry-*.md`。
- 原子写入：tmp + fsync + rename（抄 EverOS 的写路径保证）。
- **风险低**：`MemoryArea` 已经面向 `MemoryBackend` 抽象编程，换后端不改上层。

### P1-B · 混合检索补齐 BM25 / 词法层

**EverOS 做法**：BM25（Tantivy）+ 向量 ANN + 标量过滤在**一次 LanceDB 查询**内完成。

**Autumn 现状**：`recall()`（`base.py:455`）= 精确 KV + tag 过滤 + 向量搜索，**没有词法/
BM25 召回**。对专有名词、ID、代码符号这类「语义相近但字面才命中」的查询会漏。

**映射到 Autumn**：
- 在 `hybrid_backend.py` 或 `vector_backend.py` 旁加一个 SQLite **FTS5** 索引做 BM25 召回，
  与现有向量结果在 `recall()` 里融合（RRF 或加权）。
- 融合后仍走现有 4D 排序：合成项维度为空 → 退化为各自分数，**与今天兼容**。

### P1-C · 抽取/整合提示词外置为 slot

**EverOS 做法**：三层 prompt slot（包内默认 → app 覆盖 → 运行时覆盖），算法不内联 prompt。

**Autumn 现状**：`consolidate()` 的 system prompt 硬编码在 `base.py:705`；`recall` 合成
prompt 硬编码在 `skills.py:106`。

**映射到 Autumn**：抽出 `autumn/core/memory/prompts/*.yaml`（或 Python 常量模块），
`consolidate`/`recall` 接收可选 `prompt` 参数，默认取包内值。零行为变化，但可被产品层覆盖
（中英、风格、领域）。

---

### P2-A · 记忆类型化（Episode / AtomicFact / Profile …）

**EverOS 做法**：记忆分型——Episode（每日对话）、AtomicFact（离散事实）、Foresight（预测）、
Profile（用户画像）、Case（Agent 任务经验）、Skill（程序性记忆）。

**Autumn 现状**：单一 `MemoryEntry` + 自由 `tags`，类型靠约定。

**为什么值得**：**AtomicFact** 抽取尤其有用——把一轮对话裂解为可独立检索、独立打分的
原子事实，比整段 episode 召回更精准；这也正好喂给 Autumn 的 `aim.scope`/`trigger.cues`。

**映射到 Autumn**：先用 tag 约定轻量落地（`tags=["atomic_fact"]` / `["episode"]` /
`["profile"]`），配一个抽取 pass（见 P2-B）。无需改数据结构即可起步。

### P2-B · 索引与写路径解耦（cascade-lite）

**EverOS 做法**：写 md 强一致后立即返回；独立 cascade 守护进程 watch md → diff → 同步
LanceDB，**最终一致**；LanceDB 不可用时变更进 SQLite 队列，恢复时按 LSN 重放，**不阻塞响应**。

**Autumn 现状**：`append_history()`（`base.py:415`）在写路径内联 `auto_index` 向量索引——
embedding 服务慢或挂会直接拖慢/影响写入。

**映射到 Autumn**：把向量索引从 `append_history` 移到一个轻量异步队列（不必上 watcher 守护
进程）；md/dict 写成功即返回，索引失败进队列重试。贴合 RFC §10「push 成本」对异步化的预期。

---

### P3-A · 自进化：重复模式 → 可复用 skill

**EverOS 做法**：从真实使用中抽取常用 skill，重复模式自动变成可复用 workflow，无需重训。

**Autumn 现状**：只有 `consolidate()` 做摘要；没有「模式→skill」的提炼。但 Autumn **已具备
闭环所需的信号**：`use.reward` / `use.utility` 正反馈（`dimensions.py:176`）+ RFC §5.4 规划的
Checker 反馈。

**映射到 Autumn**：加一个离线 evolution pass——扫描高 `utility`、高 `count`、同 `aim.intent`
的记忆簇，用 A4 提炼成一条 `UseMode.CONSTRAIN`/程序性 skill 写回 Mom 区。这正是 RFC「开放
问题 2（reward 从哪来）」的自然延伸。

### P3-B · 用户画像轨（Profile）与 scope 正交

**EverOS 做法**：用户记忆（Episode/Profile）与 Agent 记忆（Case/Skill）**分轨独立抽取**；
检索可按 `user_id/agent_id/app_id/project_id/session_id` 正交过滤。

**Autumn 现状**：按 workspace 分区（Mom1/2/3/shared）+ project scope；没有显式「用户画像」
概念，也没有 user/session 维度的正交检索。

**映射到 Autumn**：在 shared/Mom1 内增设 `profile` 类记忆（单文件重写式，类似 EverOS 的
`user.md`），承载稳定的用户偏好；检索时作为高 `importance` 常驻项。session 维度可由 tag 承载。

### P3-C · frontmatter 字段四级保护（若采纳 P1-A）

EverOS frontmatter 有 L1 只读 / L2 系统 / L3 业务 / L4 用户 四级字段保护。一旦 Autumn 走
Markdown 可编辑路线，需要同样的护栏：`id`/`timestamp` 只读，`use.stats` 系统管，`aim`/`tags`
用户可改。这是 P1-A 的配套，不单独立项。

---

## 2. 不要照抄的部分（Autumn 已更强）

- **激活模型本身**：Autumn 的 aim=门 / use=模式+账本 / time=调度器 + `activation = w_time ×
  align × (1+utility)` 比 EverOS 以检索为中心的模型更进一步。**保留。**
- **push 主动触发**：EverOS 基本是 pull（search）。Autumn 的 push 引擎（CONSTRAIN/REMIND 每轮
  自动注入、`render_push_context`）是真正的差异化能力。**这是 Autumn 的护城河，继续投入。**
- **跨域访问控制**：Mom1 受控访问（A1 裁决、A4 中介、审计日志）比 EverOS 的 scope 过滤更强。
- **使用反馈闭环**：`use.reward → utility` 的正反馈让「有用的记忆自动上浮」，EverOS 未强调。

一句话：**别为了 EverOS 的存储优雅而丢掉 Autumn 的激活智能。两条轴叠加才是目标形态。**

---

## 3. 建议路线图

| 优先级 | 项目 | 改动面 | 风险 | 收益 | 状态 |
|--------|------|--------|------|------|------|
| **P1-A** | Markdown 后端 + 4D frontmatter | `markdown_backend.py` + config/framework 可插拔 | 低（后端可插拔） | 可读/可编辑/可版本化记忆 | ✅ 已实现 |
| **P1-B** | recall 补 BM25/FTS5 词法层 | `lexical_backend.py` + recall RRF 融合 | 中 | 专名/ID/符号召回 | ✅ 已实现 |
| **P1-C** | 抽取/整合提示词外置 slot | `prompts.py` + `base.py`/`skills.py` | 低 | 可覆盖、可本地化 | ✅ 已实现 |
| **P2-A** | 记忆类型化（先 tag 约定 + AtomicFact） | 抽取 pass | 中 | 更精准的原子召回 | ⏳ |
| **P2-B** | 索引与写路径解耦（异步队列） | `base.py` | 中 | 写入不被 embedding 拖慢 | ⏳ |
| **P3-A** | 自进化：模式→skill（接 reward 闭环） | 新增 evolution pass | 中高 | 越用越聪明 | ⏳ |
| **P3-B** | 用户画像轨 + user/session scope | `shared.py`/`project.py` | 中 | 稳定偏好常驻 | ⏳ |

**P1 进度（全部完成）**：P1-A/B/C 已在 `claude/4d-memory-p1` 分支实现并测试
（全套 830 passed，新增 37）。三个开关全部默认关、向后兼容：
- `STORAGE_BACKEND=markdown` — 启用 Markdown 可读后端（默认 `sqlite` 不变）。
- `LEXICAL_RECALL_ENABLED=true` — 启用 BM25/FTS5 词法层，与向量结果经 RRF 融合进 recall
  （未启用时 recall 与向量-only 旧路径逐字节一致；FTS5 不可用时自动降级为空结果不崩溃）。
- P1-C 提示词 slot 默认值逐字复制，`consolidate(system_prompt=...)` 可覆盖。

---

## 附：参考来源

- EverOS 架构：`https://github.com/EverMind-AI/EverOS/blob/main/docs/architecture.md`
- EverOS README（记忆模型/存储布局）：`https://github.com/EverMind-AI/EverOS/blob/main/README.md`
- everalgo 算法边界：`https://github.com/EverMind-AI/EverAlgo`
- Autumn 4D RFC：`docs/rfc-4d-memory.md`
- Autumn 记忆实现：`autumn/core/memory/{dimensions,base,mom1,shared,skills}.py`

# Roadmap — 0.3.3 之后（Post-0.3.3 TODO）

> 状态：**规划中（Planning）**· 起点版本：0.3.3 · 目标：把工程质量与三端覆盖、API 稳定性对齐，铺向 1.0
> 范围：`web/frontend/` · `windows/` · `desktop/` · `autumn/core/workspace/wp4.py`
>       `autumn/core/components/mcp_stdio.py` · `autumn/plugins/loader.py` · `autumn/server/app.py` · `docs/`

本文记录 0.3.3 深度审计之后的下一阶段待办。背景判断：**核心 Python 框架的工程质量
（1039 条测试、安全层、架构一致性）已经超过版本号暗示的成熟度，而客户端覆盖
（尤其 Web 端）和公开 API 的稳定性还没跟上**。下面按优先级分层，每项给出动机与完成判据。

图例：⬜ 未开始 · 🟡 进行中 · ✅ 已完成

---

## P0 — 收尾欠账（挡在 1.0 门口的硬债）

### 🟡 1. Web 前端视觉对齐到 "Paper & Clay"
- **现状**：`web/frontend/` 仍是偏离的暗色开发主题，`CLAUDE.md` 与 `autumn-design-taste` 都把它标成已知债。
- **动作**：以 `desktop/AutumnApp/DesignSystem/Tokens.swift` 为唯一真相源，把 clay 强调色
  `#CC6645`、发丝边框、暖纸侧栏迁到 `web/frontend/src/styles.css` 的 CSS 变量；逐屏改造
  （chat / composer / memory panel / pipeline strip / settings / sidebar）。
- **判据**：三端截图并排，Web 端读起来与 macOS 端是「同一个产品」；
  `autumn-web-design-engineer` 的 pre-flight checklist 全过。
- **进展（2026-06-22）**：Web 的 chat / composer / memory / pipeline / settings / sidebar
  已完成 Paper & Clay 令牌化、明暗主题、窄屏抽屉与键盘可达性改造；Vite 生产构建和
  WebKit 桌面明暗 / 390px 移动端渲染验收通过，无横向溢出、框架错误层或控制台错误。
- **落地**：PR #37（merge commit `be56bf4`）。
- **待收口**：补三端并排截图。

### ⬜ 2. Windows WinUI 客户端落地对齐（PR #20）
- **现状**：客户端存在但挂在 `claude/windows-client`，未合并，三端尚未真正打齐。
- **动作**：人审 WinUI（Linux 不能编译），确认 `windows/.../App.xaml` 镜像了 Tokens；
  用户本地构建验证后决定合并节奏。
- **判据**：三端共享同一 HTTP/SSE 契约且视觉一致；PR #20 有明确的 merge-or-defer 结论。

---

## P1 — 质量与稳定性（让工程质量配得上版本号）

### 🟡 3. 三端 E2E / 冒烟测试
- **现状**：1039 条测试全在 `tests/` 的单元/集成层，没有任何客户端 E2E。
- **动作**：对 HTTP/SSE 契约写一套契约测试（启服务 → 跑一轮 direct + convert + recall/remember
  → 断言 SSE 帧序）；至少 Web 端加 Playwright 冒烟。
- **判据**：CI 多一个 e2e job，能抓到「前后端契约漂移」。
- **进展（2026-06-22）**：
  - HTTP/SSE 契约测试层（35 条，`tests/test_http_sse_contract.py`）：健康探针、认证门控、
    503/413 防护、/process + /trace + /intent 响应结构、SSE 帧序（chunk → trace → [DONE]）、
    流内错误帧格式、Terr 管理、记忆端点、安全响应头、枚举值全集。
  - 契约漂移守卫（2 条，`tests/test_contract_doc_sync.py`）：把 `docs/http-sse-contract.md`
    钉到 FastAPI 实时路由表——新增端点漏写文档、或文档引用已删端点，都会让普通 `pytest` 失败。
    当前 47 真实路由与文档 `METHOD /path` 引用**双向一一对应**。这条直接命中判据里的「契约漂移」。
- **待收口**：Web 端 Playwright 冒烟 + 独立 CI e2e job（需浏览器环境）。

### ✅ 4. API 冻结边界决策（为 1.0 铺路）
- **现状**：0.3.3 仍是 0.x，无向后兼容承诺。
- **动作**：盘点对外面（server 路由 + `Autumn` 公共方法）哪些算稳定 API、哪些是内部实现；
  写一份 `docs/api-stability.md` 标注 stable / experimental。
- **判据**：有明确的「1.0 要冻结这些、可以继续动那些」清单。
- **落地**：`docs/api-stability.md`（本批次 commit）。三级分类（🟢 Stable / 🟡 Experimental /
  🔴 Internal）覆盖包导出、`Autumn` 方法、`BehaviorConfig` 字段、HTTP 端点、内置工具名；
  并附 §6「走向 1.0 的收敛清单」，明确每个 🟡 升 🟢 的前置条件。

### ✅ 5. HTTP/SSE 契约文档化
- **现状**：契约散落在 `autumn/server/app.py`，三端各自实现。
- **动作**：把端点、SSE 事件类型、心跳/取消语义写成单一 `docs/http-sse-contract.md`
  （含计费-取消保护那条边界）。
- **判据**：新客户端能只看文档接入。
- **落地**：`docs/http-sse-contract.md`（本批次 commit）。覆盖全部 40+ 端点、SSE 帧格式与
  心跳/断线/计费语义、安全边界（SSRF / 大小限制 / 响应头过滤）、枚举值表。

---

## P2 — 功能完善（深化已有子系统）

### ✅ 6. WP4 / 4D push 引擎查缺补漏
- **动作**：核对 `autumn/core/workspace/wp4.py` 里 `fourd_push_on_turn`、Mom1 access broker、
  project intelligence、audit log 是真实现还是占位；补齐 push 激活路径的测试。
- **判据**：push 路径有端到端用例，不只是 config flag。
- **审计结论（2026-06-22）**：WP4 全表面均为**真实现，无占位**——push 引擎
  （`activate_push` + `render_push_context`，gating/ranking/audit 齐全）、Mom1 access broker
  （`Mom1AccessBroker.request`，有 `test_memory_access*`）、project intelligence（0.3.3 已迁
  A1 转发器）、audit log（`activate_push` 落审计）、archive（`record_execution_summary`）。
- **落地**：`tests/test_push_end_to_end.py`（8 条端到端用例）——经 `Autumn.process()` 真实
  WP1→WP3/WP2 链路验证 CONSTRAIN/REMIND 记忆的文本确实进入模型 system prompt；覆盖
  direct/task 双路由、push-off 负例、CONTEXT 不推、以及 `stream`/`stream_with_trace` 两个
  流式入口同样喂 push。同时修正 `test_memory_4d_push.py` 顶部「尚未接入工作流」的过期注释。
  测试计数 1074 → 1082。
- **关联**：满足 `docs/api-stability.md` §6 中「4D push 端到端用例」前置条件，为 `fourd_*` /
  `/memory/4d/*` 在 1.0 升 🟢 解锁。

### ✅ 7. MCP stdio 客户端的重连/退避
- **现状**：0.3.3 已修 `connect()` 的子进程泄漏与幂等守卫，但断连后无重连。
- **动作**：给 `StdioMCPClient` 加可选的 disconnect 检测 + 指数退避重连（失败容忍，
  降级到「无该 Terr」）。
- **判据**：模拟 server 崩溃 → 客户端不挂死、能恢复或干净降级。
- **落地**：`StdioMCPClient` 新增 `max_reconnect_attempts`（默认 0=关，行为与今日逐字一致）
  + `reconnect_backoff_base/cap`。新增 `MCPConnectionLost(RuntimeError)` 专指传输层断裂
  （EOF / 断管 / 无进程），与「服务端返回的工具 error」区分——只有前者触发重连。请求在
  传输丢失时按指数退避 respawn 并重试，超预算则抛出让上层降级；`disconnect()` latch `_closed`
  阻止意外复活；`_generation` + lock 处理并发重连竞态。`connect()` 期间 `_connecting` 守卫
  防止握手自我递归重连。长生命周期的 `mcp_codebase_memory` 工厂已默认开启
  `max_reconnect_attempts=3`。测试 `tests/test_mcp.py` +5（崩溃恢复 / 预算耗尽降级 /
  默认关闭向后兼容 / 关闭后不复活 / 幂等守卫保持）。计数 1082 → 1087。

### ✅ 8. 插件 / Terr 热重载
- **动作**：评估 `PluginLoader` 支持运行时重载 `.py`（无需重启 server），至少做到
  add/remove Terr 不重启。
- **判据**：改一个 builtin Terr → 走 `/config/apply` 或专用端点生效。
- **落地**：
  - `Autumn.remove_terr(name)`（异步，注销 tools/skills + 断开该域 MCP + 丢弃记录，幂等）
    与 `Autumn.reload_terr(terr)`（热替换同名域，保留 enabled/disabled 状态）。
  - `PluginLoader` 加 per-Terr 归属追踪（`register_terr(..., extra_callables=)` 含 MCP-bridged
    工具名）+ `remove_terr` 精确注销；`reload_from_directory` 重新执行插件 `.py` 并按增量
    增删 Terr。`load_from_directory` 改为每次从源码 `compile`，绕开 `.pyc` 的
    (mtime,size) 缓存，使**同长度小改动**（如改一字符）也能生效。
  - `_collect_plugins` 每轮新解析，故移除的能力在下一轮即从模型视野消失。
- **测试**：`tests/test_terr.py` +8（add→remove 注销 / 未知域 no-op / remove 断开 MCP /
  reload 换定义 / reload 保留禁用态 / reload 换 MCP / 目录重载拾取编辑 / 目录重载删除消失的域）。
  计数 1087 → 1095。
- **备注**：服务端默认不挂插件目录，故 HTTP「专用端点」留作薄封装的后续；框架/loader 层
  的运行时增删改能力已完整且经测试。

---

## P3 — 工程化与可观测

### ⬜ 9. 性能基准
给 4D recall（dict/lexical/vector/hybrid/markdown 五后端）建 benchmark，盯住向量召回在大库下的延迟。

### 🟡 10. CI 增强
现有 ruff + pytest 3.11/3.12 之上加覆盖率门槛 + e2e job。
- **进展（2026-06-22）**：`pytest-cov>=5` 进 dev 依赖；`[tool.coverage.run]` 配置 source + omit
  `__main__.py`；CI `pytest` 步骤加 `--cov=autumn --cov-fail-under=85`（基线 87.7%，门槛 85%
  留 ~3% 弹性）；两个 Python 版本矩阵均执行覆盖率检查。
- **待收口**：e2e job（需浏览器环境 / 独立 runner）。

### ✅ 11. 可观测性
server 加结构化日志 + 基础 metrics（每轮 token、各 WP 耗时），为后续多用户做铺垫。
- **落地**：`autumn/server/app.py` 加 `logging.getLogger("autumn.server")`，替换启动 `print()`
  为结构化 `logger.warning/info`；`_Metrics` 数据类（runs / errors / prompt_tokens /
  completion_tokens / started_at）挂在 `app.state.metrics`；`_record_run()` 在每轮完成后累计
  token 并发 `logger.info`；`_record_failure()` 同步增 error 计数并 `logger.error`；
  新增 `GET /metrics` 端点暴露快照（需认证）。
  `/process` 内部改为调用 `process_with_trace()` 以获得 stage-level token 数据，
  相关测试（`test_server.py` / `test_server_projects.py`）同步更新。
  测试 +4（`test_http_sse_contract.py`），计数 1097 → 1101。
- **契约文档**：`docs/http-sse-contract.md` 新增 §4.2 `GET /metrics`，双向守卫自动验证。

---

> 维护约定：完成一项后把 ⬜ 改成 ✅ 并在该项下补一行「落地：<commit/PR>」；
> 大主题（如三端对齐、1.0 API 冻结）单独开 RFC，本文只做索引。

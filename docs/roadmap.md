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
- **待收口**：补三端并排截图，并在提交或 PR 生成后按本文约定回填「落地」引用。

### ⬜ 2. Windows WinUI 客户端落地对齐（PR #20）
- **现状**：客户端存在但挂在 `claude/windows-client`，未合并，三端尚未真正打齐。
- **动作**：人审 WinUI（Linux 不能编译），确认 `windows/.../App.xaml` 镜像了 Tokens；
  用户本地构建验证后决定合并节奏。
- **判据**：三端共享同一 HTTP/SSE 契约且视觉一致；PR #20 有明确的 merge-or-defer 结论。

---

## P1 — 质量与稳定性（让工程质量配得上版本号）

### ⬜ 3. 三端 E2E / 冒烟测试
- **现状**：1039 条测试全在 `tests/` 的单元/集成层，没有任何客户端 E2E。
- **动作**：对 HTTP/SSE 契约写一套契约测试（启服务 → 跑一轮 direct + convert + recall/remember
  → 断言 SSE 帧序）；至少 Web 端加 Playwright 冒烟。
- **判据**：CI 多一个 e2e job，能抓到「前后端契约漂移」。

### ⬜ 4. API 冻结边界决策（为 1.0 铺路）
- **现状**：0.3.3 仍是 0.x，无向后兼容承诺。
- **动作**：盘点对外面（server 路由 + `Autumn` 公共方法）哪些算稳定 API、哪些是内部实现；
  写一份 `docs/api-stability.md` 标注 stable / experimental。
- **判据**：有明确的「1.0 要冻结这些、可以继续动那些」清单。

### ⬜ 5. HTTP/SSE 契约文档化
- **现状**：契约散落在 `autumn/server/app.py`，三端各自实现。
- **动作**：把端点、SSE 事件类型、心跳/取消语义写成单一 `docs/http-sse-contract.md`
  （含计费-取消保护那条边界）。
- **判据**：新客户端能只看文档接入。

---

## P2 — 功能完善（深化已有子系统）

### ⬜ 6. WP4 / 4D push 引擎查缺补漏
- **动作**：核对 `autumn/core/workspace/wp4.py` 里 `fourd_push_on_turn`、Mom1 access broker、
  project intelligence、audit log 是真实现还是占位；补齐 push 激活路径的测试。
- **判据**：push 路径有端到端用例，不只是 config flag。

### ⬜ 7. MCP stdio 客户端的重连/退避
- **现状**：0.3.3 已修 `connect()` 的子进程泄漏与幂等守卫，但断连后无重连。
- **动作**：给 `StdioMCPClient` 加可选的 disconnect 检测 + 指数退避重连（失败容忍，
  降级到「无该 Terr」）。
- **判据**：模拟 server 崩溃 → 客户端不挂死、能恢复或干净降级。

### ⬜ 8. 插件 / Terr 热重载
- **动作**：评估 `PluginLoader` 支持运行时重载 `.py`（无需重启 server），至少做到
  add/remove Terr 不重启。
- **判据**：改一个 builtin Terr → 走 `/config/apply` 或专用端点生效。

---

## P3 — 工程化与可观测

### ⬜ 9. 性能基准
给 4D recall（dict/lexical/vector/hybrid/markdown 五后端）建 benchmark，盯住向量召回在大库下的延迟。

### ⬜ 10. CI 增强
现有 ruff + pytest 3.11/3.12 之上加覆盖率门槛 + e2e job。

### ⬜ 11. 可观测性
server 加结构化日志 + 基础 metrics（每轮 token、各 WP 耗时），为后续多用户做铺垫。

---

> 维护约定：完成一项后把 ⬜ 改成 ✅ 并在该项下补一行「落地：<commit/PR>」；
> 大主题（如三端对齐、1.0 API 冻结）单独开 RFC，本文只做索引。

# Autumn Desktop

SwiftUI macOS 客户端。通过 HTTP/SSE 与本地运行的 Autumn 服务器通信。

## 架构

```
┌────────────────────┐    HTTP / SSE     ┌──────────────────────┐
│   QcoworkDesktop   │ ────────────────► │   autumn.server      │
│   (SwiftUI app)    │                   │   FastAPI · :8765    │
└────────────────────┘                   └──────────┬───────────┘
                                                    │
                                          ┌─────────▼──────────┐
                                          │  Autumn 框架        │
                                          │  A1/A2/A3 + Mom1-3 │
                                          └────────────────────┘
```

## 前置条件

- macOS + Xcode 15 及以上
- [XcodeGen](https://github.com/yonaskolb/XcodeGen)：`brew install xcodegen`
- Python ≥ 3.11

## 1. 准备 Python 依赖

回到仓库根目录：

```bash
pip install -e ".[server]"
cp .env.example .env             # 可选：填写默认 A1/A2/A3 凭据
```

桌面 App 启动时会自动检测 `Server URL`。当地址是默认的
`http://127.0.0.1:8765` 且本地没有服务在运行时，App 会在仓库根目录自动执行：

```bash
python -m autumn.server
```

优先使用仓库下的 `.venv/bin/python`，否则回退到系统 `python3`。服务日志写入
`build/logs/autumn_server.log`。如果你想调试服务器或让外部客户端连接，也可以手动启动；默认监听
`http://127.0.0.1:8765`，可通过 `AUTUMN_HOST` / `AUTUMN_PORT` 环境变量覆盖：

```bash
AUTUMN_HOST=0.0.0.0 AUTUMN_PORT=9000 python -m autumn.server
```

健康检查：

```bash
curl http://127.0.0.1:8765/health
# {"status":"ok","configured":true}
```

## 2. 生成并打开 Xcode 工程

仓库根目录已经提供一键构建/运行脚本：

```bash
bash ./script/build_and_run.sh
```

如需手动打开 Xcode：

```bash
cd desktop
xcodegen generate
open QcoworkDesktop.xcodeproj
```

在 Xcode 中：

1. 选中 **QcoworkDesktop** target → **Signing & Capabilities**，设置你的 Team。
2. 顶部 destination 选 **My Mac**。
3. ⌘R 运行。

## 3. 在 App 内配置

打开左侧边栏的 **设置**：

- **本地服务** 会显示 App 自动启动或连接到已有本地服务器的状态。
- 确认 **Server URL** 指向你的服务器（默认 `http://127.0.0.1:8765`）。
- 为 **A1 / A2 / A3** 填写 API Key、Base URL、协议和模型。
- App 会在 Key / Base URL / 协议变化后向本地服务器请求模型列表并更新模型选择框。
- 可选打开 **A4（记忆模型）**：用于驱动 `recall` / `remember` 记忆 skill。常配本地廉价模型（Ollama / llama3.1）；本地协议留空 API Key 也可工作。
- 点 **应用配置**，看到「已应用」即可。
- 切回 **协作** 发送消息；每次回复下方会显示 WP1/WP2/WP3 的协作路径。
- 打开 **记忆** 浏览 Mom1-3 / Shared 历史（最新优先）：统计条显示总数 / 置顶 / 过期 / 四维注解数；当记忆区存在四维条目时会出现「约束 / 提醒 / 上下文 / 摘要」筛选芯片；展开条目可见四维卡片（aim / use / trigger，线索渲染为换行芯片）。

### 项目

侧边栏顶部的「新建项目」按钮可建立项目。每个项目带一段可选的 **项目指令**——发送消息时这段指令会自动以前缀方式注入到 Autumn，形成"项目级 system prompt"。把对话拖入/移入项目即可继承指令；未分组对话保持原行为。

## 端点速查

| Method | Path                    | 用途                                |
|--------|-------------------------|-------------------------------------|
| GET    | `/health`               | 健康检查 + 是否已配置               |
| POST   | `/models`               | 根据 API Key / Base URL / 协议获取模型列表 |
| POST   | `/config/apply`         | 将 A1 / A2 / A3 / A4 配置应用到本地服务器 |
| POST   | `/process`              | 同步执行，返回最终输出；JSON 可带 `route` |
| POST   | `/trace`                | 同步执行并返回输出、输入类型、路由和协作阶段（含 Agent 工具调用 `kind="tool"` 和 token 用量）|
| POST   | `/intent`               | 仅做 A1 分类，不执行——返回 inputType / taskType / route / 置信度 / reasoning |
| GET    | `/stream?input=...`     | SSE 流式分块；交替发 `{"chunk":...}` 与一个最终 `{"trace":...}` |
| GET    | `/terrs`                | 返回已注册的 Terr（能力域）摘要——tools / skills / mcps |
| GET    | `/memory/{area}/history`| `mom1` / `mom2` / `mom3` / `shared` 历史（`limit`/`offset` 分页）|
| GET    | `/memory/stats`         | WP4 全区统计总览                    |
| GET    | `/memory/{area}/stats`  | 单区统计（总数 / 置顶 / 过期 / 标签等）|
| POST   | `/memory/{area}/consolidate` | 用 WP4/A4 归并记忆区（未配 A4 返回 400）|
| POST   | `/session/end`          | 清空短期记忆                        |

`route` 可选值：`auto`、`direct`、`convert`。桌面端设置页的「Mission 默认路由」会随每次请求传给服务器，覆盖服务器 `.env` 中的全局默认值。

所有 `/process` `/trace` `/intent` `/stream` 都接受可选 `project_instructions`（字符串）和 `project_id`（保留字段）。当 `project_instructions` 非空时，服务器把它包装成 `[项目指令]…[用户输入]…` 的格式后再喂给 Autumn。

## 键盘快捷键

| 快捷键 | 行为 |
|---|---|
| ⌘N | 新建对话 |
| ⌘⇧K | 清空当前对话 |
| ⌘⇧E | 结束会话（清空短期记忆） |
| ⌘L | 聚焦到输入框 |
| ⌘⇧I | 切换右侧检视面板 |
| ⌘, | 打开设置 |

## 模块化设计

App 按"职责"分目录组织，每个目录都可以独立替换或扩展。

| 目录 | 职责 | 何时编辑 |
|---|---|---|
| `DesignSystem/` | 颜色 / 字号 / 间距 / 圆角 / 阴影 / 动效 | 想统一调整视觉风格 |
| `DesignSystem/Components/` | `AutumnCard` / `AutumnBadge` / `AutumnChip` / `AutumnPrimaryButton` / `EmptyStateView` / `FlowLayout` | 想引入新原子组件 |
| `Chat/` | 聊天 VM + 视图 + 工作流时间线 | 改对话呈现 |
| `Conversations/` | 多对话持久化（UserDefaults JSON）+ 侧边栏列表 | 改对话存储/列表 UI |
| `Workspace/` | 工作区主布局 + 检视面板（状态/路由/模型卡） | 改主区域布局 |
| `Memory/` | Mom1/2/3/Shared 历史浏览 + 四维筛选与详情卡 | 改记忆 UI |
| `Settings/` | A1/A2/A3 配置 + 持久化 | 改配置项或配置 UI |
| `Networking/` | `AutumnClient`（process/trace/stream/models/config/apply/memory）+ Codable 模型 | 服务器接口变更 |
| `Services/` | `LocalServerManager`（App 内拉起 Python 服务）/ `AutumnAppDelegate` | 改生命周期/进程管理 |
| `Commands/` | `AppCommands`（菜单 + 键位） | 加快捷键或菜单项 |
| `Onboarding/` | 首启引导页 | 改新用户欢迎流 |
| `Views/` | `SidebarView` 共享导航 | 改侧边栏结构 |
| `Models/` | `AppSection` / `MemoryModels` / `JSONValue` | 加跨模块数据模型 |
| `Resources/` | Info.plist / entitlements | 改权限或元数据 |

**修改 UI 风格**：只需编辑 `DesignSystem/Tokens.swift` 中的某个值（如把 `radius.lg` 从 14 改为 18），全局视觉自动更新。

**新增设计原子**：在 `DesignSystem/Components/` 下放新 SwiftUI View，遵循只引用 `Autumn.colors` / `Autumn.typography` / `Autumn.spacing` 的约定。

**新增功能模块**（例如插件管理）：
1. 新建目录 `Plugins/`
2. 添加新的 `AppSection` 枚举项 + `SidebarView` 自动包含
3. 在 `ContentView.detailView` 的 switch 加一个 case 指向新视图
4. XcodeGen 的 `sources: - path: AutumnApp` 会自动包含新文件

## 文件结构

```
desktop/
├── project.yml                          # XcodeGen 工程描述
├── README.md
└── AutumnApp/
    ├── AutumnApp.swift                  # @main
    ├── ContentView.swift                # NavigationSplitView + Onboarding gate
    ├── DesignSystem/
    │   ├── Tokens.swift                 # 颜色/字号/间距/动效集中定义
    │   └── Components/
    │       ├── AutumnCard.swift
    │       ├── AutumnBadge.swift
    │       ├── AutumnChip.swift
    │       ├── AutumnPrimaryButton.swift
    │       ├── EmptyStateView.swift
    │       └── FlowLayout.swift          # 标签/线索芯片换行布局
    ├── Models/
    │   ├── AppSection.swift             # 侧边栏选择
    │   └── MemoryModels.swift           # Mom1-3 + JSON 记忆条目 + 四维访问器
    ├── Views/
    │   └── SidebarView.swift            # 主导航 + 对话列表
    ├── Workspace/
    │   └── WorkspaceView.swift          # 协作工作台 + 可折叠检视面板
    ├── Memory/
    │   ├── MemoryView.swift             # Mom1-3/Shared 历史 + 四维筛选/详情卡
    │   └── MemoryViewModel.swift
    ├── Chat/
    │   ├── ChatMessage.swift
    │   ├── ChatViewModel.swift          # @MainActor，绑定 ConversationStore
    │   ├── ChatView.swift               # 聊天 UI（DesignSystem）
    │   └── WorkflowTraceView.swift      # 协作时间线（可折叠 + 动画）
    ├── Conversations/
    │   ├── Conversation.swift           # Codable 对话模型（含 projectID）
    │   └── ConversationStore.swift      # UserDefaults JSON 持久化 + 项目归属
    ├── Projects/
    │   ├── Project.swift                # Codable 项目模型 + 调色板
    │   ├── ProjectStore.swift           # UserDefaults JSON 持久化
    │   ├── ProjectEditorView.swift      # 创建/编辑项目（名称/指令/颜色）
    │   └── ProjectSidebarView.swift     # 侧边栏：项目分组 + 未分组对话
    ├── Networking/
    │   ├── AutumnClient.swift           # HTTP + SSE 客户端
    │   └── ChatModels.swift             # Codable 模型
    ├── Services/
    │   ├── LocalServerManager.swift     # 自动拉起 autumn.server
    │   └── AutumnAppDelegate.swift      # macOS 生命周期
    ├── Settings/
    │   ├── AppSettings.swift            # @Published + UserDefaults
    │   └── SettingsView.swift           # A1/A2/A3 配置 UI
    ├── Commands/
    │   └── AppCommands.swift            # 菜单 + 键盘快捷键
    ├── Onboarding/
    │   └── OnboardingView.swift         # 首启引导
    └── Resources/
        ├── Info.plist                   # NSAllowsLocalNetworking
        └── AutumnDesktop.entitlements   # 非沙盒 + network.client/server（本地开发工具需要 spawn Python）
```

App 以 **非沙盒** 形式构建（仍开启 Hardened Runtime），因为 `LocalServerManager` 需要从仓库根目录 spawn `python -m autumn.server` 并读仓库内文件，这两者都被 App Sandbox 拒绝。如果要走 App Store 分发，需要拆出一个走 XPC 的 helper 进程或改为完全外置的服务器。

## 常见问题

**Mac 弹出"该 App 想连接本地网络"?**
首次运行时正常，点同意。

**SSE 连接被中途切断?**
检查服务器日志；流式输出依赖底层模型 API 不超时，必要时调高 `URLSession` 超时（已设为 300 秒）。

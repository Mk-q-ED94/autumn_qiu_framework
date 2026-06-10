# Autumn Desktop (Windows)

WinUI 3 / .NET Windows 客户端。与 macOS 客户端共用同一套 HTTP/SSE 协议，连接本地运行的
Autumn 服务器。它是 `desktop/`（SwiftUI）在 Windows 上的原生对等实现。

## 架构

```
┌────────────────────┐    HTTP / SSE     ┌──────────────────────┐
│   AutumnDesktop    │ ────────────────► │   autumn.server      │
│   (WinUI 3 · .NET) │                   │   FastAPI · :8765    │
└────────────────────┘                   └──────────┬───────────┘
                                                    │
                                          ┌─────────▼──────────┐
                                          │  Autumn 框架        │
                                          │  A1/A2/A3 + Mom1-3 │
                                          └────────────────────┘
```

客户端启动时会自动检测 `Server URL`。当地址是默认的 `http://127.0.0.1:8765` 且本地无服务响应时，
`LocalServerManager` 会在仓库根目录以**无控制台窗口**的方式启动 `python -m autumn.server`。

## 前置条件

- Windows 10 (1809+) / Windows 11
- [.NET 8 SDK](https://dotnet.microsoft.com/download)
- Visual Studio 2022（含 **.NET 桌面开发** + **Windows App SDK** 工作负载），或命令行 `dotnet`
- Python ≥ 3.11（用于本地服务器）

## 1. 准备 Python 依赖

在仓库根目录：

```powershell
pip install -e ".[server]"
```

App 优先使用仓库下的 `.venv\Scripts\python.exe`（Windows 虚拟环境布局），否则回退到
`py -3`，再回退到 PATH 上的 `python`。

## 2. 构建并运行

```powershell
cd windows
dotnet build AutumnDesktop.sln -c Debug
dotnet run --project AutumnDesktop\AutumnDesktop.csproj
```

或用 Visual Studio 打开 `AutumnDesktop.sln`，选 `x64` 配置后 F5 运行。

> 默认以**非打包（unpackaged / framework-dependent）**方式构建，直接从文件夹运行，无需证书或
> MSIX 签名——与 macOS 端不走 App Store 的开发方式一致。如需 MSIX 分发，把 csproj 里的
> `WindowsPackageType` 改回 `MSIX` 并提供签名证书。

## 3. 在 App 内配置

打开左侧 **设置**：

- **本地服务** 显示 App 自动启动或连接已有服务器的状态，并内联展示服务端报错。
- 确认 **Server URL**（默认 `http://127.0.0.1:8765`）。
- 为 **A1 / A2 / A3** 填写 API Key、Base URL、协议和模型。
- 可选打开 **A4（记忆模型）**：驱动 `recall` / `remember` 记忆 skill；常配本地 Ollama，留空 Key 也可。
- 点 **应用配置**，看到「已应用」即可。
- 切到 **协作** 发送消息；回复下方的「协作路径」展开即为 WP1/WP2/WP3 的工作流追踪。
- **记忆** 页浏览 Mom1-3 + 共享区历史。

## Windows 框架适配

这些适配让 Python 框架在 Windows 上以每用户、可写的方式运行（不写入 `Program Files`）：

| 关注点 | 适配 |
|---|---|
| 解释器发现 | 优先 `.venv\Scripts\python.exe`，再 `py -3`，再 PATH `python` |
| 无控制台窗口 | 子进程 `CreateNoWindow=true` 启动，stdout/stderr 重定向到日志文件 |
| 每用户数据目录 | 通过 `AUTUMN_DATA_DIR=%APPDATA%\Autumn` 注入；框架的 `autumn.core.paths.resolve_data_path` 把相对的 `STORAGE_DB_PATH` 落到该目录 |
| 日志 | `%LOCALAPPDATA%\Autumn\logs\autumn_server.log` |
| 设置持久化 | `%APPDATA%\Autumn\settings.json`（非打包构建也可用） |

框架侧新增的跨平台 `autumn/core/paths.py` 同时服务 macOS / Linux / Windows——见仓库根 README。

## 模块化设计

按职责分目录，每个目录可独立替换或扩展（与 macOS 端一一对应）。

| 目录 | 职责 | 对应 macOS |
|---|---|---|
| `DesignSystem/` | 颜色 / 间距 / 圆角 / 格式化令牌（`Autumn.*`） | `DesignSystem/Tokens.swift` |
| `Models/` | 线协议 Codable 模型 + 导航/记忆枚举 | `Networking/ChatModels.swift`、`Models/` |
| `Networking/` | `AutumnClient`（HTTP + SSE，`IAsyncEnumerable`） | `Networking/AutumnClient.swift` |
| `Services/` | `LocalServerManager`（拉起 Python 服务，Windows 适配） | `Services/LocalServerManager.swift` |
| `Settings/` | `AppSettings` 持久化 + 配置 UI | `Settings/` |
| `Chat/` | 聊天 VM + 流式 + 工作流追踪 | `Chat/` |
| `Memory/` | Mom1-3 + 共享区历史 | `Memory/` |
| `Common/` | MVVM 转换器等公共件 | — |

**修改 UI 风格**：编辑 `DesignSystem/Tokens.cs` 的 `Autumn.*` 值，或 `App.xaml` 的画刷资源。

**新增功能模块**：
1. 新建目录（如 `Projects/`）放 `Page` + `ViewModel`
2. 在 `MainWindow.xaml` 的 `NavigationView` 加一个 `NavigationViewItem`
3. 在 `MainWindow.xaml.cs` 的 `Nav_SelectionChanged` 加一个 case

## 文件结构

```
windows/
├── AutumnDesktop.sln
└── AutumnDesktop/
    ├── AutumnDesktop.csproj            # net8.0-windows · WinUI 3 · 非打包
    ├── app.manifest                    # PerMonitorV2 DPI
    ├── App.xaml(.cs)                    # 应用入口 + 服务单例
    ├── MainWindow.xaml(.cs)            # NavigationView 外壳
    ├── DesignSystem/Tokens.cs          # 设计令牌
    ├── Common/Converters.cs            # XAML 值转换器
    ├── Models/
    │   ├── ChatModels.cs               # 线协议记录（snake_case ↔ C#）
    │   ├── AppSection.cs               # 导航 + 路由枚举
    │   └── MemoryModels.cs             # 记忆区 + 条目
    ├── Networking/AutumnClient.cs      # HTTP + SSE 客户端
    ├── Services/LocalServerManager.cs  # 自动拉起 autumn.server（Windows）
    ├── Settings/
    │   ├── AppSettings.cs              # JSON 持久化（%APPDATA%）
    │   ├── SettingsViewModel.cs        # 应用配置 / 连接检测
    │   └── SettingsPage.xaml(.cs)
    ├── Chat/
    │   ├── ChatMessage.cs
    │   ├── ChatViewModel.cs            # 流式 + 追踪
    │   └── ChatPage.xaml(.cs)
    ├── Memory/
    │   ├── MemoryViewModel.cs
    │   └── MemoryPage.xaml(.cs)
    └── Assets/autumn.ico
```

## 端点速查

与 macOS 端一致，见 [`../desktop/README.md`](../desktop/README.md) 的「端点速查」一节。
所有 `/process` `/trace` `/intent` `/stream` 都接受可选 `project_instructions` 与 `project_id`。

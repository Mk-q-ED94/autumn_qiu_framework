# Autumn Desktop

SwiftUI macOS 客户端。通过 HTTP/SSE 与本地运行的 Autumn 服务器通信。

## 架构

```
┌────────────────────┐    HTTP / SSE     ┌──────────────────────┐
│   AutumnDesktop    │ ────────────────► │   autumn.server      │
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
open AutumnDesktop.xcodeproj
```

在 Xcode 中：

1. 选中 **AutumnDesktop** target → **Signing & Capabilities**，设置你的 Team。
2. 顶部 destination 选 **My Mac**。
3. ⌘R 运行。

## 3. 在 App 内配置

打开 **设置** 标签页：

- **本地服务** 会显示 App 自动启动或连接到已有本地服务器的状态。
- 确认 **Server URL** 指向你的服务器（默认 `http://127.0.0.1:8765`）。
- 为 **A1 / A2 / A3** 填写 API Key、Base URL、协议和模型。
- App 会在 Key / Base URL / 协议变化后向本地服务器请求模型列表并更新模型选择框。
- 点 **应用配置**，看到「已应用」即可。
- 切回 **聊天** 标签页发送消息。

## 端点速查

| Method | Path                    | 用途                                |
|--------|-------------------------|-------------------------------------|
| GET    | `/health`               | 健康检查 + 是否已配置               |
| POST   | `/models`               | 根据 API Key / Base URL / 协议获取模型列表 |
| POST   | `/config/apply`         | 将 A1 / A2 / A3 配置应用到本地服务器 |
| POST   | `/process`              | 同步执行，返回最终输出；JSON 可带 `route` |
| GET    | `/stream?input=...`     | SSE 流式分块；query 可带 `route`    |
| GET    | `/memory/{area}/history`| `mom1` / `mom2` / `mom3` 历史       |
| POST   | `/session/end`          | 清空短期记忆                        |

`route` 可选值：`auto`、`direct`、`convert`。桌面端设置页的「Mission 默认路由」会随每次请求传给服务器，覆盖服务器 `.env` 中的全局默认值。

## 文件结构

```
desktop/
├── project.yml                          # XcodeGen 工程描述
├── README.md
└── AutumnApp/
    ├── AutumnApp.swift                  # @main
    ├── ContentView.swift                # TabView（聊天 / 设置）
    ├── Networking/
    │   ├── AutumnClient.swift           # HTTP + SSE 客户端
    │   └── ChatModels.swift             # Codable 模型
    ├── Services/
    │   └── LocalServerManager.swift     # App 启动时拉起本地 autumn.server
    ├── Chat/
    │   ├── ChatMessage.swift
    │   ├── ChatViewModel.swift          # @MainActor 流式逻辑
    │   └── ChatView.swift               # 聊天 UI
    ├── Settings/
    │   ├── AppSettings.swift            # @Published + UserDefaults
    │   └── SettingsView.swift           # 设置 UI
    └── Resources/
        └── Info.plist                   # NSAllowsLocalNetworking
```

## 常见问题

**Mac 弹出"该 App 想连接本地网络"?**
首次运行时正常，点同意。

**SSE 连接被中途切断?**
检查服务器日志；流式输出依赖底层模型 API 不超时，必要时调高 `URLSession` 超时（已设为 300 秒）。

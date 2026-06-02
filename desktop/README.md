# Autumn Desktop

SwiftUI 多平台客户端（iOS + macOS）。通过 HTTP/SSE 与本地运行的 Autumn 服务器通信。

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

## 1. 启动 Autumn 服务器

回到仓库根目录：

```bash
pip install -e ".[server]"
cp .env.example .env             # 填写 A1/A2/A3 凭据
python -m autumn.server
```

默认监听 `http://127.0.0.1:8765`。可通过 `AUTUMN_HOST` / `AUTUMN_PORT` 环境变量覆盖：

```bash
AUTUMN_HOST=0.0.0.0 AUTUMN_PORT=9000 python -m autumn.server
```

健康检查：

```bash
curl http://127.0.0.1:8765/health
# {"status":"ok","configured":true}
```

## 2. 生成并打开 Xcode 工程

```bash
cd desktop
xcodegen generate
open AutumnDesktop.xcodeproj
```

在 Xcode 中：

1. 选中 **AutumnDesktop** target → **Signing & Capabilities**，设置你的 Team。
2. 顶部 destination 选 **My Mac** 或 iOS 模拟器/真机。
3. ⌘R 运行。

## 3. 在 App 内配置

打开 **设置** 标签页：

- 确认 **Server URL** 指向你的服务器（默认 `http://127.0.0.1:8765`）。
- 点 **检测连接**，看到「已连接」即可。
- 切回 **聊天** 标签页发送消息。

## 端点速查

| Method | Path                    | 用途                                |
|--------|-------------------------|-------------------------------------|
| GET    | `/health`               | 健康检查 + 是否已配置               |
| POST   | `/process`              | 同步执行，返回最终输出              |
| GET    | `/stream?input=...`     | SSE 流式分块                        |
| GET    | `/memory/{area}/history`| `mom1` / `mom2` / `mom3` 历史       |
| POST   | `/session/end`          | 清空短期记忆                        |

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
    ├── Chat/
    │   ├── ChatMessage.swift
    │   ├── ChatViewModel.swift          # @MainActor 流式逻辑
    │   └── ChatView.swift               # 聊天 UI
    ├── Settings/
    │   ├── AppSettings.swift            # @Published + UserDefaults
    │   └── SettingsView.swift           # 设置 UI
    └── Resources/
        ├── Info.plist                   # NSAllowsLocalNetworking
        └── AutumnDesktop.entitlements   # network.client + sandbox
```

## 常见问题

**iOS 连不上 localhost?**
真机 iOS 不能访问 Mac 的 `127.0.0.1`。改用 Mac 的局域网 IP，例如 `http://192.168.1.10:8765`，并把服务器以 `AUTUMN_HOST=0.0.0.0 python -m autumn.server` 启动。

**Mac 弹出"该 App 想连接本地网络"?**
首次运行时正常，点同意。entitlements 已包含 `network.client`。

**SSE 连接被中途切断?**
检查服务器日志；流式输出依赖底层模型 API 不超时，必要时调高 `URLSession` 超时（已设为 300 秒）。

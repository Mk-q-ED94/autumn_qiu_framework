# 本地拉取 · 构建 · 测试全流程

每次远程分支更新后,把改动拉到本地并构建/测试的标准操作手册。

> 当前活动开发分支:**`claude/nifty-gauss-Pck8K`**(不是 `main`)。拉取时请指明此分支。

---

## 仓库的 4 个可独立构建部分

| 部分 | 路径 | 构建/测试方式 | 所在分支 |
|------|------|--------------|----------|
| Python 框架 + 服务器 | `autumn/` `tests/` | `pytest` / `ruff` | 全部分支 |
| macOS 客户端 | `desktop/` | XcodeGen + Xcode | 全部分支 |
| Web 前端 | `web/frontend/` | npm + vite | 全部分支 |
| Windows 客户端 | `windows/` | Visual Studio / dotnet | 仅 `claude/windows-client` |

### 两个必须知道的坑

- `.gitignore` 含 `desktop/*.xcodeproj/` —— **Xcode 工程文件不进 Git**,每次拉完代码都要重新
  `xcodegen generate`(`script/build_and_run.sh` 已包含这步)。
- `build/` 被忽略,构建日志写在 `build/logs/` 下。

---

## 0. 一次性设置(第一次才做)

```bash
cd autumn_qiu_framework

# Python 环境(放仓库根的 .venv,桌面 App 会优先用它启动服务)
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,server]"

# macOS 端工具链
brew install xcodegen            # Xcode 15+ 另需从 App Store 安装

# Web 端依赖
cd web/frontend && npm install && cd ../..
```

### 最小依赖清单

| 部分 | 必需 | 说明 |
|------|------|------|
| Python 框架 | Python ≥ 3.11、`httpx` | `pip install -e .` |
| 运行服务器 | + `fastapi` `pydantic<3` `uvicorn[standard]` | `pip install -e ".[server]"` |
| 跑测试 | + `pytest` `pytest-asyncio` | `pip install -e ".[dev]"` |
| 静态检查 | `ruff` | `pip install ruff` |
| macOS 客户端 | macOS 14+、Xcode 15+、XcodeGen | `brew install xcodegen` |
| Web 前端 | Node.js 18+、npm | `npm install` |

---

## 1. 每次更新的标准拉取动作

```bash
cd autumn_qiu_framework

# 1) 确认本地没有未提交改动(避免 pull 冲突)
git status

# 2) 拉取开发分支
git fetch origin claude/nifty-gauss-Pck8K
git checkout claude/nifty-gauss-Pck8K      # 第一次切换
git pull origin claude/nifty-gauss-Pck8K   # 之后每次更新

# 3) 看这次改了什么,决定下面跑哪几步
git log --oneline -5
git show --stat HEAD
```

`git show --stat HEAD` 的输出会告诉你改了哪个目录:
- 改 `desktop/` → 跑 **第 2 步**(macOS)
- 改 `autumn/` 或 `tests/` → 跑 **第 3 步**(Python)
- 改 `web/` → 跑 **第 4 步**(Web)

---

## 2. macOS 客户端:构建 + 验证

```bash
# 一条命令:重新生成工程 → 编译 → 启动 → 确认进程存活
bash ./script/build_and_run.sh --verify
```

脚本依次执行 `xcodegen generate` → `xcodebuild`(Debug / My Mac)→ `open` →
检查 App 是否秒退。构建日志在 `build/logs/build_and_run.log`。

其它模式:

```bash
bash ./script/build_and_run.sh            # 只构建并运行
bash ./script/build_and_run.sh --logs     # 运行并实时流式打印 App 日志
```

第一次建议在 Xcode 里手动跑一遍以确认签名:

```bash
cd desktop
xcodegen generate
open AutumnDesktop.xcodeproj
# Xcode 里:AutumnDesktop target → Signing & Capabilities → 设 Team
#          destination 选 My Mac → ⌘R
cd ..
```

> macOS 端纯 UI 验证**不强制启动后端** —— App 首启会自动从 `.venv` 拉起
> `python -m autumn.server`。要测完整对话流再去设置页填 A1/A2/A3。

---

## 3. Python 框架:测试 + 静态检查

```bash
source .venv/bin/activate          # 确保在虚拟环境里
pip install -e ".[dev,server]"     # 依赖有变动时才需重装

pytest -q                          # 全量测试(CI 同款命令)
ruff check autumn tests            # 静态检查(CI 同款命令)
```

快速冒烟测后端:

```bash
python -m autumn.server &          # 默认 127.0.0.1:8765
curl http://127.0.0.1:8765/health
# {"status":"ok","configured":...}
```

---

## 4. Web 前端

```bash
cd web/frontend
npm install            # package.json 有变动时才需要
npm run build          # tsc 类型检查 + vite 打包,能过即类型/构建 OK
npm run dev            # 本地开发服务器(热更新)
cd ../..
```

---

## 5. 一键全量验证(改动跨多个部分时)

```bash
cd autumn_qiu_framework
git pull origin claude/nifty-gauss-Pck8K

# 后端
source .venv/bin/activate && pytest -q && ruff check autumn tests

# 前端
( cd web/frontend && npm run build )

# macOS
bash ./script/build_and_run.sh --verify
```

---

## 常见问题速查

| 现象 | 处理 |
|------|------|
| `git pull` 报冲突 | 本地改过文件。`git stash` → pull → `git stash pop`;或 `git reset --hard origin/claude/nifty-gauss-Pck8K` 丢弃本地改动(确认不要了再用) |
| `xcodegen: command not found` | `brew install xcodegen` |
| 构建签名失败 | Xcode 里给 AutumnDesktop target 设一个 Development Team(个人 Apple ID 即可) |
| App 启动秒退 | 看 `build/logs/build_and_run.log` 末尾;通常是端口被占或 `.venv` 缺依赖 |
| 拉了代码但 UI 没变 | 多半忘了 `xcodegen generate`;直接用 `build_and_run.sh`,它会自动重生成 |
| Windows 端要测 | 在 `claude/windows-client` 分支,本分支没有,需单独 checkout |

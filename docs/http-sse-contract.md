# HTTP/SSE Contract

> 版本：`API_REVISION = 1`（见 `autumn/server/app.py`）  
> 适用服务器：`autumn/server/app.py` · `create_app()` · FastAPI  
> 默认端口：`8765`（`script/build_and_run.sh`）

客户端（macOS SwiftUI / Windows WinUI / Web React）均对接本文档描述的同一 HTTP/SSE
接口。新接入方**只看本文即可对接**；服务端实现细节不属于契约内容。

---

## 目录

1. [全局约定](#1-全局约定)  
2. [认证](#2-认证)  
3. [错误格式](#3-错误格式)  
4. [核心推理端点](#4-核心推理端点)  
5. [SSE 流格式](#5-sse-流格式)  
6. [配置端点](#6-配置端点)  
7. [Terr 管理](#7-terr-管理)  
8. [记忆端点](#8-记忆端点)  
9. [项目端点](#9-项目端点)  
10. [集成端点（MCP / 平台）](#10-集成端点mcp--平台)  
11. [Ollama 辅助端点](#11-ollama-辅助端点)  
12. [会话管理](#12-会话管理)  
13. [安全边界](#13-安全边界)  
14. [枚举值参考](#14-枚举值参考)  

---

## 1. 全局约定

| 项目 | 值 |
|------|----|
| 基础路径 | `/` （无版本前缀；靠 `api_revision` 区分能力） |
| 请求体格式 | `application/json` |
| 响应格式 | `application/json`（SSE 除外） |
| 字符集 | UTF-8（中文内容保持原文，`ensure_ascii=False`） |
| 安全响应头 | `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer` |
| 请求体上限 | 默认 4 MB；`AUTUMN_MAX_BODY_BYTES` 可覆盖 |
| CORS | 默认 `*`；`AUTUMN_CORS_ORIGINS`（逗号分隔）可锁定来源 |

**`api_revision`**：`GET /health` 返回此整数，客户端据此判断服务端是否支持所需能力，
而无需解析版本号。当前值为 `1`（增加了 `/mcps` 内联连接面）。

---

## 2. 认证

当 `AUTUMN_API_KEY` 环境变量被设置时，**除 `/health` 外**所有端点均需认证：

```
X-API-Key: <secret>
# 或
Authorization: Bearer <secret>
```

未设置该变量时（本地单用户默认），服务完全开放。

- **401** 缺少或无效密钥

---

## 3. 错误格式

所有 HTTP 错误均返回标准 FastAPI `{"detail": "<message>"}` 体：

| 状态码 | 含义 |
|--------|------|
| `400` | 请求参数无效 |
| `401` | 认证失败 |
| `404` | 资源不存在 |
| `413` | 请求体 / 查询参数超限 |
| `501` | 功能未配置（如 A1 模型未设置） |
| `502` | 上游模型 API 请求失败 |
| `503` | 服务未配置（`/config/apply` 尚未成功调用） |

---

## 4. 核心推理端点

### 4.1 `GET /health`

心跳探针；不需要认证。

**响应 200**

```json
{
  "status": "ok",
  "configured": true,
  "last_error": null,
  "api_revision": 1,
  "version": "0.3.4"
}
```

- `configured`：`/config/apply` 是否已成功运行
- `last_error`：最近一次流式推理的错误消息，`null` 表示无错
- `api_revision`：客户端版本门控用

---

### 4.2 `GET /metrics`

进程生命周期内的累计运行指标；需要认证（与其他端点一致）。

**响应 200**

```json
{
  "runs": 42,
  "errors": 1,
  "prompt_tokens": 185320,
  "completion_tokens": 34210,
  "uptime_seconds": 3601.5
}
```

- `runs`：`/process`、`/trace`、`/stream` 成功完成的推理总次数
- `errors`：`_record_failure` 记录的 502 错误次数（不含客户端 4xx）
- `prompt_tokens` / `completion_tokens`：所有 WorkflowStage 的 token 累计
- `uptime_seconds`：服务进程启动以来的秒数

---

### 4.3 `POST /process`

同步单次推理，等待完整输出后返回。

**请求体**

```json
{
  "input": "帮我写一个 Python 排序算法",
  "route": null,
  "input_type": null,
  "task_type": null,
  "project_instructions": null,
  "project_id": null
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `input` | string | ✅ | 用户输入 |
| `route` | `"direct"` \| `"convert"` \| `"auto"` \| null | | 强制路由；null 表示由 A1 自动选择 |
| `input_type` | 见 [§14](#14-枚举值参考) | | 强制输入类型分类 |
| `task_type` | 见 [§14](#14-枚举值参考) | | 强制任务类型分类 |
| `project_instructions` | string \| null | | 会被包裹为 `[项目指令]` 前置块注入 |
| `project_id` | string \| null | | 激活指定项目上下文 |

**响应 200**

```json
{ "output": "..." }
```

---

### 4.4 `POST /trace`

同步推理，返回完整 WorkflowRun trace。字段与 `/process` 相同。

**响应 200**

```json
{
  "output": "...",
  "input_type": "chat",
  "route": "direct",
  "task_type": null,
  "stages": [
    {
      "id": "wp1.select",
      "title": "选择路由",
      "detail": "...",
      "workspace": "WP1",
      "items": null,
      "status": "done",
      "kind": "stage",
      "duration_ms": 312.0,
      "prompt_tokens": 540,
      "completion_tokens": 18,
      "source_terr": null,
      "cost_usd": 0.00015
    }
  ],
  "total_prompt_tokens": 1200,
  "total_completion_tokens": 95,
  "total_cost_usd": 0.0006
}
```

`kind` 取值：`"stage"` · `"tool"` · `"agent"` · `"push"`（4D memory push-injection）

`workspace` 取值：`"WP1"` · `"WP2"` · `"WP3"` · `"WP4"`

---

### 4.5 `POST /intent`

仅分类意图，不执行推理。字段与 `/process` 相同。

**响应 200**

```json
{
  "input_type": "task",
  "task_type": "code",
  "route": "convert",
  "confidence": 0.92,
  "reasoning": "..."
}
```

---

### 4.6 `GET /stream` （SSE）

流式推理。见 [§5](#5-sse-流格式) 了解事件格式。

**查询参数**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `input` | string | ✅ | 用户输入（UTF-8 字节数受 `AUTUMN_MAX_BODY_BYTES` 限制） |
| `route` | string | | 同 `/process` |
| `input_type` | string | | 同 `/process` |
| `task_type` | string | | 同 `/process` |
| `project_instructions` | string | | 同 `/process` |
| `project_id` | string | | 同 `/process` |

**响应** `Content-Type: text/event-stream`（见 §5）

---

## 5. SSE 流格式

`GET /stream` 使用标准 SSE 协议，每个帧为：

```
data: <json>\n\n
```

### 5.1 帧类型

| 帧 JSON 键 | 含义 | 值类型 |
|-----------|------|--------|
| `chunk` | 文本增量 | string |
| `trace` | 完整 WorkflowRun trace（与 `/trace` 响应同结构） | object |
| `error` | 流内错误（非 HTTP 错误）| string |

### 5.2 终止帧

```
data: [DONE]\n\n
```

**无论正常完成还是出错，流总以 `[DONE]` 结束。** 客户端应以此作为关闭连接的信号。

### 5.3 心跳（Ping）帧

```
: ping\n\n
```

SSE 注释帧，每隔 **15 秒**（`_SSE_HEARTBEAT_SECONDS`）在等待模型时发送。客户端忽略即可；
企业代理通常在 30–60 秒空闲后断开 SSE，心跳防止超时。

### 5.4 断线计费保护

服务端在 `while True` 循环内、每次等待模型前检查 `request.is_disconnected()`。客户端
断开连接后，当前正在进行的模型调用任务会被 `.cancel()`，防止为已无人接收的响应付费。

### 5.5 完整交互示例

```
data: {"chunk": "快速排序"}
data: {"chunk": "（Quick Sort）的思路："}
data: {"chunk": "选择一个 pivot..."}
: ping
data: {"chunk": "时间复杂度 O(n log n)。"}
data: {"trace": {"output": "...", "stages": [...]}}
data: [DONE]
```

---

## 6. 配置端点

### 6.1 `POST /models`

检查指定 base URL 上的模型列表。常用于配置向导的"测试连接"按钮。

**请求体**

```json
{
  "api_key": "sk-...",
  "base_url": "https://api.openai.com/v1",
  "protocol": "openai"
}
```

`protocol` 取值：`"openai"` · `"anthropic"` · `"ollama"`

**响应 200**

```json
{ "models": ["gpt-4o", "gpt-4o-mini", "o1"] }
```

- **400** base URL 为私有/内网地址（SSRF 防护）

---

### 6.2 `POST /config/apply`

配置并启动 Autumn 实例（四个模型槽）。必须在调用任何推理端点之前成功执行。

**请求体**

```json
{
  "a1": { "api_key": "sk-...", "base_url": "https://api.anthropic.com", "model": "claude-opus-4-8", "protocol": "anthropic" },
  "a2": { "api_key": "sk-...", "base_url": "https://api.anthropic.com", "model": "claude-sonnet-4-6", "protocol": "anthropic" },
  "a3": { "api_key": "sk-...", "base_url": "https://api.anthropic.com", "model": "claude-haiku-4-5-20251001", "protocol": "anthropic" },
  "a4": null,
  "behavior": { "a1_supervision": true, "a1_task_planning": false }
}
```

`a4` 可为 `null`；其余三个必填。`ModelSlotConfig`：`{ api_key, base_url, model, protocol }`

`behavior`（可选）用于在运行时切换协作型工作流开关，省略字段保持环境默认值。可设字段：
`cooperative_workflow`、`a1_task_planning`、`a1_supervision`、`archive_executions`、
`a4_delegate_to_a1`、`a4_knowledge_terr`（均为 `bool`）。4D 记忆开关另见 §8.10。

**响应 200**

```json
{ "status": "ok", "configured": true }
```

---

### 6.3 `GET /config/codebase-memory`

查询 Codebase Memory 层状态。

**响应 200**

```json
{
  "enabled": true,
  "connected": true,
  "indexed": true,
  "repo": "/srv/app",
  "tool_count": 7,
  "error": null
}
```

---

### 6.4 `POST /config/codebase-memory`

启用或禁用 Codebase Memory 层。

**请求体**

```json
{ "enabled": true, "repo": "/srv/app" }
```

`repo` 可选，省略则使用服务器工作目录。**响应 200** — 同 GET（`CodebaseMemoryStatusResponse`）

---

## 7. Terr 管理

**Terr（域）**是一组工具/技能的命名能力域。

### 7.1 `GET /terrs`

列出所有已注册的 Terr 及其工具/技能。

**响应 200** — `TerrResponse` 数组：

```json
[
  {
    "name": "web",
    "description": "网页浏览与搜索能力",
    "enabled": true,
    "tools": [{ "name": "http_get", "description": "...", "parameters": [] }],
    "skills": [{ "name": "web_search", "description": "...", "parameters": [] }],
    "mcps": []
  }
]
```

---

### 7.2 `PATCH /terrs/{terr_name}`

启用或禁用指定 Terr。

**请求体**

```json
{ "enabled": false }
```

**响应 200** — 更新后的 `TerrResponse`

- **404** 未知 Terr 名称

---

## 8. 记忆端点

记忆区域（`{area}`）取值：`mom1` · `mom2` · `mom3` · `shared`

> **注意**：涉及 A4 认知操作的端点需要 A4 模型槽已配置（否则 **400**）。
> `/memory/stats` 和 `/memory/audit/access_log` 不需要模型槽。

### 8.1 `GET /memory/{area}/history`

分页获取记忆历史。

**查询参数**：`limit`（默认 200，范围 1–2000）、`offset`（默认 0）

**响应 200** — `MemoryEntry` 数组（按 `limit`/`offset` 切片）

---

### 8.2 `GET /memory/stats` / `GET /memory/{area}/stats`

全局 / 单区域统计。

---

### 8.3 `POST /memory/{area}/consolidate`

A4 认知操作：整合记忆条目，提炼持久性见解。

---

### 8.4 `POST /memory/{area}/extract-facts`

A4 认知操作：从近期历史中提取原子事实并存入记忆。

**请求体**（均可选）`{ "keep_recent": 0, "max_facts": 20 }`

---

### 8.5 `POST /memory/{area}/evolve`

A4 认知操作：演化/更新现有记忆条目。

---

### 8.6 `GET /memory/{area}/profile` / `POST /memory/{area}/profile`

读取或重建用户画像（A4 综合）。

---

### 8.7 `POST /memory/{area}/annotate`

为记忆条目手动添加 4D 标注。请求体为**扁平**结构（非嵌套 aim/use/trigger），省略字段保持原值。

**请求体**

```json
{
  "entry_id": "e123",
  "mode": "constrain",
  "intent": "deploy_guardrail",
  "goal_ref": "goal:ship-v2",
  "scope": ["deploy"],
  "cues": ["部署"],
  "half_life": null
}
```

`mode`：`constrain | remind | summarize | context`。**响应 200**

```json
{ "status": "ok", "entry_id": "e123", "found": true }
```

---

### 8.8 `POST /memory/{area}/auto-annotate`

A4 认知操作：自动为近期条目批量推断 4D 标注。

**请求体**（均可选）`{ "n": 10, "only_unannotated": true }`

**响应 200**

```json
{ "status": "ok", "annotated": 4, "scanned": 10 }
```

---

### 8.9 `GET /memory/4d/status`

4D 记忆层当前状态（push 引擎开关、上次 push 时间等）。

---

### 8.10 `POST /memory/4d/config`

切换 4D 记忆配置。

**请求体** `{ "fourd_enabled": true, "push_on_turn": false }`

---

### 8.11 `POST /memory/push/preview`

预览下一次 push 注入会写入哪些条目（不实际执行）。

---

### 8.12 `GET /memory/audit/access_log`

获取 Mom1 访问审计日志（WP2/WP3 通过 broker 读 Mom1 的记录）。

---

## 9. 项目端点

### 9.1 `GET /projects`

列出所有项目 ID。

---

### 9.2 `GET /projects/{project_id}/memory`

读取项目专属记忆。

---

### 9.3 `GET /projects/{project_id}/stats`

项目记忆统计。

---

### 9.4 `POST /projects/{project_id}/consolidate`

整合项目记忆。

---

### 9.5 `DELETE /projects/{project_id}`

删除项目及其所有数据。

---

### 9.6 `GET /projects/{project_id}/metadata`

读取项目元数据（type / description / goals / environment）。

---

### 9.7 `PATCH /projects/{project_id}/metadata`

更新项目元数据。

**请求体（所有字段可选）**

```json
{
  "project_type": "code",
  "description": "An AI workflow framework",
  "goals": { "master": "Ship 1.0", "long_term": [], "short_term": [] },
  "files": ["/srv/app/main.py"]
}
```

---

### 9.8 `POST /projects/{project_id}/files`

向项目添加文件路径。

**请求体** `{ "file_path": "/srv/app/main.py" }`

---

### 9.9 `DELETE /projects/{project_id}/files/{file_path}`

从项目移除文件路径。

---

### 9.10 `POST /projects/{project_id}/describe`

由 A1 根据自由文本草拟项目描述（不自动保存）。

**请求体** `{ "input": "这是一个帮助团队协作的 AI 框架" }`

**响应 200** `{ "description": "..." }`

---

### 9.11 `POST /projects/{project_id}/goals`

由 A1 将目标描述结构化为 master / long_term / short_term（不自动保存）。

**请求体** `{ "input": "三个月内发布 1.0，先完成三端对齐" }`

**响应 200** `{ "master": "...", "long_term": [...], "short_term": [...] }`

---

### 9.12 `POST /projects/{project_id}/infer-environment`

由 A1 推断并**持久化**项目的执行环境配置（terrs / skills / tools / mcp / agent_channel）。

**响应 200** — 完整更新后的 ProjectMeta

---

## 10. 集成端点（MCP / 平台）

### 10.1 MCP

| 端点 | 说明 |
|------|------|
| `GET /mcps/catalog` | 框架内置的已知 MCP 服务器列表（无需配置即可读取） |
| `GET /mcps/status` | 当前已连接的 MCP 客户端状态 |
| `POST /mcps/connect` | 按 ID 连接一个已知 MCP | `{ "id": "...", "options": {} }` |
| `DELETE /mcps/{mcp_id}` | 断开并注销指定 MCP |

### 10.2 平台集成

| 端点 | 说明 |
|------|------|
| `GET /integrations/catalog` | 平台集成目录（GitHub、Notion 等） |
| `GET /integrations/status` | 已连接的平台集成状态 |
| `POST /integrations/connect` | 连接一个平台集成 |
| `DELETE /integrations/{integration_id}` | 断开并移除指定集成 |

---

## 11. Ollama 辅助端点

| 端点 | 说明 |
|------|------|
| `POST /ollama/status` | 检测本地 Ollama 是否运行 `{ "base_url": "..." }` |
| `POST /ollama/models` | 列出本地 Ollama 可用模型 `{ "base_url": "..." }` |
| `DELETE /ollama/models` | 删除本地 Ollama 模型 `{ "base_url": "...", "name": "..." }` |
| `GET /ollama/recommended` | 框架推荐的 A4 小模型列表（静态，无需配置） |
| `GET /ollama/pull` | 流式下载 Ollama 模型（SSE，格式同 §5） |

---

## 12. 会话管理

### `POST /session/end`

通知服务端当前会话结束（触发 WP4 会话后记忆整合）。

**响应 200** `{ "status": "ok" }`

---

## 13. 安全边界

### 13.1 SSRF 防护

`POST /models`、所有网络工具调用均经过 `assert_url_allowed()`：

- **阻止**：回环（`127.x`、`::1`、`localhost`）、私有网段（RFC 1918）、云元数据 IP（`169.254.169.254`）、内部 DNS 后缀（`.internal`）
- **阻止**：非 HTTP/HTTPS scheme（如 `file://`、`ftp://`）
- **允许**：通过 `AUTUMN_ALLOW_PRIVATE_NETWORK=1` 豁免（Ollama 本地使用场景）

### 13.2 输入大小限制

- 请求体：`Content-Length` 超限返回 **413**
- `GET /stream` 的 `input` / `project_instructions` 查询参数：UTF-8 字节数独立检查（GET 不经 Content-Length 中间件）

### 13.3 响应头过滤（`safe_head`）

`http_head` 工具返回的响应头中，`set-cookie`、`authorization`、`www-authenticate`、`proxy-authenticate` 等敏感头已被自动剔除，防止目标站点 cookie 泄漏至模型上下文。

### 13.4 SSE 重定向 SSRF 防护

`safe_head` 在手动跟随每个重定向跳时重新执行 SSRF 检查，防止 `A → 公网 IP → 302 → 169.254.x.x` 绕过。

---

## 14. 枚举值参考

### `InputType`

| 值 | 含义 |
|----|------|
| `"task"` | 结构化任务请求（有明确动作意图） |
| `"mission"` | 对话 / 自然语言交互（由 A1 进一步分类） |

### `TaskType`

| 值 | 含义 |
|----|------|
| `"code"` | 编写 / 调试代码 |
| `"write"` | 文字写作 |
| `"search"` | 检索 / 搜索 |
| `"data"` | 数据处理 |
| `"general"` | 通用任务 |

### `MissionRoute`

| 值 | 含义 |
|----|------|
| `"direct"` | 直接回复（WP3 → `answer_directly`） |
| `"convert"` | 转化为任务（WP3 → `convert_to_task` → WP2） |
| `"auto"` / `null` | 由 A1 Selector 自动选择 |

---

> 维护约定：当端点增减或 `api_revision` 变动时更新本文档，并在 `docs/roadmap.md`
> 相应条目下补记落地版本。

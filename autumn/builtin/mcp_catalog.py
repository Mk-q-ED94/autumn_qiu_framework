"""Catalog of well-known external MCP servers.

These are *factory* functions that construct :class:`StdioMCPClient` objects
for the official MCP servers most commonly used in agent workflows. You still
need the underlying binary installed (``npx``, ``uvx``, etc.); the catalog
just spares you from remembering each launch command.

Usage:

    from autumn.builtin import mcp_filesystem, mcp_fetch
    from autumn.core.components.terr import Terr

    files = Terr("files", "Local file ops via MCP", mcps=[mcp_filesystem("/srv/data")])
    await autumn.add_terr(files)

Each factory returns an unconnected client — call ``Autumn.add_terr`` /
``Autumn.add_mcp`` to drive the connect → bridge → register pipeline.
"""
from __future__ import annotations

from ..core.components.mcp_stdio import StdioMCPClient


def mcp_filesystem(root: str, *, binary: str = "npx") -> StdioMCPClient:
    """Official ``@modelcontextprotocol/server-filesystem`` over stdio.

    Exposes read/write/list/delete on the ``root`` directory.
    """
    return StdioMCPClient(
        command=[binary, "-y", "@modelcontextprotocol/server-filesystem", root],
    )


def mcp_fetch(*, binary: str = "uvx") -> StdioMCPClient:
    """Official ``mcp-server-fetch`` — generic HTTP GET/HEAD over stdio."""
    return StdioMCPClient(command=[binary, "mcp-server-fetch"])


def mcp_git(repo: str, *, binary: str = "uvx") -> StdioMCPClient:
    """Official ``mcp-server-git`` — git operations scoped to ``repo``."""
    return StdioMCPClient(command=[binary, "mcp-server-git", "--repository", repo])


def mcp_sqlite(db_path: str, *, binary: str = "uvx") -> StdioMCPClient:
    """Official ``mcp-server-sqlite`` — read/write queries against a SQLite file."""
    return StdioMCPClient(command=[binary, "mcp-server-sqlite", "--db-path", db_path])


def mcp_brave_search(api_key: str, *, binary: str = "npx") -> StdioMCPClient:
    """Official ``@modelcontextprotocol/server-brave-search``.

    Requires a Brave Search API key. Passed via ``BRAVE_API_KEY`` env var.
    """
    return StdioMCPClient(
        command=[binary, "-y", "@modelcontextprotocol/server-brave-search"],
        env={"BRAVE_API_KEY": api_key},
    )


def mcp_github(token: str, *, binary: str = "npx") -> StdioMCPClient:
    """Official ``@modelcontextprotocol/server-github`` — GitHub API access."""
    return StdioMCPClient(
        command=[binary, "-y", "@modelcontextprotocol/server-github"],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": token},
    )


def mcp_puppeteer(*, binary: str = "npx") -> StdioMCPClient:
    """Official ``@modelcontextprotocol/server-puppeteer`` — headless browser."""
    return StdioMCPClient(
        command=[binary, "-y", "@modelcontextprotocol/server-puppeteer"],
    )


def mcp_memory(*, binary: str = "npx") -> StdioMCPClient:
    """Official ``@modelcontextprotocol/server-memory`` — persistent KV memory."""
    return StdioMCPClient(
        command=[binary, "-y", "@modelcontextprotocol/server-memory"],
    )


def mcp_codebase_memory(repo: str | None = None, *, binary: str = "uvx") -> StdioMCPClient:
    """``codebase-memory-mcp`` — index a codebase into a knowledge graph.

    A code-intelligence MCP server (DeusData/codebase-memory-mcp, MIT) that
    parses a repository into a queryable graph of functions/classes/routes and
    their call/import/inherit edges. The agent then answers structural questions
    with graph queries (``search_graph`` / ``trace_path`` / ``get_architecture``
    / ``query_graph``) instead of reading files one by one — the project reports
    ~99% fewer tokens on structural exploration. This is the engine behind
    Autumn's optional *codebase memory* token-saving layer.

    Parameters
    ----------
    repo:
        Absolute path to the repository the server should operate on. Passed as
        the subprocess working directory so on-launch indexing and the
        background change-watcher scope to this tree; the agent still indexes it
        explicitly via ``index_repository``. ``None`` leaves the cwd inherited.
    binary:
        Launcher. ``"uvx"`` (default) runs the published PyPI package, ``"npx"``
        the npm package; any other value is treated as a direct path to the
        natively-installed ``codebase-memory-mcp`` binary.
    """
    if binary == "npx":
        command = ["npx", "-y", "codebase-memory-mcp"]
    elif binary == "uvx":
        command = ["uvx", "codebase-memory-mcp"]
    else:
        # Treat `binary` as a path to the natively-installed server binary
        # (e.g. produced by the project's install.sh).
        command = [binary]
    return StdioMCPClient(command=command, cwd=repo or None)


def mcp_postgres(connection_string: str, *, binary: str = "npx") -> StdioMCPClient:
    """Official ``@modelcontextprotocol/server-postgres`` — read-only SQL access.

    The connection string (``postgresql://user:pass@host/db``) is passed as a
    positional argument to the server.
    """
    return StdioMCPClient(
        command=[binary, "-y", "@modelcontextprotocol/server-postgres", connection_string],
    )


def mcp_slack(bot_token: str, team_id: str, *, binary: str = "npx") -> StdioMCPClient:
    """Official ``@modelcontextprotocol/server-slack`` — post/read Slack messages."""
    return StdioMCPClient(
        command=[binary, "-y", "@modelcontextprotocol/server-slack"],
        env={"SLACK_BOT_TOKEN": bot_token, "SLACK_TEAM_ID": team_id},
    )


def mcp_gitlab(token: str, *, api_url: str | None = None, binary: str = "npx") -> StdioMCPClient:
    """Official ``@modelcontextprotocol/server-gitlab`` — GitLab API access."""
    env = {"GITLAB_PERSONAL_ACCESS_TOKEN": token}
    if api_url:
        env["GITLAB_API_URL"] = api_url
    return StdioMCPClient(
        command=[binary, "-y", "@modelcontextprotocol/server-gitlab"],
        env=env,
    )


def mcp_google_maps(api_key: str, *, binary: str = "npx") -> StdioMCPClient:
    """Official ``@modelcontextprotocol/server-google-maps`` — geocoding/directions."""
    return StdioMCPClient(
        command=[binary, "-y", "@modelcontextprotocol/server-google-maps"],
        env={"GOOGLE_MAPS_API_KEY": api_key},
    )


def mcp_sequential_thinking(*, binary: str = "npx") -> StdioMCPClient:
    """Official ``@modelcontextprotocol/server-sequential-thinking``.

    A reasoning scaffold the model can call to break problems into ordered,
    revisable thought steps. No credentials or network access required.
    """
    return StdioMCPClient(
        command=[binary, "-y", "@modelcontextprotocol/server-sequential-thinking"],
    )


def mcp_time(*, binary: str = "uvx") -> StdioMCPClient:
    """Official ``mcp-server-time`` — timezone conversion and current time."""
    return StdioMCPClient(command=[binary, "mcp-server-time"])


def mcp_everything(*, binary: str = "npx") -> StdioMCPClient:
    """Official ``@modelcontextprotocol/server-everything`` — reference/test server.

    Exercises every MCP feature (tools, prompts, resources); handy for smoke
    testing an MCP integration end to end.
    """
    return StdioMCPClient(
        command=[binary, "-y", "@modelcontextprotocol/server-everything"],
    )


# ── catalog metadata ─────────────────────────────────────────────────────────
#
# Each catalog entry carries everything a client needs to *introduce* an MCP and
# (where applicable) configure it inline:
#
#   category          "platform" (external account, secret token), "local"
#                     (a path on the server host), or "keyless" (one-click, no
#                     config).
#   fields            input form for the connect args — empty for keyless MCPs.
#   setup             a short, human tutorial: a one-line summary, ordered steps,
#                     and an optional documentation URL.
#   required_args     kept for back-compat with older clients.


def _field(key: str, label: str, *, secret: bool = False,
           optional: bool = False, placeholder: str = "") -> dict:
    return {
        "key": key,
        "label": label,
        "secret": secret,
        "optional": optional,
        "placeholder": placeholder,
    }


def _setup(summary: str, steps: list[str], doc_url: str | None = None) -> dict:
    return {"summary": summary, "steps": steps, "doc_url": doc_url}


def _entry(
    id: str, name: str, description: str, factory: str, *,
    category: str,
    fields: list[dict] | None = None,
    setup: dict | None = None,
) -> dict:
    fields = fields or []
    return {
        "id": id,
        "name": name,
        "description": description,
        "factory": factory,
        "category": category,
        "needs_credentials": bool(fields),
        "fields": fields,
        "setup": setup,
        # Required positional/credential args, derived from the form fields.
        "required_args": [f["key"] for f in fields if not f.get("optional")],
    }


# A flat, richly-described list — the single source clients render from. Keep in
# sync with the factories above.
KNOWN_MCPS: list[dict] = [
    # ── local resources (a path on the server host) ──────────────────────────
    _entry(
        "filesystem", "Filesystem (MCP)",
        "Read/write/list operations over a chosen directory.",
        "mcp_filesystem", category="local",
        fields=[_field("root", "目录路径", placeholder="/Users/you/Documents")],
        setup=_setup(
            "让 agent 在你指定的目录内读写文件。",
            [
                "确认服务器主机已安装 npx（Node.js 18+）。",
                "在上方填入要授权的目录绝对路径，例如 /Users/you/Documents。",
                "默认只读；如需让 agent 创建 / 修改 / 删除文件，请打开“允许写操作”。",
                "点击连接。",
            ],
            "https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
        ),
    ),
    _entry(
        "git", "Git (MCP)",
        "Inspect and manipulate a local git repository.",
        "mcp_git", category="local",
        fields=[_field("repo", "Git 仓库路径", placeholder="/Users/you/project")],
        setup=_setup(
            "让 agent 查看与操作一个本地 git 仓库。",
            [
                "确认服务器主机已安装 uvx（uv）。",
                "填入本地 git 仓库的绝对路径。",
                "默认只读（log / diff / status 等）；commit 等写操作需打开“允许写操作”。",
                "点击连接。",
            ],
            "https://github.com/modelcontextprotocol/servers/tree/main/src/git",
        ),
    ),
    _entry(
        "sqlite", "SQLite (MCP)",
        "Run read/write queries against a SQLite file.",
        "mcp_sqlite", category="local",
        fields=[_field("db_path", "SQLite 文件路径", placeholder="/Users/you/data.db")],
        setup=_setup(
            "对一个 SQLite 数据库文件执行查询。",
            [
                "确认服务器主机已安装 uvx（uv）。",
                "填入 .db 文件的绝对路径（不存在会新建）。",
                "默认只读查询；写入需打开“允许写操作”。",
                "点击连接。",
            ],
            "https://github.com/modelcontextprotocol/servers/tree/main/src/sqlite",
        ),
    ),
    _entry(
        "codebase_memory", "Codebase Memory (MCP)",
        "Index a codebase into a knowledge graph; query structure (calls, "
        "imports, architecture) instead of reading files to save tokens.",
        "mcp_codebase_memory", category="local",
        fields=[_field("repo", "代码库路径（可留空，连接后由 agent 指定）",
                       optional=True, placeholder="/Users/you/project")],
        setup=_setup(
            "把代码库索引成知识图谱,让 agent 用图谱查询(调用链、依赖、架构)代替逐文件"
            "阅读,大幅减少 token 消耗。这是 Autumn“代码库记忆”省 token 层的底层引擎。",
            [
                "安装服务器二进制:推荐 uvx codebase-memory-mcp(需 uv),或 npx -y "
                "codebase-memory-mcp(需 Node 18+),或用项目 install.sh 安装原生二进制。",
                "可在上方填入要索引的代码库绝对路径作为工作目录;留空则连接后由 agent "
                "通过 index_repository(repo_path=...) 指定。",
                "点击连接。首次 agent 会调用 index_repository 建图,之后 search_graph / "
                "trace_path / get_architecture / query_graph 都是亚毫秒级。",
                "全部为只读/索引操作,不会修改你的源码。",
            ],
            "https://github.com/DeusData/codebase-memory-mcp",
        ),
    ),
    # ── platforms (external account behind a secret) ─────────────────────────
    _entry(
        "github", "GitHub (MCP)",
        "GitHub API access for issues, PRs, files, search.",
        "mcp_github", category="platform",
        fields=[_field("token", "Personal Access Token", secret=True, placeholder="ghp_…")],
        setup=_setup(
            "用个人访问令牌授权 Autumn 读写你的 GitHub。",
            [
                "打开 GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)。",
                "点击 Generate new token，按需勾选 repo 等 scope。",
                "复制 ghp_ 开头的令牌，粘贴到上方 Personal Access Token。",
                "默认只读；如需创建 / 修改 issue、PR、文件，请打开“允许写操作”后再连接。",
            ],
            "https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens",
        ),
    ),
    _entry(
        "gitlab", "GitLab (MCP)",
        "GitLab API access for projects, issues, and merge requests.",
        "mcp_gitlab", category="platform",
        fields=[
            _field("token", "Personal Access Token", secret=True, placeholder="glpat-…"),
            _field("api_url", "API URL（自托管填写，官方云可留空）",
                   optional=True, placeholder="https://gitlab.example.com/api/v4"),
        ],
        setup=_setup(
            "访问 GitLab 项目、issue 与合并请求。",
            [
                "打开 GitLab → 用户设置 → Access Tokens。",
                "创建令牌，勾选 api scope。",
                "复制并粘贴到 Personal Access Token。",
                "自托管实例在 API URL 填 https://你的域名/api/v4；官方云 gitlab.com 留空即可。",
            ],
            "https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html",
        ),
    ),
    _entry(
        "slack", "Slack (MCP)",
        "Post and read messages across Slack channels.",
        "mcp_slack", category="platform",
        fields=[
            _field("bot_token", "Bot Token", secret=True, placeholder="xoxb-…"),
            _field("team_id", "Team ID", placeholder="T0…"),
        ],
        setup=_setup(
            "读取与发送 Slack 频道消息。",
            [
                "在 api.slack.com/apps 创建 App，添加 Bot Token Scopes（chat:write、channels:read 等）。",
                "安装到工作区，复制 xoxb- 开头的 Bot Token。",
                "在工作区设置中找到 Team ID（T 开头）。",
                "把两者分别填入上方字段。",
            ],
            "https://api.slack.com/authentication/token-types",
        ),
    ),
    _entry(
        "brave_search", "Brave Search (MCP)",
        "Web search via the Brave Search API.",
        "mcp_brave_search", category="platform",
        fields=[_field("api_key", "API Key", secret=True, placeholder="BSA…")],
        setup=_setup(
            "通过 Brave Search API 进行网页搜索。",
            [
                "访问 https://brave.com/search/api/ 注册并创建订阅（含免费额度）。",
                "在控制台生成 API Key。",
                "粘贴到上方 API Key。",
                "点击连接。",
            ],
            "https://brave.com/search/api/",
        ),
    ),
    _entry(
        "google_maps", "Google Maps (MCP)",
        "Geocoding, place search, and directions via Google Maps.",
        "mcp_google_maps", category="platform",
        fields=[_field("api_key", "API Key", secret=True, placeholder="AIza…")],
        setup=_setup(
            "地理编码、地点检索与路线规划。",
            [
                "在 Google Cloud Console 启用 Maps / Geocoding / Places API。",
                "APIs & Services → Credentials → 创建 API Key。",
                "建议为该 Key 限制可用 API 与来源。",
                "粘贴到上方 API Key。",
            ],
            "https://developers.google.com/maps/documentation",
        ),
    ),
    _entry(
        "postgres", "PostgreSQL (MCP)",
        "Read-only SQL queries against a PostgreSQL database.",
        "mcp_postgres", category="platform",
        fields=[_field("connection_string", "Connection String", secret=True,
                       placeholder="postgresql://user:pass@host:5432/db")],
        setup=_setup(
            "对 PostgreSQL 数据库执行只读 SQL 查询。",
            [
                "准备形如 postgresql://user:pass@host:5432/dbname 的连接串。",
                "建议使用只读账户。",
                "粘贴到上方 Connection String。",
                "点击连接。",
            ],
            "https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNSTRING",
        ),
    ),
    # ── keyless utilities (one-click, no configuration) ──────────────────────
    _entry(
        "fetch", "HTTP Fetch (MCP)",
        "Generic HTTP GET/HEAD for retrieving web pages.",
        "mcp_fetch", category="keyless",
        setup=_setup("无需凭据，点击连接即可让 agent 抓取网页（GET/HEAD）。需服务器安装 uvx。", []),
    ),
    _entry(
        "puppeteer", "Puppeteer (MCP)",
        "Headless browser automation for JS-heavy pages.",
        "mcp_puppeteer", category="keyless",
        setup=_setup("无需凭据。提供无头浏览器自动化，适合 JS 重的页面。需服务器安装 npx，首次会下载 Chromium。", []),
    ),
    _entry(
        "memory", "Memory (MCP)",
        "Persistent key-value memory via the official MCP memory server.",
        "mcp_memory", category="keyless",
        setup=_setup("无需凭据。基于官方 memory server 的持久化键值记忆。需服务器安装 npx。", []),
    ),
    _entry(
        "sequential_thinking", "Sequential Thinking (MCP)",
        "Structured step-by-step reasoning scaffold. No credentials needed.",
        "mcp_sequential_thinking", category="keyless",
        setup=_setup("无需凭据。提供结构化分步推理脚手架。需服务器安装 npx。", []),
    ),
    _entry(
        "time", "Time (MCP)",
        "Current time and timezone conversion.",
        "mcp_time", category="keyless",
        setup=_setup("无需凭据。当前时间与时区换算。需服务器安装 uvx。", []),
    ),
    _entry(
        "everything", "Everything (MCP)",
        "Reference server exercising every MCP feature; useful for testing.",
        "mcp_everything", category="keyless",
        setup=_setup("无需凭据。参考 / 测试服务器，覆盖所有 MCP 特性，用于联调。需服务器安装 npx。", []),
    ),
]


MCP_BY_ID: dict[str, dict] = {entry["id"]: entry for entry in KNOWN_MCPS}


__all__ = [
    "mcp_filesystem",
    "mcp_fetch",
    "mcp_git",
    "mcp_sqlite",
    "mcp_brave_search",
    "mcp_github",
    "mcp_puppeteer",
    "mcp_memory",
    "mcp_codebase_memory",
    "mcp_postgres",
    "mcp_slack",
    "mcp_gitlab",
    "mcp_google_maps",
    "mcp_sequential_thinking",
    "mcp_time",
    "mcp_everything",
    "KNOWN_MCPS",
    "MCP_BY_ID",
]

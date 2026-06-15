"""Platform integrations — turn a saved credential into live agent capability.

When the user stores a token for a platform (GitHub, GitLab, Slack, …), the
server starts the matching official MCP server, bridges its tools, and
registers them as a Terr on the running :class:`Autumn` instance. From that
point the WP2 agent can read and edit that platform's content on its own,
because the tools live in its plugin registry — there is no per-request
credential plumbing for the model to worry about.

Credentials stay inside the server process (held in ``app.state``). Status
responses never echo the secret values back to the client.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..builtin import mcp_catalog as _cat
from ..core.components.mcp_bridge import mcp_to_tools
from ..core.components.terr import Terr
from ..core.framework import Autumn

# Verbs that mark a platform tool as *mutating* the user's real account
# (issues, PRs, files, messages, rows). When an integration is connected in the
# default read-only mode, tools whose name carries one of these verbs are NOT
# registered for the agent at all — the dangerous capability simply isn't
# present until the user explicitly grants write access and reconnects.
#
# The set is deliberately conservative: a false positive only hides a tool the
# user can re-enable, but a false negative would let the agent mutate an account
# it was never authorised to touch. Common read verbs (get/list/search/read/
# fetch/describe) and the noun "request" (as in get_pull_request) are excluded
# so they never get caught.
_WRITE_VERBS: frozenset[str] = frozenset({
    "create", "update", "delete", "remove", "add", "edit", "set", "write",
    "patch", "post", "send", "reply", "merge", "push", "fork", "upload",
    "rename", "archive", "assign", "submit", "approve", "dismiss", "insert",
    "drop", "truncate", "star", "pin", "unpin", "invite", "publish", "deploy",
    "restore", "revert", "replace", "close", "reopen", "lock", "unlock",
    "cancel", "move", "transfer", "comment",
})


def _name_tokens(name: str) -> list[str]:
    """Split a tool name into lowercase tokens across snake_case, kebab-case,
    spaces and camelCase boundaries (``createIssue`` → ``["create", "issue"]``)."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name or "")
    return [t for t in re.split(r"[^a-zA-Z0-9]+", spaced.lower()) if t]


def is_write_tool(name: str) -> bool:
    """True when a tool name reads as a mutating action on the platform."""
    return any(token in _WRITE_VERBS for token in _name_tokens(name))

# The subset of the MCP catalog that represents an external account / platform
# the agent can act on with a user-supplied credential. Each entry maps to a
# catalog factory plus the fields that factory needs. ``fields`` drives the
# client's input form; ``secret`` masks the value, ``optional`` relaxes the
# required check.
INTEGRATIONS: list[dict] = [
    {
        "id": "github",
        "name": "GitHub",
        "description": "读写 issues、Pull Request、仓库文件与代码搜索。",
        "factory": "mcp_github",
        "fields": [
            {"key": "token", "label": "Personal Access Token", "secret": True, "optional": False},
        ],
    },
    {
        "id": "gitlab",
        "name": "GitLab",
        "description": "访问项目、issues 与合并请求。",
        "factory": "mcp_gitlab",
        "fields": [
            {"key": "token", "label": "Personal Access Token", "secret": True, "optional": False},
            {"key": "api_url", "label": "API URL（自托管可留空）", "secret": False, "optional": True},
        ],
    },
    {
        "id": "slack",
        "name": "Slack",
        "description": "读取与发送频道消息。",
        "factory": "mcp_slack",
        "fields": [
            {"key": "bot_token", "label": "Bot Token", "secret": True, "optional": False},
            {"key": "team_id", "label": "Team ID", "secret": False, "optional": False},
        ],
    },
    {
        "id": "brave_search",
        "name": "Brave Search",
        "description": "通过 Brave Search API 进行网页搜索。",
        "factory": "mcp_brave_search",
        "fields": [
            {"key": "api_key", "label": "API Key", "secret": True, "optional": False},
        ],
    },
    {
        "id": "google_maps",
        "name": "Google Maps",
        "description": "地理编码、地点检索与路线规划。",
        "factory": "mcp_google_maps",
        "fields": [
            {"key": "api_key", "label": "API Key", "secret": True, "optional": False},
        ],
    },
    {
        "id": "postgres",
        "name": "PostgreSQL",
        "description": "对 PostgreSQL 数据库执行只读 SQL 查询。",
        "factory": "mcp_postgres",
        "fields": [
            {"key": "connection_string", "label": "Connection String", "secret": True, "optional": False},
        ],
    },
]

_BY_ID: dict[str, dict] = {entry["id"]: entry for entry in INTEGRATIONS}


def catalog() -> list[dict]:
    """Public, secret-free catalog the client renders input forms from."""
    return [
        {
            "id": e["id"],
            "name": e["name"],
            "description": e["description"],
            "fields": e["fields"],
        }
        for e in INTEGRATIONS
    ]


def is_known(integration_id: str) -> bool:
    return integration_id in _BY_ID


def required_field_keys(integration_id: str) -> list[str]:
    entry = _BY_ID[integration_id]
    return [f["key"] for f in entry["fields"] if not f.get("optional")]


def display_name(integration_id: str) -> str:
    entry = _BY_ID.get(integration_id)
    return entry["name"] if entry else integration_id


def terr_name_for(integration_id: str) -> str:
    return f"integration:{integration_id}"


def _build_client(integration_id: str, args: dict[str, str]):
    entry = _BY_ID[integration_id]
    factory = getattr(_cat, entry["factory"])
    # Only forward non-empty args so optional fields fall back to factory defaults.
    kwargs = {k: v for k, v in args.items() if v not in (None, "")}
    return factory(**kwargs)


@dataclass
class IntegrationRuntime:
    """Live handle for one connected integration, kept in ``app.state`` so it can
    be torn down cleanly on disconnect or replaced on reconnect."""

    integration_id: str
    terr_name: str
    client: object
    tool_names: list[str] = field(default_factory=list)
    write_enabled: bool = False
    blocked_tool_names: list[str] = field(default_factory=list)

    @property
    def tool_count(self) -> int:
        return len(self.tool_names)

    @property
    def blocked_count(self) -> int:
        return len(self.blocked_tool_names)


async def connect(
    autumn: Autumn,
    integration_id: str,
    args: dict[str, str],
    *,
    write_enabled: bool = False,
) -> IntegrationRuntime:
    """Start the platform's MCP server and register it as a Terr on ``autumn``.

    Materialises the MCP tools up front (so we can record their names for a
    later clean removal) and registers them through a Terr, which keeps the
    integration visible and toggleable in the Terrs UI alongside the built-in
    domains. Raises ``ValueError`` for missing args; propagates connection
    errors so the caller can surface them.

    Safety default — ``write_enabled=False``: tools that read as a *mutating*
    action on the user's real account (see :func:`is_write_tool`) are withheld
    from the agent entirely. The agent gets the platform's read surface and
    nothing that can create / edit / delete / post on the user's behalf. Pass
    ``write_enabled=True`` (a deliberate, per-integration grant) to register the
    full tool set; rotate the mode the same way a token rotates — by reconnecting.
    """
    if not is_known(integration_id):
        raise ValueError(f"未知集成: {integration_id}")
    missing = [k for k in required_field_keys(integration_id) if not args.get(k)]
    if missing:
        raise ValueError(f"缺少必填字段: {', '.join(missing)}")

    entry = _BY_ID[integration_id]
    client = _build_client(integration_id, args)
    await client.connect()
    try:
        tools = await mcp_to_tools(client)
    except Exception:
        await client.disconnect()
        raise

    # Partition into the read surface and the mutating surface. In read-only
    # mode only the read surface is registered; the write tools are recorded so
    # status can report exactly how much capability is being withheld.
    if write_enabled:
        registered, withheld = list(tools), []
    else:
        registered = [t for t in tools if not is_write_tool(getattr(t, "name", ""))]
        withheld = [t for t in tools if is_write_tool(getattr(t, "name", ""))]

    terr = Terr(
        name=terr_name_for(integration_id),
        description=f"{entry['name']} — {entry['description']}",
        tools=registered,
    )
    autumn.register_terr(terr)
    # Own the client so Autumn.close() disconnects it on shutdown / rebuild.
    autumn._mcp_clients.append(client)

    return IntegrationRuntime(
        integration_id=integration_id,
        terr_name=terr.name,
        client=client,
        tool_names=[t.name for t in registered],
        write_enabled=write_enabled,
        blocked_tool_names=[t.name for t in withheld],
    )


async def disconnect(autumn: Autumn, runtime: IntegrationRuntime) -> None:
    """Unregister the integration's tools + Terr and disconnect its MCP client."""
    for name in runtime.tool_names:
        autumn.plugins.unregister(name)
    autumn.plugins.unregister_terr(runtime.terr_name)
    try:
        autumn._mcp_clients.remove(runtime.client)
    except (ValueError, AttributeError):
        pass
    try:
        await runtime.client.disconnect()
    except Exception:
        # Best-effort: a half-dead MCP subprocess shouldn't block the API call.
        pass

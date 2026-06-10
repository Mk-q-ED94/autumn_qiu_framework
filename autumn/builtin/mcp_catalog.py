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


# A flat description list useful for desktop pickers — keep in sync with the
# factories above.
KNOWN_MCPS: list[dict] = [
    {
        "id": "filesystem",
        "name": "Filesystem (MCP)",
        "description": "Read/write/list operations over a chosen directory.",
        "factory": "mcp_filesystem",
        "required_args": ["root"],
    },
    {
        "id": "fetch",
        "name": "HTTP Fetch (MCP)",
        "description": "Generic HTTP GET/HEAD for retrieving web pages.",
        "factory": "mcp_fetch",
        "required_args": [],
    },
    {
        "id": "git",
        "name": "Git (MCP)",
        "description": "Inspect and manipulate a local git repository.",
        "factory": "mcp_git",
        "required_args": ["repo"],
    },
    {
        "id": "sqlite",
        "name": "SQLite (MCP)",
        "description": "Run read/write queries against a SQLite file.",
        "factory": "mcp_sqlite",
        "required_args": ["db_path"],
    },
    {
        "id": "brave_search",
        "name": "Brave Search (MCP)",
        "description": "Web search via the Brave Search API.",
        "factory": "mcp_brave_search",
        "required_args": ["api_key"],
    },
    {
        "id": "github",
        "name": "GitHub (MCP)",
        "description": "GitHub API access for issues, PRs, files, search.",
        "factory": "mcp_github",
        "required_args": ["token"],
    },
    {
        "id": "puppeteer",
        "name": "Puppeteer (MCP)",
        "description": "Headless browser automation for JS-heavy pages.",
        "factory": "mcp_puppeteer",
        "required_args": [],
    },
    {
        "id": "memory",
        "name": "Memory (MCP)",
        "description": "Persistent key-value memory via the official MCP memory server.",
        "factory": "mcp_memory",
        "required_args": [],
    },
    {
        "id": "postgres",
        "name": "PostgreSQL (MCP)",
        "description": "Read-only SQL queries against a PostgreSQL database.",
        "factory": "mcp_postgres",
        "required_args": ["connection_string"],
    },
    {
        "id": "slack",
        "name": "Slack (MCP)",
        "description": "Post and read messages across Slack channels.",
        "factory": "mcp_slack",
        "required_args": ["bot_token", "team_id"],
    },
    {
        "id": "gitlab",
        "name": "GitLab (MCP)",
        "description": "GitLab API access for projects, issues, and merge requests.",
        "factory": "mcp_gitlab",
        "required_args": ["token"],
    },
    {
        "id": "google_maps",
        "name": "Google Maps (MCP)",
        "description": "Geocoding, place search, and directions via Google Maps.",
        "factory": "mcp_google_maps",
        "required_args": ["api_key"],
    },
    {
        "id": "sequential_thinking",
        "name": "Sequential Thinking (MCP)",
        "description": "Structured step-by-step reasoning scaffold. No credentials needed.",
        "factory": "mcp_sequential_thinking",
        "required_args": [],
    },
    {
        "id": "time",
        "name": "Time (MCP)",
        "description": "Current time and timezone conversion.",
        "factory": "mcp_time",
        "required_args": [],
    },
    {
        "id": "everything",
        "name": "Everything (MCP)",
        "description": "Reference server exercising every MCP feature; useful for testing.",
        "factory": "mcp_everything",
        "required_args": [],
    },
]


__all__ = [
    "mcp_filesystem",
    "mcp_fetch",
    "mcp_git",
    "mcp_sqlite",
    "mcp_brave_search",
    "mcp_github",
    "mcp_puppeteer",
    "mcp_memory",
    "mcp_postgres",
    "mcp_slack",
    "mcp_gitlab",
    "mcp_google_maps",
    "mcp_sequential_thinking",
    "mcp_time",
    "mcp_everything",
    "KNOWN_MCPS",
]

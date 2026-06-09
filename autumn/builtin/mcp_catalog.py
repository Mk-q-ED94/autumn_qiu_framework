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
    "KNOWN_MCPS",
]

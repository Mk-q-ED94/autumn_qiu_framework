from typing import Any

from .mcp import MCPClient
from .tool import Tool, ToolParameter

# Top-level JSON Schema keys that are part of the "type definition" for a
# property. Everything else (`type`, `description`) is already first-class on
# ToolParameter; this list is the set we additionally preserve in `extra`.
_PASSTHROUGH_SCHEMA_KEYS = (
    "enum",          # restricted value set
    "items",         # array element schema
    "properties",    # nested object structure
    "default",       # default value
    "minimum",       # numeric lower bound
    "maximum",       # numeric upper bound
    "minLength",
    "maxLength",
    "pattern",
    "format",
    "anyOf",
    "oneOf",
    "allOf",
)


def _schema_to_parameters(input_schema: dict) -> list[ToolParameter]:
    """Convert an MCP tool's JSON-Schema input spec into ToolParameter records.

    Preserves complex schema fields (`enum`, `items`, `default`, etc.) via
    ToolParameter.extra so the model sees the full type constraints, not just
    the bare type tag.
    """
    props = (input_schema or {}).get("properties", {}) or {}
    required = set((input_schema or {}).get("required", []) or [])
    params: list[ToolParameter] = []
    for name, spec in props.items():
        extra = {k: spec[k] for k in _PASSTHROUGH_SCHEMA_KEYS if k in spec}
        params.append(ToolParameter(
            name=name,
            type=spec.get("type", "string"),
            description=spec.get("description", ""),
            required=name in required,
            extra=extra,
        ))
    return params


def _unwrap_content(content: Any) -> str:
    """Render an MCP tool result into a plain string the model can read.

    MCP returns a list of content blocks: ``[{"type": "text", "text": "..."},
    {"type": "image", ...}, {"type": "resource", ...}]``. We join all text
    blocks; non-text blocks are summarized with a tag so the model knows they
    existed but is not flooded with binary data.
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            parts.append(str(block))
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(block.get("text", ""))
        elif kind == "image":
            mime = block.get("mimeType", "image")
            parts.append(f"[image: {mime}]")
        elif kind == "resource":
            uri = (block.get("resource") or {}).get("uri", "")
            parts.append(f"[resource: {uri}]" if uri else "[resource]")
        else:
            parts.append(str(block))
    return "\n".join(p for p in parts if p)


def _make_caller(client: MCPClient, tool_name: str):
    async def _call(**kwargs):
        result = await client.call_tool(tool_name, kwargs)
        return _unwrap_content(result)
    return _call


async def mcp_to_tools(client: MCPClient) -> list[Tool]:
    """Convert all tools exposed by an MCP server into Autumn Tool objects.

    The returned Tools call back into the MCPClient when invoked, so the client
    must remain connected for the lifetime of the agent that uses them.
    """
    tools: list[Tool] = []
    for spec in await client.list_tools():
        name = spec["name"]
        tools.append(Tool(
            name=name,
            description=spec.get("description", ""),
            fn=_make_caller(client, name),
            parameters=_schema_to_parameters(spec.get("inputSchema", {})),
        ))
    return tools

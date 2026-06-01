from .mcp import MCPClient
from .tool import Tool, ToolParameter


def _schema_to_parameters(input_schema: dict) -> list[ToolParameter]:
    props = (input_schema or {}).get("properties", {}) or {}
    required = set((input_schema or {}).get("required", []) or [])
    params: list[ToolParameter] = []
    for name, spec in props.items():
        params.append(ToolParameter(
            name=name,
            type=spec.get("type", "string"),
            description=spec.get("description", ""),
            required=name in required,
        ))
    return params


def _make_caller(client: MCPClient, tool_name: str):
    async def _call(**kwargs):
        return await client.call_tool(tool_name, kwargs)
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

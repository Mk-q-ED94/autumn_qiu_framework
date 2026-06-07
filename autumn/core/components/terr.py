from .tool import Tool
from .skill import Skill
from .mcp import MCPClient


class Terr:
    """A named capability domain grouping related tools, skills, and MCP clients.

    Terr (域) is the organizational unit for bundling functionally similar or
    complementary capabilities — "search", "code", "data" — so they can be
    registered with an agent or framework in a single call.

    The model sees the individual tool/skill schemas as usual (flat, unchanged).
    The domain boundary is a developer-facing concept: it keeps related
    capabilities together and surfaces domain descriptions in the agent's system
    prompt so the model can reason about what areas of expertise are loaded.

    MCP clients in ``mcps`` are not connected here. Call ``Autumn.add_terr()``
    which handles the async connect → bridge → register pipeline. For direct
    Agent construction without the Autumn wrapper, pre-materialize MCPs via
    ``mcp_to_tools`` and pass the resulting Tool objects in ``tools``.
    """

    def __init__(
        self,
        name: str,
        description: str,
        tools: "list[Tool] | None" = None,
        skills: "list[Skill] | None" = None,
        mcps: "list[MCPClient] | None" = None,
    ):
        self.name = name
        self.description = description
        self.tools: list[Tool] = list(tools or [])
        self.skills: list[Skill] = list(skills or [])
        self.mcps: list[MCPClient] = list(mcps or [])
        for callable_obj in [*self.tools, *self.skills]:
            callable_obj.source_terr = name
            callable_obj.source_terr_description = description

    def __repr__(self) -> str:
        return (
            f"Terr({self.name!r}, tools={len(self.tools)}, "
            f"skills={len(self.skills)}, mcps={len(self.mcps)})"
        )

from pathlib import Path
from typing import AsyncIterator, Literal

from .config import AutumnConfig
from .interaction import UserInteraction
from .api.interfaces import A1, A2, A3
from .api.embedding import EmbeddingInterface
from .memory.backends import SQLiteBackend, HybridBackend, SQLiteVectorStore
from .memory.shared import SharedZone
from .memory.mom1 import Mom1
from .memory.mom2 import Mom2
from .memory.mom3 import Mom3
from .workspace.wp1 import WP1Tot
from .workspace.wp2 import WP2Tas
from .workspace.wp3 import WP3Mis
from .components.checker import Checker
from .components.agent import Agent
from .components.skill import Skill
from .components.tool import Tool
from .components.mcp import MCPClient
from .components.mcp_bridge import mcp_to_tools
from .types import MissionRoute, WorkflowRun
from ..plugins.loader import PluginLoader


class Autumn:
    """秋/Autumn — Multi-Model Collaborative Workflow Framework.

    Quick start:
        async with Autumn(config) as autumn:
            result = await autumn.process(user_input)

        # Stream chunks:
        async for chunk in autumn.stream(user_input):
            print(chunk, end="", flush=True)

        # With CLI interaction:
        from autumn import CLIInteraction
        async with Autumn(config, interaction=CLIInteraction()) as autumn:
            ...

        # Auto-load plugins from directories:
        Autumn(config, plugin_dirs=["./my_plugins"])

        # Attach an MCP server:
        client = StdioMCPClient(["python", "-m", "my_mcp_server"])
        await autumn.add_mcp(client)
    """

    def __init__(
        self,
        config: AutumnConfig,
        interaction: UserInteraction | None = None,
        plugin_dirs: list[str | Path] | None = None,
    ):
        self.config = config
        self.plugins = PluginLoader()
        self._mcp_clients: list[MCPClient] = []
        self._build(config, interaction)

        for d in (plugin_dirs or []):
            self.plugins.load_from_directory(d)

    def _build(self, config: AutumnConfig, interaction: UserInteraction | None) -> None:
        self.a1 = A1(config.a1)
        self.a2 = A2(config.a2)
        self.a3 = A3(config.a3)

        db = config.storage.db_path
        shared = SharedZone(HybridBackend(SQLiteBackend(db + ".shared")))

        self.mom2 = Mom2(HybridBackend(SQLiteBackend(db + ".mom2")), shared)
        self.mom3 = Mom3(HybridBackend(SQLiteBackend(db + ".mom3")), shared)
        self.mom1 = Mom1(HybridBackend(SQLiteBackend(db + ".mom1")), self.mom2, self.mom3)

        self._embedding: EmbeddingInterface | None = None
        if config.embedding is not None:
            self._embedding = EmbeddingInterface(config.embedding)
            for mom, suffix in [
                (self.mom1, "mom1"),
                (self.mom2, "mom2"),
                (self.mom3, "mom3"),
            ]:
                store = SQLiteVectorStore(f"{db}.{suffix}.vec")
                mom.enable_vector(self._embedding, store, auto_index=config.auto_index)

        p = config.prompts
        self.wp2 = WP2Tas(
            self.a2, self.mom2,
            system_prompt=p.wp2_task,
            tool_provider=self._collect_plugins,
        )
        self.wp3 = WP3Mis(self.a3, self.mom3, direct_prompt=p.wp3_direct, convert_prompt=p.wp3_convert)
        self.wp1 = WP1Tot(
            self.a1, self.mom1, self.wp2, self.wp3,
            interaction=interaction,
            selector_prompt=p.selector,
            headless_mission_route=config.headless_mission_route,
        )

        self.wp1.checker = Checker("wp1", self.a1, eval_prompt=p.wp1_checker)
        self.wp2.checker = Checker("wp2", self.a2, eval_prompt=p.wp2_checker)
        self.wp3.checker = Checker("wp3", self.a3, eval_prompt=p.wp3_checker)

    # ── public api ────────────────────────────────────────────────────────────

    async def process(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
    ) -> str:
        """Run the full pipeline and return the validated final output."""
        return await self.wp1.process(user_input, mission_route=mission_route)

    async def process_with_trace(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
    ) -> WorkflowRun:
        """Run the full pipeline and return output plus a structured workflow trace."""
        return await self.wp1.process_with_trace(user_input, mission_route=mission_route)

    async def stream(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
    ) -> AsyncIterator[str]:
        """Real-time streaming with post-hoc Checker advisory.

        Tokens flow from the chosen workspace (WP2 for tasks, WP3 for direct
        missions) straight to the caller. The Checker no longer gates output —
        instead, after the stream ends, it runs once as an observation; if it
        flags an issue, a clearly-marked advisory chunk is appended. The
        convert path remains buffered because conversion is a non-streamed
        model call.
        """
        async for chunk in self.wp1.stream(user_input, mission_route=mission_route):
            yield chunk

    # ── plugin & extension api ────────────────────────────────────────────────

    def _collect_plugins(self) -> tuple[list[Tool], list[Skill]]:
        """Snapshot currently-registered tools and skills for WP2's agent loop.

        Resolved fresh on each WP2 turn, so tools added at runtime (e.g. via
        ``add_mcp``) become available immediately. MCP tools appear here too —
        ``add_mcp`` registers them as :class:`Tool` instances.
        """
        tools: list[Tool] = []
        skills: list[Skill] = []
        for obj in self.plugins.all().values():
            if isinstance(obj, Tool):
                tools.append(obj)
            elif isinstance(obj, Skill):
                skills.append(obj)
        return tools, skills

    def register_tool(self, tool: Tool) -> None:
        self.plugins.register(tool.name, tool)

    def register_skill(self, skill: Skill) -> None:
        self.plugins.register(skill.name, skill)

    def register_agent(self, agent: Agent) -> None:
        self.plugins.register(agent.name, agent)

    async def add_mcp(self, client: MCPClient) -> list[Tool]:
        """Connect an MCP server and register all its tools as plugins.

        The client is owned by Autumn after this call: it will be disconnected
        on close(). Returns the list of registered Tool objects for inspection.
        """
        await client.connect()
        self._mcp_clients.append(client)
        tools = await mcp_to_tools(client)
        for tool in tools:
            self.register_tool(tool)
        return tools

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def end_session(self) -> None:
        """Clear short-term memory across all Mom areas, preserve long-term."""
        for mom in (self.mom1, self.mom2, self.mom3):
            backend = mom._backend
            if hasattr(backend, "clear_session"):
                await backend.clear_session()

    async def close(self) -> None:
        for client in self._mcp_clients:
            await client.disconnect()
        self._mcp_clients.clear()
        await self.a1.close()
        await self.a2.close()
        await self.a3.close()
        if self._embedding is not None:
            await self._embedding.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

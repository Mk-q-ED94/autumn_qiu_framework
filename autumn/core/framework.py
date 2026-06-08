from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Literal

from .config import AutumnConfig
from .interaction import UserInteraction
from .api.interfaces import A1, A2, A3, A4
from .api.embedding import EmbeddingInterface
from .memory.backends import SQLiteBackend, HybridBackend, SQLiteVectorStore
from .memory.shared import SharedZone
from .memory.mom1 import Mom1
from .memory.mom2 import Mom2
from .memory.mom3 import Mom3
from .memory.project import ProjectMemory, ProjectZone, project_context
from .workspace.wp1 import WP1Tot
from .workspace.wp2 import WP2Tas
from .workspace.wp3 import WP3Mis
from .components.checker import Checker
from .components.agent import Agent
from .components.skill import Skill
from .components.tool import Tool
from .components.terr import Terr
from .components.mcp import MCPClient
from .components.mcp_bridge import mcp_to_tools
from .types import InputType, MissionRoute, TaskType, WorkflowRun
from ..plugins.loader import PluginLoader


def _mark_terr_source(callable_obj, terr: Terr) -> None:
    callable_obj.source_terr = terr.name
    callable_obj.source_terr_description = terr.description


def _annotate_costs(run: WorkflowRun, config: AutumnConfig) -> WorkflowRun:
    """Fill per-stage ``cost_usd`` and ``run.total_cost_usd`` from slot prices.

    Each stage is priced by the workspace that produced it: WP1→a1, WP2→a2,
    WP3→a3 (tool stages inherit their workspace's slot). No-op when no slot has
    pricing configured, so unpriced setups see ``None`` exactly as before.
    """
    slots = {"WP1": config.a1, "WP2": config.a2, "WP3": config.a3}
    if not any(slot.has_pricing for slot in slots.values()):
        return run
    total = 0.0
    priced = False
    for stage in run.stages:
        slot = slots.get(stage.workspace)
        if slot is None or not slot.has_pricing:
            continue
        if stage.prompt_tokens is None and stage.completion_tokens is None:
            continue
        cost = slot.cost(stage.prompt_tokens, stage.completion_tokens)
        stage.cost_usd = round(cost, 6)
        total += cost
        priced = True
    if priced:
        run.total_cost_usd = round(total, 6)
    return run


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
        self.a4 = A4(config.a4) if config.a4 is not None else None

        db = config.storage.db_path
        b = config.behavior
        # Surface the shared zone on Autumn so callers (and add_memory_skills)
        # can bind to it without having to reach into Mom2.shared.
        self.shared = SharedZone(HybridBackend(SQLiteBackend(db + ".shared")))

        hist = b.history_limit
        self.mom2 = Mom2(HybridBackend(SQLiteBackend(db + ".mom2")), self.shared, history_limit=hist)
        self.mom3 = Mom3(HybridBackend(SQLiteBackend(db + ".mom3")), self.shared, history_limit=hist)
        self.mom1 = Mom1(
            HybridBackend(SQLiteBackend(db + ".mom1")), self.mom2, self.mom3, history_limit=hist
        )

        # Per-project shared memory: each project id gets its own isolated zone,
        # but within a project the zone is shared across every workspace and turn.
        # Resolved per-request via project_scope()/the active-project contextvar.
        self.projects = ProjectMemory(
            HybridBackend(SQLiteBackend(db + ".projects")), history_limit=hist
        )

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
            agent_max_steps=b.agent_max_steps,
        )
        self.wp3 = WP3Mis(self.a3, self.mom3, direct_prompt=p.wp3_direct, convert_prompt=p.wp3_convert)
        self.wp1 = WP1Tot(
            self.a1, self.mom1, self.wp2, self.wp3,
            interaction=interaction,
            selector_prompt=p.selector,
            headless_mission_route=config.headless_mission_route,
            validate_before_stream=config.validate_before_stream,
            confirm_threshold=b.confirm_threshold,
        )

        self.wp1.checker = Checker("wp1", self.a1, eval_prompt=p.wp1_checker, retries=b.checker_retries)
        self.wp2.checker = Checker("wp2", self.a2, eval_prompt=p.wp2_checker, retries=b.checker_retries)
        self.wp3.checker = Checker("wp3", self.a3, eval_prompt=p.wp3_checker, retries=b.checker_retries)

    # ── public api ────────────────────────────────────────────────────────────

    async def process(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
        input_type: InputType | None = None,
        task_type: TaskType | None = None,
    ) -> str:
        """Run the full pipeline and return the validated final output."""
        return await self.wp1.process(
            user_input,
            mission_route=mission_route,
            input_type=input_type,
            task_type=task_type,
        )

    async def process_with_trace(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
        input_type: InputType | None = None,
        task_type: TaskType | None = None,
    ) -> WorkflowRun:
        """Run the full pipeline and return output plus a structured workflow trace."""
        run = await self.wp1.process_with_trace(
            user_input,
            mission_route=mission_route,
            input_type=input_type,
            task_type=task_type,
        )
        return _annotate_costs(run, self.config)

    async def classify_intent(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
        input_type: InputType | None = None,
        task_type: TaskType | None = None,
    ):
        """Classify user input for desktop previews without executing the pipeline."""
        return await self.wp1.classify_intent(
            user_input,
            mission_route=mission_route,
            input_type=input_type,
            task_type=task_type,
        )

    async def stream(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
        input_type: InputType | None = None,
        task_type: TaskType | None = None,
    ) -> AsyncIterator[str]:
        """Real-time streaming with post-hoc Checker advisory.

        Tokens flow from the chosen workspace (WP2 for tasks, WP3 for direct
        missions) straight to the caller. The Checker no longer gates output —
        instead, after the stream ends, it runs once as an observation; if it
        flags an issue, a clearly-marked advisory chunk is appended. The
        convert path remains buffered because conversion is a non-streamed
        model call.
        """
        async for chunk in self.wp1.stream(
            user_input,
            mission_route=mission_route,
            input_type=input_type,
            task_type=task_type,
        ):
            yield chunk

    async def stream_with_trace(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
        input_type: InputType | None = None,
        task_type: TaskType | None = None,
    ) -> AsyncIterator[str | WorkflowRun]:
        """Stream chunks and finish with the WorkflowRun produced by the same turn."""
        async for event in self.wp1.stream_with_trace(
            user_input,
            mission_route=mission_route,
            input_type=input_type,
            task_type=task_type,
        ):
            if isinstance(event, WorkflowRun):
                yield _annotate_costs(event, self.config)
            else:
                yield event

    def describe_terrs(self) -> list[dict]:
        """Return serializable Terr summaries for desktop/debug UI."""
        summaries: list[dict] = []
        for terr in self.plugins.all_terrs().values():
            summaries.append({
                "name": terr.name,
                "description": terr.description,
                "enabled": self.plugins.is_terr_enabled(terr.name),
                "tools": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": [p.__dict__ for p in tool.parameters],
                    }
                    for tool in terr.tools
                ],
                "skills": [
                    {
                        "name": skill.name,
                        "description": skill.description,
                        "parameters": [p.__dict__ for p in skill.parameters],
                    }
                    for skill in terr.skills
                ],
                "mcps": [
                    {
                        "name": getattr(client, "name", type(client).__name__),
                        "description": type(client).__name__,
                    }
                    for client in terr.mcps
                ],
            })
        return summaries

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
            source_terr = getattr(obj, "source_terr", None)
            if source_terr and not self.plugins.is_terr_enabled(source_terr):
                continue
            if isinstance(obj, Tool):
                tools.append(obj)
            elif isinstance(obj, Skill):
                skills.append(obj)
        return tools, skills

    def add_memory_skills(self, area: str = "shared") -> None:
        """Register recall and remember Skills backed by a memory area.

        The Skills appear in the agent's ReAct trace so every memory read
        and write is visible in the workflow timeline.

        Parameters
        ----------
        area:
            Which memory zone to bind to.  One of ``"shared"``, ``"mom1"``,
            ``"mom2"``, ``"mom3"``, or ``"project"``.  Defaults to ``"shared"``
            so facts persist across workspaces.

            ``"project"`` binds the skills to the *context-active project's*
            shared zone: a single registration that transparently reads and
            writes whichever project is active for the current request (set via
            :meth:`project_scope`).
        """
        from .memory.skills import make_memory_skills, make_project_memory_skills
        if area == "project":
            for skill in make_project_memory_skills(self.projects, api=self.a4):
                self.register_skill(skill)
            return
        _areas = {
            "shared": self.shared,
            "mom1": self.mom1,
            "mom2": self.mom2,
            "mom3": self.mom3,
        }
        if area not in _areas:
            raise ValueError(
                f"Unknown memory area: {area!r}.  "
                f"Choose from: {list(_areas) + ['project']}"
            )
        for skill in make_memory_skills(_areas[area], api=self.a4):
            self.register_skill(skill)

    def project_zone(self, project_id: str | None = None) -> ProjectZone:
        """Return the dedicated shared memory zone for a project.

        Each project id gets its own isolated namespace; within a project the
        zone is shared across all workspaces and turns. Pass ``None`` for the
        default project.
        """
        return self.projects.zone(project_id)

    def project_scope(self, project_id: str | None):
        """Context manager binding ``project_id`` for project-scoped memory.

        While the block is active, memory skills registered with
        ``add_memory_skills("project")`` resolve to this project's shared zone::

            autumn.add_memory_skills("project")
            with autumn.project_scope("acme-app"):
                await autumn.process("remember the deploy target is fly.io")
        """
        return project_context(project_id)

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

    def register_terr(self, terr: Terr) -> None:
        """Register a capability domain whose tools/skills need no async setup.

        MCP clients inside the Terr are NOT connected — use add_terr() if the
        domain contains MCP servers that must be started first.
        """
        for tool in terr.tools:
            _mark_terr_source(tool, terr)
            self.register_tool(tool)
        for skill in terr.skills:
            _mark_terr_source(skill, terr)
            self.register_skill(skill)
        self.plugins.register_terr(terr)

    def set_terr_enabled(self, name: str, enabled: bool) -> dict:
        self.plugins.set_terr_enabled(name, enabled)
        for summary in self.describe_terrs():
            if summary["name"] == name:
                return summary
        raise KeyError(name)

    @asynccontextmanager
    async def open_terr(self, terr: Terr):
        """Register a capability domain for the duration of the ``async with`` block.

        On entry: MCP servers are connected, their tools bridged and registered
        alongside the Terr's direct tools and skills.
        On exit: MCP servers are disconnected and every tool/skill added by this
        call is removed from the plugin registry.

        Use this for one-shot sessions or when a domain should not outlive a
        single operation. For permanent registration use ``add_terr()`` instead.
        """
        registered_tool_names: list[str] = []
        registered_skill_names: list[str] = []
        connected_clients: list[MCPClient] = []

        try:
            for client in terr.mcps:
                await client.connect()
                connected_clients.append(client)
                for tool in await mcp_to_tools(client):
                    _mark_terr_source(tool, terr)
                    self.register_tool(tool)
                    registered_tool_names.append(tool.name)

            for tool in terr.tools:
                _mark_terr_source(tool, terr)
                self.register_tool(tool)
                registered_tool_names.append(tool.name)

            for skill in terr.skills:
                _mark_terr_source(skill, terr)
                self.register_skill(skill)
                registered_skill_names.append(skill.name)

            self.plugins.register_terr(terr)
            yield terr
        finally:
            for client in connected_clients:
                await client.disconnect()
            for name in registered_tool_names:
                self.plugins.unregister(name)
            for name in registered_skill_names:
                self.plugins.unregister(name)
            self.plugins.unregister_terr(terr.name)

    async def add_terr(self, terr: Terr) -> None:
        """Register a capability domain, connecting any embedded MCP servers.

        All MCP clients in the Terr are connected and their tools are bridged to
        Tool objects and registered alongside the Terr's direct tools and skills.
        The MCP clients are owned by Autumn after this call and disconnected on
        close().
        """
        for client in terr.mcps:
            await client.connect()
            self._mcp_clients.append(client)
            for tool in await mcp_to_tools(client):
                _mark_terr_source(tool, terr)
                self.register_tool(tool)
        for tool in terr.tools:
            _mark_terr_source(tool, terr)
            self.register_tool(tool)
        for skill in terr.skills:
            _mark_terr_source(skill, terr)
            self.register_skill(skill)
        self.plugins.register_terr(terr)

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
        if self.a4 is not None:
            await self.a4.close()
        if self._embedding is not None:
            await self._embedding.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

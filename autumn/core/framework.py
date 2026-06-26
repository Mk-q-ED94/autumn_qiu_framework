import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from ..plugins.loader import PluginLoader
from .api.embedding import EmbeddingInterface
from .api.interfaces import A1, A2, A3, A4
from .components.agent import Agent, _format_memory_context
from .components.checker import Checker
from .components.mcp import MCPClient
from .components.mcp_bridge import mcp_to_tools
from .components.skill import Skill
from .components.terr import Terr
from .components.tool import Tool
from .codebase import CodebaseMemory
from .config import AutumnConfig
from .interaction import UserInteraction
from .memory.backends import (
    HybridBackend,
    MarkdownBackend,
    SQLiteBackend,
    SQLiteLexicalStore,
    SQLiteVectorStore,
)
from .memory.base import MemoryArea
from .memory.dimensions import ActivationContext
from .memory.mom1 import Mom1
from .memory.mom2 import Mom2
from .memory.mom3 import Mom3
from .memory.project import (
    ProjectMemory,
    ProjectZone,
    get_current_project,
    project_context,
)
from .memory.access import Mom1AccessBroker
from .memory.shared import SharedZone
from .types import InputType, MissionRoute, TaskType, WorkflowRun, WorkflowStage
from .workspace.wp1 import WP1Tot
from .workspace.wp2 import WP2Tas
from .workspace.wp3 import WP3Mis
from .workspace.wp4 import WP4Mem


# How many recent Mom1 turns to pull into the executor prompt each turn.
_TURN_RECALL_K = 5


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
        # MCP clients owned by each added Terr, so remove_terr/reload_terr can
        # disconnect exactly the servers that domain brought online.
        self._terr_clients: dict[str, list[MCPClient]] = {}
        self._build(config, interaction)

        for d in (plugin_dirs or []):
            self.plugins.load_from_directory(d)

    def _build(self, config: AutumnConfig, interaction: UserInteraction | None) -> None:
        self.a1 = A1(config.a1)
        self.a2 = A2(config.a2)
        self.a3 = A3(config.a3)
        self.a4 = A4(config.a4) if config.a4 is not None else None

        # Codebase-memory token-saving layer (off until start_codebase_memory()).
        # The brief provider is wired into WP2 unconditionally and reads these
        # live, so the layer can be toggled at runtime without a rebuild.
        self.codebase: CodebaseMemory | None = None
        self._codebase_client: MCPClient | None = None
        self._codebase_terr_names: list[str] = []
        self._codebase_index_task: "asyncio.Task | None" = None

        db = config.storage.db_path
        b = config.behavior
        hist = b.history_limit
        decay = b.memory_decay_half_life or None
        fourd = b.fourd_memory_enabled

        # Long-term backend factory. "sqlite" (default) keeps the historical
        # file-per-zone DB; "markdown" stores readable .md entries with 4D
        # frontmatter under "<db>.mdstore/<zone>/". Both are wrapped in
        # HybridBackend for the short-term session cache, so the choice is
        # transparent to every zone above.
        markdown = config.storage.backend == "markdown"

        def _zone(suffix: str) -> HybridBackend:
            if markdown:
                return HybridBackend(MarkdownBackend(f"{db}.mdstore/{suffix}"))
            return HybridBackend(SQLiteBackend(f"{db}.{suffix}"))

        # Surface the shared zone on Autumn so callers (and add_memory_skills)
        # can bind to it without having to reach into Mom2.shared.
        self.shared = SharedZone(
            _zone("shared"),
            history_limit=hist, decay_half_life=decay, fourd_enabled=fourd,
        )

        self.mom2 = Mom2(
            _zone("mom2"), self.shared,
            history_limit=hist, decay_half_life=decay, fourd_enabled=fourd,
        )
        self.mom3 = Mom3(
            _zone("mom3"), self.shared,
            history_limit=hist, decay_half_life=decay, fourd_enabled=fourd,
        )
        self.mom1 = Mom1(
            _zone("mom1"), self.mom2, self.mom3,
            history_limit=hist, decay_half_life=decay, fourd_enabled=fourd,
        )

        # Per-project shared memory: each project id gets its own isolated zone,
        # but within a project the zone is shared across every workspace and turn.
        # Resolved per-request via project_scope()/the active-project contextvar.
        self.projects = ProjectMemory(
            _zone("projects"),
            history_limit=hist, decay_half_life=decay, fourd_enabled=fourd,
        )

        # WP4 (A4) — the dedicated memory-management workspace. It owns the A4
        # slot and curates every zone above: recall synthesis and consolidation
        # run on A4, while forget/stats/pin delegate to the target area. Its own
        # audit log records each management action it performs.
        self.wp4 = WP4Mem(
            self.a4,
            MemoryArea(
                "wp4", _zone("wp4"),
                history_limit=hist, decay_half_life=decay, fourd_enabled=fourd,
            ),
            zones={
                "mom1": self.mom1,
                "mom2": self.mom2,
                "mom3": self.mom3,
                "shared": self.shared,
            },
            projects=self.projects,
            # Delegate heavy cognitive ops to A1 (strong model) when enabled (default).
            # A4 handles mechanical memory ops; A1 handles reasoning-heavy synthesis.
            delegation_api=self.a1 if b.delegate_on else None,
            delegation_threshold=b.a4_delegation_threshold,
            # Project discussion is always A1-owned and is independent from the
            # optional A4 heavy-memory delegation switch above.
            project_api=self.a1,
            # External-retrieval augmentation: A4.research() pulls these skills from
            # the knowledge Terr (registered below when a4_knowledge_terr is on).
            research_provider=self._collect_knowledge_skills,
        )

        # Governed upward channel: Mom2/Mom3 may *request* a Mom1 read, A1
        # adjudicates, A4 mediates a restricted answer, WP4's log audits it. The
        # asymmetric default isolation is preserved — this only adds a gated path.
        self.mom1_access = Mom1AccessBroker(
            mom1=self.mom1,
            adjudicator=self.a1,
            mediator=self.a4,
            audit=self.wp4.memory,
            enabled=b.mom1_access_enabled,
        )
        self.mom2.attach_mom1_broker(self.mom1_access)
        self.mom3.attach_mom1_broker(self.mom1_access)

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

        # Lexical (BM25) recall — opt-in keyword half of hybrid retrieval (P1-B).
        # Auto-indexes on append so it works out of the box; fused with vector
        # results (when present) by RRF inside recall. Off by default.
        if b.lexical_recall_enabled:
            for mom, suffix in [
                (self.mom1, "mom1"),
                (self.mom2, "mom2"),
                (self.mom3, "mom3"),
            ]:
                mom.enable_lexical(SQLiteLexicalStore(f"{db}.{suffix}.fts"), auto_index=True)

        # Background indexing (P2-B): decouple embedding/lexical indexing from the
        # write path so a slow/down embedding service never blocks (or breaks) an
        # append. Off by default → synchronous, unchanged. flush_index() runs on
        # close so in-flight indexing completes before the embedding client shuts.
        if b.async_index:
            for mom in (self.mom1, self.mom2, self.mom3):
                mom.set_async_index(True)

        # Knowledge Terr (0.3.0): A4's external-retrieval engine. Registered here so
        # research() can resolve its skills; also available to A2/A3 like any Terr.
        if b.knowledge_terr_on:
            from ..builtin.knowledge_terr import knowledge_terr
            self.register_terr(knowledge_terr(recall_fn=self._knowledge_recall))

        p = config.prompts
        self.wp2 = WP2Tas(
            self.a2, self.mom2,
            system_prompt=p.wp2_task,
            tool_provider=self._collect_plugins,
            agent_max_steps=b.agent_max_steps,
            # Always wired; returns "" until the codebase layer is started, so a
            # runtime toggle takes effect without rebuilding WP2.
            codebase_brief_provider=self._codebase_brief,
        )
        self.wp3 = WP3Mis(
            self.a3, self.mom3,
            direct_prompt=p.wp3_direct,
            convert_prompt=p.wp3_convert,
            # Always wire the provider; it re-reads lite_skills_on() each turn and
            # returns [] when the master switch / whitelist is off, so the gate
            # stays live (a runtime config flip takes effect) like every other.
            skill_provider=self._collect_a3_skills,
        )
        self.wp1 = WP1Tot(
            self.a1, self.mom1, self.wp2, self.wp3,
            wp4=self.wp4,
            projects=self.projects,
            mom1_access=self.mom1_access,
            interaction=interaction,
            selector_prompt=p.selector,
            headless_mission_route=config.headless_mission_route,
            validate_before_stream=config.validate_before_stream,
            confirm_threshold=b.confirm_threshold,
            task_planning=b.task_planning_on,
            supervision=b.supervision_on,
            archive=b.archive_on,
            capability_provider=self._capability_digest,
        )

        self.wp1.checker = Checker("wp1", self.a1, eval_prompt=p.wp1_checker, retries=b.checker_retries)
        self.wp2.checker = Checker("wp2", self.a2, eval_prompt=p.wp2_checker, retries=b.checker_retries)
        self.wp3.checker = Checker("wp3", self.a3, eval_prompt=p.wp3_checker, retries=b.checker_retries)

    # ── public api ────────────────────────────────────────────────────────────

    async def _active_goal(self) -> str | None:
        """Best-effort: the active project's master goal, for goal-gated push.

        Lets ``aim.goal_ref``-tagged CONSTRAIN/REMIND memories fire when they
        match the project the turn is scoped to — the RFC's flagship activation
        path, which was dead on-path because the turn never supplied a goal.
        Returns ``None`` when no project is in scope or the read fails; push then
        falls back to empty-aim and cue-overlap gating exactly as before.
        """
        pid = get_current_project()
        if not pid:
            return None
        try:
            meta = await self.projects.get_metadata(pid)
        except Exception:
            return None
        return meta.goals.master or None

    async def _compute_push(self, user_input: str, goal: str | None = None) -> tuple[str, int, float]:
        """Run the 4D push engine for the current turn.

        Returns ``(fragment, fired_count, elapsed_ms)``. When push is disabled
        or nothing fires, returns ``("", 0, 0.0)`` — callers can test the
        fragment truthiness to skip the push stage entirely. ``goal`` gates
        ``aim.goal_ref`` activation; when omitted it is derived from the active
        project so goal-tagged memories fire without the caller wiring it.
        """
        if not self.config.behavior.fourd_push_on_turn:
            return "", 0, 0.0
        from .workspace.wp4 import render_push_context

        if goal is None:
            goal = await self._active_goal()
        t = time.perf_counter()
        turn_cues = [tok for tok in user_input.split() if tok]
        ctx = ActivationContext(
            now=time.time(), query=user_input or None, goal=goal, cues=turn_cues,
        )
        fired = await self.wp4.activate_push(area="mom1", ctx=ctx)
        fragment = render_push_context(fired)
        ms = round((time.perf_counter() - t) * 1000, 1)
        return fragment, len(fired), ms

    async def _compute_recall(self, user_input: str) -> tuple[str, int, float]:
        """Pull recent cross-turn context from Mom1 (the read-all zone) for this turn.

        Mom1 accumulates every turn's input/output but is otherwise never read
        back on the default path — its advertised "reads all" authority was inert.
        This is the *pull* half of 4D memory, symmetric with ``_compute_push``:
        the executor (WP2/WP3) gets the recent conversation it would otherwise be
        blind to. Returns ``("", 0, 0.0)`` when disabled or Mom1 is empty, so the
        caller can skip the recall stage entirely.
        """
        if not self.config.behavior.fourd_pull_on_turn:
            return "", 0, 0.0
        t = time.perf_counter()
        try:
            history = await self.mom1.get_history(n=_TURN_RECALL_K)
        except Exception:
            return "", 0, 0.0
        fragment = _format_memory_context(history)
        # Count entries that actually rendered (each is one "\n- " bullet), not the
        # raw history length — non-conversational entries (e.g. CONSTRAIN strings)
        # are dropped by the renderer, so len(history) would over-report the stage.
        count = fragment.count("\n- ") if fragment else 0
        ms = round((time.perf_counter() - t) * 1000, 1)
        return fragment, count, ms

    async def _compute_turn_context(self, user_input: str, goal: str | None = None) -> dict:
        """Assemble the turn's memory context: pull (Mom1 recall) + push (4D).

        Returns the kwargs threaded into WP1's process/stream entry points. The
        recall and push fragments are joined into a single ``push_context`` the
        executors receive, while ``recall_count``/``push_count`` keep their trace
        stages distinct. ``goal`` is forwarded to the push engine's aim gate.
        """
        recall_frag, recall_count, recall_ms = await self._compute_recall(user_input)
        push_frag, push_count, push_ms = await self._compute_push(user_input, goal=goal)
        turn_context = "\n\n".join(f for f in (recall_frag, push_frag) if f)
        return {
            "push_context": turn_context,
            "push_count": push_count,
            "push_ms": push_ms,
            "recall_count": recall_count,
            "recall_ms": recall_ms,
        }

    async def _auto_annotate_turn(self) -> "WorkflowStage | None":
        """Best-effort: annotate the most-recent Mom1 entry via A4.

        Runs after each turn write so entries accumulate 4D dimensions on the
        default path without manual HTTP calls. Gated on A4 slot and the
        ``fourd_auto_annotate`` flag (default: on). Returns a trace stage when
        annotation fires, ``None`` otherwise — never raises.
        """
        if not self.config.behavior.fourd_auto_annotate:
            return None
        if not self.wp4.has_model:
            return None
        started = time.perf_counter()
        try:
            result = await self.wp4.annotate_recent(area="mom1", n=1, only_unannotated=True)
        except Exception:
            return None
        annotated = result.get("annotated", 0)
        if not annotated:
            return None
        return WorkflowStage(
            id="wp4.annotate",
            title="A4 自动标注",
            detail=f"已为 {annotated} 条 Mom1 记忆标注 4D 维度",
            workspace="WP4",
            kind="stage",
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    async def _auto_consolidate_turn(self) -> "WorkflowStage | None":
        """Best-effort: consolidate Mom1 when history nears the history_limit.

        Runs after each turn write and fires when Mom1 holds ≥ 80 % of the
        configured limit — calling ``wp4.consolidate`` so A4's curator lifecycle
        runs automatically rather than only on manual HTTP triggers. Gated on A4
        slot and ``fourd_auto_consolidate`` (default: on). Returns a trace stage
        when consolidation fires, ``None`` otherwise — never raises.
        """
        if not self.config.behavior.fourd_auto_consolidate:
            return None
        if not self.wp4.has_model:
            return None
        limit = self.config.behavior.history_limit
        try:
            history = await self.mom1.get_history()
            if len(history) < int(limit * 0.8):
                return None
        except Exception:
            return None
        started = time.perf_counter()
        try:
            summary = await self.wp4.consolidate(area="mom1")
        except Exception:
            return None
        if summary is None:
            return None
        return WorkflowStage(
            id="wp4.consolidate",
            title="A4 自动整合",
            detail="Mom1 历史已整合为摘要条目",
            workspace="WP4",
            kind="stage",
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    async def process(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
        input_type: InputType | None = None,
        task_type: TaskType | None = None,
        goal: str | None = None,
    ) -> str:
        """Run the full pipeline and return the validated final output."""
        ctx = await self._compute_turn_context(user_input, goal=goal)
        run = await self.wp1.process_with_trace(
            user_input,
            mission_route=mission_route,
            input_type=input_type,
            task_type=task_type,
            **ctx,
        )
        return run.output

    async def process_with_trace(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
        input_type: InputType | None = None,
        task_type: TaskType | None = None,
        goal: str | None = None,
    ) -> WorkflowRun:
        """Run the full pipeline and return output plus a structured workflow trace."""
        ctx = await self._compute_turn_context(user_input, goal=goal)
        run = await self.wp1.process_with_trace(
            user_input,
            mission_route=mission_route,
            input_type=input_type,
            task_type=task_type,
            **ctx,
        )
        # Per-turn memory lifecycle: annotate the newly-written Mom1 entry, then
        # consolidate if approaching the history limit. Both are best-effort (A4-gated)
        # and never interfere with the turn output — they only enrich future turns.
        for stage in (
            await self._auto_annotate_turn(),
            await self._auto_consolidate_turn(),
        ):
            if stage is not None:
                run.stages.append(stage)
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
        goal: str | None = None,
    ) -> AsyncIterator[str]:
        """Real-time streaming with post-hoc Checker advisory.

        Tokens flow from the chosen workspace (WP2 for tasks, WP3 for direct
        missions) straight to the caller. The Checker no longer gates output —
        instead, after the stream ends, it runs once as an observation; if it
        flags an issue, a clearly-marked advisory chunk is appended. The
        convert path remains buffered because conversion is a non-streamed
        model call.
        """
        ctx = await self._compute_turn_context(user_input, goal=goal)
        async for event in self.wp1.stream_with_trace(
            user_input,
            mission_route=mission_route,
            input_type=input_type,
            task_type=task_type,
            **ctx,
        ):
            if isinstance(event, str):
                yield event

    async def stream_with_trace(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
        input_type: InputType | None = None,
        task_type: TaskType | None = None,
        goal: str | None = None,
    ) -> AsyncIterator[str | WorkflowRun]:
        """Stream chunks and finish with the WorkflowRun produced by the same turn."""
        ctx = await self._compute_turn_context(user_input, goal=goal)
        async for event in self.wp1.stream_with_trace(
            user_input,
            mission_route=mission_route,
            input_type=input_type,
            task_type=task_type,
            **ctx,
        ):
            if isinstance(event, WorkflowRun):
                # Per-turn memory lifecycle hooks (same as process_with_trace).
                for stage in (
                    await self._auto_annotate_turn(),
                    await self._auto_consolidate_turn(),
                ):
                    if stage is not None:
                        event.stages.append(stage)
                yield _annotate_costs(event, self.config)
            else:
                yield event

    def describe_terrs(self) -> list[dict]:
        """Return serializable Terr summaries for desktop/debug UI."""
        return [
            {
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
            }
            for terr in self.plugins.all_terrs().values()
        ]

    async def active_context(
        self,
        text: str = "",
        cues: list[str] | None = None,
        goal: str | None = None,
        area: str = "mom1",
        k: int = 5,
        reinforce: bool = False,
    ) -> str:
        """Push-activate a zone for the current turn → an injectable prompt fragment.

        Scans *area* for CONSTRAIN/REMIND memories whose ``trigger``/``aim`` gates
        open against the turn context (``cues``/``goal``, plus naive tokens from
        ``text``), and renders them as a constraints+reminders block ready to
        prepend to a system prompt. Returns "" when push is disabled or nothing
        fires, so callers can use it unconditionally.

        Opt-in: gated by ``behavior.fourd_push_on_turn`` (default off). This is
        the public seam for wiring push into a turn; the core workflow does not
        call it automatically yet.
        """
        if not self.config.behavior.fourd_push_on_turn:
            return ""
        from .workspace.wp4 import render_push_context

        turn_cues = list(cues or [])
        turn_cues += [t for t in text.split() if t]  # naive; explicit cues preferred
        ctx = ActivationContext(
            now=time.time(), query=text or None, goal=goal, cues=turn_cues,
        )
        fired = await self.wp4.activate_push(area=area, ctx=ctx, k=k, reinforce=reinforce)
        return render_push_context(fired)

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

    def _collect_a3_skills(self) -> list[Skill]:
        """Snapshot the curated lite-skill set for WP3's bounded direct loop.

        Resolved fresh each turn. Only skills whose name appears in
        ``BehaviorConfig.a3_lite_skills`` and whose Terr (if any) is enabled
        are included — A3 gets a narrow, safe subset, not the full WP2 bag.
        """
        whitelist = set(self.config.behavior.lite_skills_on())
        if not whitelist:
            return []
        skills: list[Skill] = []
        for obj in self.plugins.all().values():
            if not isinstance(obj, Skill):
                continue
            if obj.name not in whitelist:
                continue
            source_terr = getattr(obj, "source_terr", None)
            if source_terr and not self.plugins.is_terr_enabled(source_terr):
                continue
            skills.append(obj)
        return skills

    def _collect_knowledge_skills(self) -> list[Skill]:
        """Snapshot the enabled ``knowledge`` Terr's skills for A4.research().

        Returns ``[]`` when the knowledge Terr isn't registered/enabled, so
        ``WP4Mem.research`` degrades gracefully to an "unavailable" message.
        """
        if not self.plugins.is_terr_enabled("knowledge"):
            return []
        return [
            obj
            for obj in self.plugins.all().values()
            if isinstance(obj, Skill) and getattr(obj, "source_terr", None) == "knowledge"
        ]

    async def _knowledge_recall(self, query: str, k: int) -> str:
        """Local-knowledge-store backing for the knowledge Terr's KB-query skill.

        Reads the shared zone (the cross-workspace knowledge zone) and returns
        formatted snippets, so A4's research loop can consult prior facts.
        """
        entries = await self.shared.recall(query, k=k)
        if not entries:
            return f"[no local knowledge found for {query!r}]"
        return "\n".join(f"- {e.text}" for e in entries)

    def _capability_digest(self) -> str:
        """Render a compact digest of enabled capability domains for the Selector.

        Lets A1 route with awareness of what the system can actually do — e.g.
        leaning TASK when a relevant code/tool domain is loaded. Returns "" when
        nothing is registered (the Selector then behaves exactly as before).
        """
        lines: list[str] = []
        for terr in self.plugins.all_terrs().values():
            if not self.plugins.is_terr_enabled(terr.name):
                continue
            lines.append(f"- {terr.name}: {terr.description}")
        if not lines:
            return ""
        return "Loaded capability domains (the system can act in these areas):\n" + "\n".join(lines)

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

        The skills are built by WP4, the memory-management workspace, so they
        share the A4 model and zone resolution WP4 uses everywhere else.

        """
        for skill in self.wp4.skills(area):
            self.register_skill(skill)

    def add_mom1_access_skill(self, area: str = "mom2") -> None:
        """Register the ``request_mom1_access`` skill for a task/mission zone.

        Exposes the governed upward channel (:attr:`mom1_access`) to the agent
        ReAct loop: a WP2/WP3 agent can file an adjudicated, A4-mediated request
        to read Mom1 instead of being hard-walled off from it. Every request is
        adjudicated by A1 and audited in WP4's log, so the asymmetric isolation
        is preserved — this only makes the gated path *reachable*.

        Parameters
        ----------
        area:
            Which requester zone files the request — ``"mom2"`` (task, default)
            or ``"mom3"`` (mission). Determines the audit log's requester field.

        No-op-safe: if the broker was disabled (``MOM1_ACCESS_ENABLED=0``) the
        skill still registers but every request returns a denial.
        """
        from .memory.skills import make_mom1_access_skill
        requester = {"mom2": self.mom2, "mom3": self.mom3}.get(area)
        if requester is None:
            raise ValueError(
                f"add_mom1_access_skill area must be 'mom2' or 'mom3', not {area!r}.",
            )
        self.register_skill(make_mom1_access_skill(requester))

    def configure_4d(
        self,
        *,
        memory_enabled: bool | None = None,
        push_on_turn: bool | None = None,
        pull_on_turn: bool | None = None,
        auto_annotate: bool | None = None,
        auto_consolidate: bool | None = None,
        mom1_access_enabled: bool | None = None,
    ) -> dict[str, bool]:
        """Flip the 4D-memory switches at runtime; returns the resulting state.

        These otherwise come only from the environment at construction. Each
        argument left ``None`` is unchanged. The changes take effect immediately:

        - ``memory_enabled`` propagates to every managed zone's recall/eviction
          ranking (``MemoryArea.set_fourd_enabled``), including cached project
          zones.
        - ``push_on_turn`` / ``pull_on_turn`` / ``auto_annotate`` /
          ``auto_consolidate`` are read live each turn from ``config.behavior``,
          so mutating them is enough.
        - ``mom1_access_enabled`` flips the broker's gate in place.
        """
        b = self.config.behavior
        if memory_enabled is not None:
            b.fourd_memory_enabled = memory_enabled
            self.wp4.set_fourd_enabled(memory_enabled)
        if push_on_turn is not None:
            b.fourd_push_on_turn = push_on_turn
        if pull_on_turn is not None:
            b.fourd_pull_on_turn = pull_on_turn
        if auto_annotate is not None:
            b.fourd_auto_annotate = auto_annotate
        if auto_consolidate is not None:
            b.fourd_auto_consolidate = auto_consolidate
        if mom1_access_enabled is not None:
            b.mom1_access_enabled = mom1_access_enabled
            self.mom1_access.enabled = mom1_access_enabled
        return {
            "fourd_memory_enabled": b.fourd_memory_enabled,
            "fourd_push_on_turn": b.fourd_push_on_turn,
            "fourd_pull_on_turn": b.fourd_pull_on_turn,
            "fourd_auto_annotate": b.fourd_auto_annotate,
            "fourd_auto_consolidate": b.fourd_auto_consolidate,
            "mom1_access_enabled": b.mom1_access_enabled,
        }

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
        close(). If any embedded MCP fails to connect, the partial registration
        is rolled back so a failure can't leave half a Terr live (orphaned tools
        plus a connected-but-unregistered MCP server).
        """
        connected_clients: list[MCPClient] = []
        registered_names: list[str] = []
        bridged_names: list[str] = []
        try:
            for client in terr.mcps:
                await client.connect()
                connected_clients.append(client)
                self._mcp_clients.append(client)
                for tool in await mcp_to_tools(client):
                    _mark_terr_source(tool, terr)
                    self.register_tool(tool)
                    registered_names.append(tool.name)
                    bridged_names.append(tool.name)
            for tool in terr.tools:
                _mark_terr_source(tool, terr)
                self.register_tool(tool)
                registered_names.append(tool.name)
            for skill in terr.skills:
                _mark_terr_source(skill, terr)
                self.register_skill(skill)
                registered_names.append(skill.name)
            # Pass the MCP-bridged tool names too so a later remove_terr can
            # unregister them (they aren't on terr.tools/terr.skills).
            self.plugins.register_terr(terr, extra_callables=tuple(bridged_names))
            self._terr_clients[terr.name] = connected_clients
        except Exception:
            for name in registered_names:
                self.plugins.unregister(name)
            for client in connected_clients:
                try:
                    self._mcp_clients.remove(client)
                except ValueError:
                    pass
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001 — rollback is best-effort
                    pass
            raise

    async def remove_terr(self, name: str) -> bool:
        """Tear down a registered Terr at runtime, no restart required.

        Unregisters every tool/skill the domain owns (including MCP-bridged
        tools), disconnects and drops any MCP servers it brought online, and
        forgets the domain. Idempotent: returns ``False`` for an unknown Terr,
        ``True`` when something was removed. ``_collect_plugins`` resolves fresh
        each turn, so the removed capabilities vanish from the model on the very
        next turn.
        """
        known = name in self.plugins.all_terrs()
        self.plugins.remove_terr(name)
        for client in self._terr_clients.pop(name, []):
            try:
                self._mcp_clients.remove(client)
            except ValueError:
                pass
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001 — teardown is best-effort
                pass
        return known

    async def reload_terr(self, terr: Terr) -> None:
        """Hot-swap a capability domain: remove the existing Terr of the same
        name (if any) and register the new definition in its place.

        Lets an edited/rebuilt Terr take effect without a restart, while
        preserving the prior enabled/disabled state so a domain a user had
        switched off stays off across the swap.
        """
        was_disabled = (
            terr.name in self.plugins.all_terrs()
            and not self.plugins.is_terr_enabled(terr.name)
        )
        await self.remove_terr(terr.name)
        await self.add_terr(terr)
        if was_disabled:
            self.plugins.set_terr_enabled(terr.name, False)

    # ── codebase-memory token-saving layer ──────────────────────────────────────

    _CODEBASE_TERR_DESC = (
        "Codebase knowledge graph — query code structure (definitions, call "
        "graph, imports, architecture, routes) instead of reading files. Prefer "
        "search_graph / trace_path / get_architecture / query_graph / "
        "get_code_snippet over opening files; it is far cheaper in tokens."
    )

    async def _codebase_brief(self, task_input: str, task_type: TaskType | None) -> str:
        """WP2 brief provider: a code-structure digest for CODE tasks, else "".

        Gated here (not in WP2) so the executor stays generic: only code-shaped
        tasks pay for the brief, and only when the layer is actually running.
        """
        cb = self.codebase
        if cb is None or task_type != TaskType.CODE:
            return ""
        return await cb.architecture_brief()

    async def start_codebase_memory(self, repo: str | None = None) -> bool:
        """Bring the code-graph layer online: connect, register tools, pre-warm.

        Builds the ``codebase-memory-mcp`` client (catalog factory), connects it,
        registers its tools as a native ``codebase`` Terr so the agent can run
        deep graph queries, wraps it in :class:`CodebaseMemory` for the proactive
        brief, and kicks off indexing in the background so the first code task is
        fast. Idempotent; re-pointing at a different repo reconnects + re-indexes.
        Returns True once the MCP server is connected (indexing may still run).
        """
        from ..builtin.mcp_catalog import mcp_codebase_memory

        b = self.config.behavior
        target = (repo if repo is not None else b.codebase_memory_repo) or ""
        target = target.strip()
        if self.codebase is not None:
            if target == self.codebase.repo:
                return True  # already running on this repo
            await self.stop_codebase_memory()

        client = mcp_codebase_memory(target or None)
        await client.connect()
        self._codebase_client = client
        self._mcp_clients.append(client)

        terr = Terr(name="codebase", description=self._CODEBASE_TERR_DESC)
        tools = await mcp_to_tools(client)
        self._codebase_terr_names = []
        for tool in tools:
            _mark_terr_source(tool, terr)
            self.register_tool(tool)
            self._codebase_terr_names.append(tool.name)
        self.plugins.register_terr(terr)

        self.codebase = CodebaseMemory(client, target)
        b.codebase_memory_repo = target
        # Pre-warm the index off the turn path; the brief awaits the same lock.
        self._codebase_index_task = asyncio.create_task(self.codebase.ensure_indexed())

        def _consume_index_result(task: asyncio.Task) -> None:
            # Retrieve the result so a failure never surfaces as an "exception
            # never retrieved" warning. ensure_indexed is failure-tolerant today,
            # but this keeps the detached task safe if that ever changes.
            if not task.cancelled():
                task.exception()

        self._codebase_index_task.add_done_callback(_consume_index_result)
        return True

    async def stop_codebase_memory(self) -> None:
        """Tear down the code-graph layer: unregister tools/Terr, disconnect, idle."""
        if self._codebase_index_task is not None:
            self._codebase_index_task.cancel()
            self._codebase_index_task = None
        for name in self._codebase_terr_names:
            self.plugins.unregister(name)
        self._codebase_terr_names = []
        self.plugins.unregister_terr("codebase")
        client = self._codebase_client
        self._codebase_client = None
        self.codebase = None
        if client is not None:
            try:
                self._mcp_clients.remove(client)
            except ValueError:
                pass
            try:
                await client.disconnect()
            except Exception:
                pass

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def end_session(self) -> None:
        """Clear short-term memory across all Mom areas, preserve long-term."""
        for mom in (self.mom1, self.mom2, self.mom3):
            backend = mom._backend
            if hasattr(backend, "clear_session"):
                await backend.clear_session()

    async def close(self) -> None:
        # Best-effort teardown: one failing step (a flaky MCP server raising on
        # disconnect, say) must not strand the remaining clients — every other
        # MCP subprocess and all four model HTTP clients would otherwise stay
        # open for the process lifetime. __aexit__ awaits this, so we swallow
        # rather than raise (a teardown error must not mask the body's exception).
        async def _safely(coro) -> None:
            try:
                await coro
            except Exception:  # noqa: BLE001 — teardown is best-effort
                pass

        # Stop any in-flight codebase indexing before disconnecting its client.
        if self._codebase_index_task is not None:
            self._codebase_index_task.cancel()
            self._codebase_index_task = None
        # Drain any background indexing before tearing down the embedding client.
        for mom in (self.mom1, self.mom2, self.mom3):
            await _safely(mom.flush_index())
        for client in list(self._mcp_clients):
            await _safely(client.disconnect())
        self._mcp_clients.clear()
        await _safely(self.a1.close())
        await _safely(self.a2.close())
        await _safely(self.a3.close())
        if self.a4 is not None:
            await _safely(self.a4.close())
        if self._embedding is not None:
            await _safely(self._embedding.close())

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

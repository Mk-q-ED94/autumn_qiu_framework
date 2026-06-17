import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable

from ..components.agent import Agent
from ..components.skill import Skill
from ..components.tool import Tool
from ..types import AgentStep, Message, Role, TaskType, WorkflowStage
from .base import WorkspaceBase

# Coordinator hook (A1) invoked after each ReAct step; see Agent.run's supervisor.
Supervisor = Callable[[int, list[AgentStep]], Awaitable["str | None"]]

_DEFAULT_SYSTEM = (
    "You are a precise task executor in the Autumn framework. "
    "Process the given task and produce a structured, accurate response."
)

_TOOL_RESULT_MAX = 120

# Returns a snapshot of (tools, skills) available for this turn.
ToolProvider = Callable[[], tuple[list[Tool], list[Skill]]]

_TASK_HINTS: dict[TaskType, str] = {
    TaskType.CODE: "Focus on correctness, test coverage, and code style.",
    TaskType.SEARCH: "Prefer search and retrieval tools to ground your answer in facts before synthesizing.",
    TaskType.WRITE: "Prioritize clarity, tone, and structure; avoid unnecessary tool use.",
    TaskType.DATA: "Break calculations into verifiable steps; validate intermediate results.",
    TaskType.GENERAL: "",
}


def _step_to_stage(index: int, step: AgentStep) -> WorkflowStage:
    """Render one agent tool call as a trace stage (kind="tool")."""
    args = ", ".join(f"{k}={v}" for k, v in step.arguments.items())
    result = step.result
    if len(result) > _TOOL_RESULT_MAX:
        result = result[:_TOOL_RESULT_MAX] + "…"
    detail = f"{args} → {result}" if args else result
    return WorkflowStage(
        id=f"wp2.tool.{index}.{step.name}",
        title=step.name,
        detail=detail,
        workspace="WP2",
        status="completed",
        kind="tool",
        duration_ms=step.duration_ms,
        prompt_tokens=step.prompt_tokens,
        completion_tokens=step.completion_tokens,
        source_terr=step.source_terr,
    )


def _source_terrs(tools: list[Tool], skills: list[Skill]) -> list[str]:
    names = {
        source
        for callable_obj in [*tools, *skills]
        if (source := getattr(callable_obj, "source_terr", None))
    }
    return sorted(names)


def _agent_to_stage(
    duration_ms: float,
    tools: list[Tool],
    skills: list[Skill],
    step_count: int,
) -> WorkflowStage:
    """Render WP2's agent handoff as a trace stage (kind="agent")."""
    capability_parts: list[str] = []
    if tools:
        capability_parts.append(f"{len(tools)} tools")
    if skills:
        capability_parts.append(f"{len(skills)} skills")
    terr_names = _source_terrs(tools, skills)
    if terr_names:
        capability_parts.append(f"Terr: {', '.join(terr_names)}")
    capabilities = " · ".join(capability_parts) if capability_parts else "no callable capabilities"
    calls = f"{step_count} callable step{'s' if step_count != 1 else ''}"
    return WorkflowStage(
        id="wp2.agent",
        title="WP2 Agent",
        detail=f"Agent 接管任务执行 · {capabilities} · {calls}",
        workspace="WP2",
        status="completed",
        kind="agent",
        duration_ms=duration_ms,
        source_terr=terr_names[0] if len(terr_names) == 1 else None,
    )


def _apply_hint(base_system: str, task_type: TaskType | None) -> str:
    if task_type is None:
        return base_system
    hint = _TASK_HINTS.get(task_type, "")
    return f"{base_system}\n\n{hint}" if hint else base_system


def _apply_turn_context(system: str, turn_context: str) -> str:
    """Append push-activated constraints/reminders after the base system prompt."""
    return f"{system}\n\n---\n\n{turn_context}" if turn_context else system


def _apply_plan_hint(system: str, plan_hint: str | None) -> str:
    """Prepend A1's suggested execution plan when provided."""
    if not plan_hint:
        return system
    return f"{system}\n\n## A1 Suggested Approach\n{plan_hint}"


def _compose_system(
    base: str,
    task_type: TaskType | None,
    turn_context: str,
    plan_hint: str | None,
) -> str:
    """Build the full WP2 system prompt: base + task hint + push context + plan."""
    return _apply_plan_hint(
        _apply_turn_context(_apply_hint(base, task_type), turn_context),
        plan_hint,
    )


class WP2Tas(WorkspaceBase):
    """Task workspace. Executes structured, directly-actionable tasks.

    When tools or skills are registered (via ``Autumn.register_tool`` /
    ``register_skill`` / ``add_mcp``), WP2 runs the task through an
    :class:`Agent` ReAct loop so the executor can call tools and reuse
    skills. With nothing registered it falls back to a single completion,
    preserving the original lightweight behavior and zero added latency.

    ``process_with_trace`` additionally returns one :class:`WorkflowStage`
    per tool call so the pipeline trace can show what the agent actually did.
    """

    def __init__(
        self,
        api,
        memory,
        system_prompt: str | None = None,
        tool_provider: ToolProvider | None = None,
        agent_max_steps: int = 10,
    ):
        super().__init__(api, memory)
        self._system = system_prompt or _DEFAULT_SYSTEM
        self._tool_provider = tool_provider
        self._agent_max_steps = agent_max_steps

    async def process(self, task_input: str, task_type: TaskType | None = None) -> str:
        output, *_ = await self._execute(task_input, task_type)
        return output

    async def process_with_trace(
        self,
        task_input: str,
        task_type: TaskType | None = None,
        turn_context: str = "",
        plan_hint: str | None = None,
        supervisor: Supervisor | None = None,
    ) -> tuple[str, list[WorkflowStage], int | None, int | None]:
        """Execute the task and return (output, tool_stages, prompt_tokens, completion_tokens).

        The token totals sum every A2 LLM call made during this turn — the agent
        loop (or single plain completion) plus the checker validation pass — so
        WP1 can attribute the full cost to its ``wp2.task`` stage.

        ``turn_context``: push-activated constraints/reminders fragment (from 4D memory
        push engine). When non-empty it is appended to the system prompt for this turn
        only, so active CONSTRAIN/REMIND memories gate A2 behaviour without altering the
        base configuration.

        ``plan_hint``: structured execution plan generated by A1 (the 0.3.0 coordinator).
        When set it is injected into A2's system prompt so the executor knows the
        intended approach before starting.

        ``supervisor``: optional A1 hook invoked after each ReAct step so the
        coordinator can watch and steer A2 mid-execution. Only used on the agent
        (tool-bearing) path.
        """
        return await self._execute(
            task_input, task_type, turn_context=turn_context,
            plan_hint=plan_hint, supervisor=supervisor,
        )

    async def _execute(
        self,
        task_input: str,
        task_type: TaskType | None = None,
        turn_context: str = "",
        plan_hint: str | None = None,
        supervisor: Supervisor | None = None,
    ) -> tuple[str, list[WorkflowStage], int | None, int | None]:
        tools, skills = self._tool_provider() if self._tool_provider else ([], [])
        tool_stages: list[WorkflowStage] = []
        prompt_total = 0
        completion_total = 0
        any_usage = False

        if tools or skills:
            steps: list[AgentStep] = []
            agent_started = time.perf_counter()
            result, agent_prompt, agent_completion = await self._run_with_agent(
                task_input, tools, skills, steps, task_type, turn_context=turn_context,
                plan_hint=plan_hint, supervisor=supervisor,
            )
            agent_stage = _agent_to_stage(
                round((time.perf_counter() - agent_started) * 1000, 1),
                tools,
                skills,
                len(steps),
            )
            tool_stages = [agent_stage, *[_step_to_stage(i, s) for i, s in enumerate(steps)]]
            if agent_prompt or agent_completion:
                prompt_total += agent_prompt
                completion_total += agent_completion
                any_usage = True
        else:
            result = await self._run_plain(task_input, task_type, turn_context=turn_context, plan_hint=plan_hint)
            usage = getattr(self.api, "last_usage", None)
            if usage:
                prompt_total += usage.get("prompt_tokens") or 0
                completion_total += usage.get("completion_tokens") or 0
                any_usage = True

        if self.checker:
            _, result = await self.checker.validate(result, self.memory)
            # Checker calls api.complete() once per validation pass; sum those into
            # the WP2 total since they're part of WP2's accountable cost.
            usage = getattr(self.api, "last_usage", None)
            if usage:
                prompt_total += usage.get("prompt_tokens") or 0
                completion_total += usage.get("completion_tokens") or 0
                any_usage = True

        await self.memory.append_history({
            "ts": time.time(),
            "task": task_input,
            "output": result,
        })
        if not any_usage:
            return result, tool_stages, None, None
        return result, tool_stages, prompt_total, completion_total

    async def _run_plain(
        self,
        task_input: str,
        task_type: TaskType | None = None,
        turn_context: str = "",
        plan_hint: str | None = None,
    ) -> str:
        """Single completion — the original WP2 behavior, used when no tools exist."""
        system = _compose_system(self._system, task_type, turn_context, plan_hint)
        messages = [
            Message(role=Role.SYSTEM, content=system),
            Message(role=Role.USER, content=task_input),
        ]
        return await self.api.complete(messages)

    async def _run_with_agent(
        self,
        task_input: str,
        tools: list[Tool],
        skills: list[Skill],
        steps: list[AgentStep] | None = None,
        task_type: TaskType | None = None,
        turn_context: str = "",
        plan_hint: str | None = None,
        supervisor: Supervisor | None = None,
    ) -> tuple[str, int, int]:
        """ReAct loop with tool access; carries WP2's persona + Mom2 history.

        Returns ``(result, prompt_tokens, completion_tokens)`` where the token
        totals are the agent loop's aggregate (0 when the provider doesn't return
        usage stats).
        """
        instructions = _compose_system(self._system, task_type, turn_context, plan_hint)
        agent = Agent(
            name="WP2-Tas",
            api=self.api,
            tools=tools,
            skills=skills,
            instructions=instructions,
            max_steps=self._agent_max_steps,
        )
        result = await agent.run(
            task_input, memory=self.memory, steps=steps, supervisor=supervisor,
        )
        return result, agent.total_prompt_tokens, agent.total_completion_tokens

    async def stream(
        self,
        task_input: str,
        task_type: TaskType | None = None,
        chunk_size: int = 64,
    ) -> AsyncIterator[str]:
        async for event in self.stream_with_trace(task_input, task_type, chunk_size):
            if isinstance(event, str):
                yield event

    async def stream_with_trace(
        self,
        task_input: str,
        task_type: TaskType | None = None,
        chunk_size: int = 64,
        turn_context: str = "",
        plan_hint: str | None = None,
        supervisor: Supervisor | None = None,
    ) -> AsyncIterator[str | list[WorkflowStage]]:
        """Token-level streaming. Bypasses the checker — caller is responsible
        for post-hoc validation.

        When tools or skills are registered, the agent loop needs whole
        responses to dispatch tool calls; in that case we fall back to a
        buffered run and chunk the result. Either way, mom2 history is
        persisted even if the stream is interrupted mid-flight.
        """
        tools, skills = self._tool_provider() if self._tool_provider else ([], [])

        if tools or skills:
            # Tool-driven turn cannot be true-streamed; buffer then chunk.
            steps: list[AgentStep] = []
            result = ""
            agent_stage: WorkflowStage | None = None
            try:
                agent_started = time.perf_counter()
                result, _, _ = await self._run_with_agent(
                    task_input, tools, skills, steps, task_type, turn_context=turn_context,
                    plan_hint=plan_hint, supervisor=supervisor,
                )
                agent_stage = _agent_to_stage(
                    round((time.perf_counter() - agent_started) * 1000, 1),
                    tools,
                    skills,
                    len(steps),
                )
                for i in range(0, len(result), chunk_size):
                    yield result[i:i + chunk_size]
                    await asyncio.sleep(0)
            finally:
                await self.memory.append_history({
                    "ts": time.time(),
                    "task": task_input,
                    "output": result,
                })
            stages = [_step_to_stage(i, s) for i, s in enumerate(steps)]
            if agent_stage is not None:
                stages.insert(0, agent_stage)
            yield stages
            return

        system = _compose_system(self._system, task_type, turn_context, plan_hint)
        messages = [
            Message(role=Role.SYSTEM, content=system),
            Message(role=Role.USER, content=task_input),
        ]
        buf: list[str] = []
        try:
            async for tok in self.api.stream_complete(messages):
                buf.append(tok)
                yield tok
        finally:
            await self.memory.append_history({
                "ts": time.time(),
                "task": task_input,
                "output": "".join(buf),
            })
        yield []

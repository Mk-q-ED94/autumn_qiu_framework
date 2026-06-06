import asyncio
import time
from typing import AsyncIterator, Callable

from .base import WorkspaceBase
from ..types import Message, Role, TaskType, WorkflowStage, AgentStep
from ..components.agent import Agent
from ..components.skill import Skill
from ..components.tool import Tool

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
    )


def _apply_hint(base_system: str, task_type: TaskType | None) -> str:
    if task_type is None:
        return base_system
    hint = _TASK_HINTS.get(task_type, "")
    return f"{base_system}\n\n{hint}" if hint else base_system


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
    ):
        super().__init__(api, memory)
        self._system = system_prompt or _DEFAULT_SYSTEM
        self._tool_provider = tool_provider

    async def process(self, task_input: str, task_type: TaskType | None = None) -> str:
        output, _ = await self._execute(task_input, task_type)
        return output

    async def process_with_trace(
        self,
        task_input: str,
        task_type: TaskType | None = None,
    ) -> tuple[str, list[WorkflowStage]]:
        """Execute the task and return (output, tool_stages)."""
        return await self._execute(task_input, task_type)

    async def _execute(
        self,
        task_input: str,
        task_type: TaskType | None = None,
    ) -> tuple[str, list[WorkflowStage]]:
        tools, skills = self._tool_provider() if self._tool_provider else ([], [])
        tool_stages: list[WorkflowStage] = []

        if tools or skills:
            steps: list[AgentStep] = []
            result = await self._run_with_agent(task_input, tools, skills, steps, task_type)
            tool_stages = [_step_to_stage(i, s) for i, s in enumerate(steps)]
        else:
            result = await self._run_plain(task_input, task_type)

        if self.checker:
            _, result = await self.checker.validate(result, self.memory)

        await self.memory.append_history({
            "ts": time.time(),
            "task": task_input,
            "output": result,
        })
        return result, tool_stages

    async def _run_plain(self, task_input: str, task_type: TaskType | None = None) -> str:
        """Single completion — the original WP2 behavior, used when no tools exist."""
        messages = [
            Message(role=Role.SYSTEM, content=_apply_hint(self._system, task_type)),
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
    ) -> str:
        """ReAct loop with tool access; carries WP2's persona + Mom2 history."""
        agent = Agent(
            name="WP2-Tas",
            api=self.api,
            tools=tools,
            skills=skills,
            instructions=_apply_hint(self._system, task_type),
        )
        return await agent.run(task_input, memory=self.memory, steps=steps)

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
    ) -> AsyncIterator[str | list[WorkflowStage]]:
        """Token-level streaming. Bypasses the checker — caller is responsible
        for post-hoc validation.

        When tools or skills are registered, the agent loop needs whole
        responses to dispatch tool calls; in that case we fall back to a
        buffered run and chunk the result. Either way, mom2 history is
        persisted after the stream completes.
        """
        tools, skills = self._tool_provider() if self._tool_provider else ([], [])

        if tools or skills:
            # Tool-driven turn cannot be true-streamed; buffer then chunk.
            steps: list[AgentStep] = []
            result = await self._run_with_agent(task_input, tools, skills, steps, task_type)
            for i in range(0, len(result), chunk_size):
                yield result[i:i + chunk_size]
                await asyncio.sleep(0)
            await self.memory.append_history({
                "ts": time.time(),
                "task": task_input,
                "output": result,
            })
            yield [_step_to_stage(i, s) for i, s in enumerate(steps)]
            return

        messages = [
            Message(role=Role.SYSTEM, content=_apply_hint(self._system, task_type)),
            Message(role=Role.USER, content=task_input),
        ]
        buf: list[str] = []
        async for tok in self.api.stream_complete(messages):
            buf.append(tok)
            yield tok
        full = "".join(buf)
        await self.memory.append_history({
            "ts": time.time(),
            "task": task_input,
            "output": full,
        })
        yield []

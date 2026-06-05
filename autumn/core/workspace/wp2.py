import time
from typing import Callable

from .base import WorkspaceBase
from ..types import Message, Role
from ..components.agent import Agent
from ..components.skill import Skill
from ..components.tool import Tool

_DEFAULT_SYSTEM = (
    "You are a precise task executor in the Autumn framework. "
    "Process the given task and produce a structured, accurate response."
)

# Returns a snapshot of (tools, skills) available for this turn.
ToolProvider = Callable[[], tuple[list[Tool], list[Skill]]]


class WP2Tas(WorkspaceBase):
    """Task workspace. Executes structured, directly-actionable tasks.

    When tools or skills are registered (via ``Autumn.register_tool`` /
    ``register_skill`` / ``add_mcp``), WP2 runs the task through an
    :class:`Agent` ReAct loop so the executor can call tools and reuse
    skills. With nothing registered it falls back to a single completion,
    preserving the original lightweight behavior and zero added latency.

    The tool set is resolved per-call via ``tool_provider`` so tools attached
    at runtime (e.g. ``await autumn.add_mcp(...)``) take effect immediately.
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

    async def process(self, task_input: str) -> str:
        tools, skills = self._tool_provider() if self._tool_provider else ([], [])

        if tools or skills:
            result = await self._run_with_agent(task_input, tools, skills)
        else:
            result = await self._run_plain(task_input)

        if self.checker:
            _, result = await self.checker.validate(result, self.memory)

        await self.memory.append_history({
            "ts": time.time(),
            "task": task_input,
            "output": result,
        })
        return result

    async def _run_plain(self, task_input: str) -> str:
        """Single completion — the original WP2 behavior, used when no tools exist."""
        messages = [
            Message(role=Role.SYSTEM, content=self._system),
            Message(role=Role.USER, content=task_input),
        ]
        return await self.api.complete(messages)

    async def _run_with_agent(
        self,
        task_input: str,
        tools: list[Tool],
        skills: list[Skill],
    ) -> str:
        """ReAct loop with tool access; carries WP2's persona + Mom2 history."""
        agent = Agent(
            name="WP2-Tas",
            api=self.api,
            tools=tools,
            skills=skills,
            instructions=self._system,
        )
        return await agent.run(task_input, memory=self.memory)

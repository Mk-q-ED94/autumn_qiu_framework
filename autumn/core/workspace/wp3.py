import time
from collections.abc import AsyncIterator, Callable

from ..components.agent import Agent
from ..components.skill import Skill
from ..types import AgentStep, Message, MissionRoute, Role, WorkflowStage
from .base import WorkspaceBase

_DEFAULT_DIRECT = (
    "You are a helpful assistant in the Autumn framework. "
    "Respond naturally and helpfully to the user's message."
)

_DEFAULT_CONVERT = (
    "Convert the following mission into a precise, structured task. "
    "Output a markdown document with a clear description and a todo list "
    "of directly executable steps. Be specific and unambiguous."
)

_TOOL_RESULT_MAX = 120

# Returns the curated set of skills A3 may call on the direct path this turn.
SkillProvider = Callable[[], list[Skill]]


def _step_to_stage(index: int, step: AgentStep) -> WorkflowStage:
    """Render one A3 skill call as a trace stage (kind="tool", WP3-scoped)."""
    args = ", ".join(f"{k}={v}" for k, v in step.arguments.items())
    result = step.result
    if len(result) > _TOOL_RESULT_MAX:
        result = result[:_TOOL_RESULT_MAX] + "…"
    detail = f"{args} → {result}" if args else result
    return WorkflowStage(
        id=f"wp3.tool.{index}.{step.name}",
        title=step.name,
        detail=detail,
        workspace="WP3",
        status="completed",
        kind="tool",
        duration_ms=step.duration_ms,
        prompt_tokens=step.prompt_tokens,
        completion_tokens=step.completion_tokens,
        source_terr=step.source_terr,
    )


class WP3Mis(WorkspaceBase):
    """Mission workspace — the general executor (A3).

    Exposes two operations (routing decision lives in WP1):
    - answer_directly: A3 responds naturally. When a curated *lite* skill set is
      provided (0.3.0), A3 may call those skills in a short, bounded loop before
      answering — e.g. ``recall`` to ground the reply — without becoming a heavy
      ReAct executor like WP2.
    - convert_to_task: A3 reformats the mission as a structured task for WP2.
    """

    def __init__(
        self,
        api,
        memory,
        direct_prompt: str | None = None,
        convert_prompt: str | None = None,
        skill_provider: SkillProvider | None = None,
        lite_max_steps: int = 4,
    ):
        super().__init__(api, memory)
        self._direct_system = direct_prompt or _DEFAULT_DIRECT
        self._convert_system = convert_prompt or _DEFAULT_CONVERT
        self._skill_provider = skill_provider
        self._lite_max_steps = lite_max_steps

    def _lite_skills(self) -> list[Skill]:
        return self._skill_provider() if self._skill_provider else []

    def _with_turn_context(self, base: str, turn_context: str) -> str:
        return f"{base}\n\n---\n\n{turn_context}" if turn_context else base

    async def answer_directly(self, mission_input: str, turn_context: str = "") -> str:
        result, *_ = await self.answer_directly_with_trace(mission_input, turn_context)
        return result

    async def answer_directly_with_trace(
        self,
        mission_input: str,
        turn_context: str = "",
    ) -> tuple[str, list[WorkflowStage], int | None, int | None]:
        """Direct answer + (tool_stages, prompt_tokens, completion_tokens).

        With no lite skills configured this is a single ``complete()`` — the
        original A3 behavior. With skills, A3 runs a short bounded agent loop so
        it can ground the reply (recall, time, etc.) before answering.
        """
        skills = self._lite_skills()
        tool_stages: list[WorkflowStage] = []
        if skills:
            steps: list[AgentStep] = []
            agent = Agent(
                name="WP3-Mis",
                api=self.api,
                skills=skills,
                instructions=self._with_turn_context(self._direct_system, turn_context),
                max_steps=self._lite_max_steps,
            )
            result = await agent.run(mission_input, memory=self.memory, steps=steps)
            tool_stages = [_step_to_stage(i, s) for i, s in enumerate(steps)]
            prompt_tokens = agent.total_prompt_tokens or None
            completion_tokens = agent.total_completion_tokens or None
        else:
            messages = [
                Message(role=Role.SYSTEM, content=self._with_turn_context(self._direct_system, turn_context)),
                Message(role=Role.USER, content=mission_input),
            ]
            result = await self.api.complete(messages)
            usage = getattr(self.api, "last_usage", None) or {}
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")

        await self.memory.append_history({
            "ts": time.time(),
            "mission": mission_input,
            "route": MissionRoute.DIRECT.value,
            "output": result,
        })
        return result, tool_stages, prompt_tokens, completion_tokens

    async def convert_to_task(self, mission_input: str, turn_context: str = "") -> str:
        messages = [
            Message(role=Role.SYSTEM, content=self._with_turn_context(self._convert_system, turn_context)),
            Message(role=Role.USER, content=mission_input),
        ]
        result = await self.api.complete(messages)
        await self.memory.append_history({
            "ts": time.time(),
            "mission": mission_input,
            "route": MissionRoute.CONVERT.value,
            "output": result,
        })
        # Hand off to the shared zone so WP2 can pick up context if needed.
        await self.memory.shared.set("handoff", {
            "original_mission": mission_input,
            "converted_task": result,
            "ts": time.time(),
        })
        return result

    async def process(self, mission_input: str) -> str:
        """Interface compliance. Actual routing is handled by WP1."""
        return await self.answer_directly(mission_input)

    async def stream_direct(
        self, mission_input: str, turn_context: str = "",
    ) -> AsyncIterator[str | list[WorkflowStage]]:
        """Token-level streaming for the direct path. Bypasses the checker —
        caller handles post-hoc validation. Mom3 history is written even if the
        stream is interrupted mid-flight, so a partial answer is recoverable.

        When lite skills are configured the turn may call them, which cannot be
        true-streamed; it falls back to a buffered run, chunks the result, and
        yields a final list of tool stages (mirroring WP2's streaming fallback).
        """
        skills = self._lite_skills()
        if skills:
            steps: list[AgentStep] = []
            result = ""
            try:
                agent = Agent(
                    name="WP3-Mis",
                    api=self.api,
                    skills=skills,
                    instructions=self._with_turn_context(self._direct_system, turn_context),
                    max_steps=self._lite_max_steps,
                )
                result = await agent.run(mission_input, memory=self.memory, steps=steps)
                for i in range(0, len(result), 48):
                    yield result[i:i + 48]
            finally:
                await self.memory.append_history({
                    "ts": time.time(),
                    "mission": mission_input,
                    "route": MissionRoute.DIRECT.value,
                    "output": result,
                })
            yield [_step_to_stage(i, s) for i, s in enumerate(steps)]
            return

        messages = [
            Message(role=Role.SYSTEM, content=self._with_turn_context(self._direct_system, turn_context)),
            Message(role=Role.USER, content=mission_input),
        ]
        buf: list[str] = []
        try:
            async for tok in self.api.stream_complete(messages):
                buf.append(tok)
                yield tok
        finally:
            await self.memory.append_history({
                "ts": time.time(),
                "mission": mission_input,
                "route": MissionRoute.DIRECT.value,
                "output": "".join(buf),
            })
        yield []

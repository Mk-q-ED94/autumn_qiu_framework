import time
from typing import AsyncIterator
from .base import WorkspaceBase
from ..types import Message, MissionRoute, Role

_DEFAULT_DIRECT = (
    "You are a helpful assistant in the Autumn framework. "
    "Respond naturally and helpfully to the user's message."
)

_DEFAULT_CONVERT = (
    "Convert the following mission into a precise, structured task. "
    "Output a markdown document with a clear description and a todo list "
    "of directly executable steps. Be specific and unambiguous."
)


class WP3Mis(WorkspaceBase):
    """Mission workspace.

    Exposes two operations (routing decision lives in WP1):
    - answer_directly: A3 responds naturally.
    - convert_to_task: A3 reformats the mission as a structured task for WP2.
    """

    def __init__(
        self,
        api,
        memory,
        direct_prompt: str | None = None,
        convert_prompt: str | None = None,
    ):
        super().__init__(api, memory)
        self._direct_system = direct_prompt or _DEFAULT_DIRECT
        self._convert_system = convert_prompt or _DEFAULT_CONVERT

    async def answer_directly(self, mission_input: str) -> str:
        messages = [
            Message(role=Role.SYSTEM, content=self._direct_system),
            Message(role=Role.USER, content=mission_input),
        ]
        result = await self.api.complete(messages)
        await self.memory.append_history({
            "ts": time.time(),
            "mission": mission_input,
            "route": MissionRoute.DIRECT.value,
            "output": result,
        })
        return result

    async def convert_to_task(self, mission_input: str) -> str:
        messages = [
            Message(role=Role.SYSTEM, content=self._convert_system),
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

    async def stream_direct(self, mission_input: str) -> AsyncIterator[str]:
        """Token-level streaming for the direct path. Bypasses the checker —
        caller handles post-hoc validation. Mom3 history is written when the
        stream completes."""
        messages = [
            Message(role=Role.SYSTEM, content=self._direct_system),
            Message(role=Role.USER, content=mission_input),
        ]
        buf: list[str] = []
        async for tok in self.api.stream_complete(messages):
            buf.append(tok)
            yield tok
        full = "".join(buf)
        await self.memory.append_history({
            "ts": time.time(),
            "mission": mission_input,
            "route": MissionRoute.DIRECT.value,
            "output": full,
        })

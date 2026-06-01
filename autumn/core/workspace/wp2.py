from .base import WorkspaceBase
from ..types import Message, Role

_DEFAULT_SYSTEM = (
    "You are a precise task executor in the Autumn framework. "
    "Process the given task and produce a structured, accurate response."
)


class WP2Tas(WorkspaceBase):
    """Task workspace. Executes structured, directly-actionable tasks."""

    def __init__(self, api, memory, system_prompt: str | None = None):
        super().__init__(api, memory)
        self._system = system_prompt or _DEFAULT_SYSTEM

    async def process(self, task_input: str) -> str:
        messages = [
            Message(role=Role.SYSTEM, content=self._system),
            Message(role=Role.USER, content=task_input),
        ]
        result = await self.api.complete(messages)

        if self.checker:
            _, result = await self.checker.validate(result, self.memory)

        return result

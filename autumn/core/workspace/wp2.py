from .base import WorkspaceBase
from ..types import Message, Role


class WP2Tas(WorkspaceBase):
    """Task workspace. Processes structured, directly executable tasks."""

    async def process(self, task_input: str) -> str:
        messages = [
            Message(
                role=Role.SYSTEM,
                content=(
                    "You are a precise task executor in the Autumn framework. "
                    "Process the given task and produce a structured, accurate response."
                ),
            ),
            Message(role=Role.USER, content=task_input),
        ]
        result = await self.api.complete(messages)

        if self.checker:
            _, result = await self.checker.validate(result, self.memory)

        return result

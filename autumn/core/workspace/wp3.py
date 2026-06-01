from .base import WorkspaceBase
from ..types import Message, Role


class WP3Mis(WorkspaceBase):
    """Mission workspace. Provides two operations for WP1 to invoke:
    - answer_directly: A3 responds naturally (no conversion)
    - convert_to_task: A3 formats the mission as a structured task for WP2
    Routing decision lives in WP1, not here.
    """

    async def answer_directly(self, mission_input: str) -> str:
        messages = [
            Message(
                role=Role.SYSTEM,
                content=(
                    "You are a helpful assistant in the Autumn framework. "
                    "Respond naturally and helpfully to the user's message."
                ),
            ),
            Message(role=Role.USER, content=mission_input),
        ]
        return await self.api.complete(messages)

    async def convert_to_task(self, mission_input: str) -> str:
        messages = [
            Message(
                role=Role.SYSTEM,
                content=(
                    "Convert the following mission into a precise, structured task. "
                    "Output a markdown document with a clear description and a todo list "
                    "of directly executable steps. Be specific and unambiguous."
                ),
            ),
            Message(role=Role.USER, content=mission_input),
        ]
        return await self.api.complete(messages)

    async def process(self, mission_input: str) -> str:
        """Interface compliance. Actual routing is handled by WP1."""
        return await self.answer_directly(mission_input)

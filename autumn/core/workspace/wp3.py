from .base import WorkspaceBase
from ..types import Message, MissionRoute, Role


class WP3Mis(WorkspaceBase):
    """Mission workspace. Handles natural conversation; optionally converts missions to tasks for WP2."""

    def __init__(self, api, memory, wp2=None):
        super().__init__(api, memory)
        self.wp2 = wp2

    async def process(self, mission_input: str) -> str:
        route = await self._decide_route(mission_input)

        if route == MissionRoute.DIRECT:
            result = await self._answer_directly(mission_input)
        else:
            task_form = await self._convert_to_task(mission_input)
            result = await self.wp2.process(task_form)

        if self.checker:
            _, result = await self.checker.validate(result, self.memory)

        return result

    async def _decide_route(self, mission_input: str) -> MissionRoute:
        # TODO: routing decision mechanism (direct vs convert-to-task) — to be confirmed
        return MissionRoute.DIRECT

    async def _answer_directly(self, mission_input: str) -> str:
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

    async def _convert_to_task(self, mission_input: str) -> str:
        messages = [
            Message(
                role=Role.SYSTEM,
                content=(
                    "Convert the following mission into a precise, structured task description. "
                    "Output a markdown todo list with clear, directly executable steps."
                ),
            ),
            Message(role=Role.USER, content=mission_input),
        ]
        return await self.api.complete(messages)

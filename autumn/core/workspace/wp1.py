from .base import WorkspaceBase
from .wp2 import WP2Tas
from .wp3 import WP3Mis
from ..types import InputType, MissionRoute
from ..components.selector import Selector
from ..interaction import UserInteraction


class WP1Tot(WorkspaceBase):
    """Total workspace. Orchestrates the full processing pipeline.

    Responsibilities:
    - Run Selector to classify input (task / mission)
    - Optionally confirm classification with user
    - For mission: ask user for route (direct / convert)
    - Apply WP1.checker as the final gate before output reaches the user
    """

    def __init__(self, api, memory, wp2: WP2Tas, wp3: WP3Mis, interaction: UserInteraction | None = None):
        super().__init__(api, memory)
        self.wp2 = wp2
        self.wp3 = wp3
        self.selector = Selector(api)
        self.interaction = interaction

    async def process(self, user_input: str) -> str:
        input_type = await self.selector.classify(user_input)

        if self.interaction:
            confirmed = await self.interaction.ask(
                f"Input classified as [{input_type.value.upper()}]. Confirm or correct?",
                [t.value for t in InputType],
            )
            input_type = InputType(confirmed)

        if input_type == InputType.TASK:
            return await self._route_task(user_input)
        else:
            return await self._route_mission(user_input)

    async def _route_task(self, task_input: str) -> str:
        """task → WP2(A2) → WP2.checker → WP1.checker → user"""
        result = await self.wp2.process(task_input)  # WP2.checker runs inside WP2
        return await self._wp1_check(result)

    async def _route_mission(self, mission_input: str) -> str:
        route = MissionRoute.DIRECT
        if self.interaction:
            chosen = await self.interaction.ask(
                "How should I handle this mission?",
                [r.value for r in MissionRoute],
            )
            route = MissionRoute(chosen)

        if route == MissionRoute.DIRECT:
            # mission(direct) → WP3(A3) → WP1.checker → user
            result = await self.wp3.answer_directly(mission_input)
            return await self._wp1_check(result)

        # mission(convert) → WP3(A3 converts) → WP3.checker → WP1.checker → WP2 flow
        task_form = await self.wp3.convert_to_task(mission_input)

        if self.wp3.checker:
            _, task_form = await self.wp3.checker.validate(task_form, self.wp3.memory)

        if self.checker:
            _, task_form = await self.checker.validate(task_form, self.memory)

        # Reuse _route_task: WP2(A2) → WP2.checker → WP1.checker → user
        return await self._route_task(task_form)

    async def _wp1_check(self, output: str) -> str:
        if self.checker:
            _, output = await self.checker.validate(output, self.memory)
        return output

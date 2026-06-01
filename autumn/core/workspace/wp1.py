import json
from typing import Literal
from .base import WorkspaceBase
from .wp2 import WP2Tas
from .wp3 import WP3Mis
from ..types import InputType, MissionRoute, Message, Role
from ..components.selector import Selector
from ..interaction import UserInteraction

_AUTO_ROUTE_SYSTEM = """\
You are a routing agent in the Autumn framework.
Decide how the following mission should be handled:
- "direct": answer conversationally (questions, discussions, simple responses, creative requests)
- "convert": convert into a structured task for step-by-step execution \
(multi-step work, concrete actions, anything that benefits from a todo list)

Respond with ONLY valid JSON: {"route": "direct"} or {"route": "convert"}"""


class WP1Tot(WorkspaceBase):
    """Total workspace. Orchestrates the full processing pipeline.

    Task path:          WP2(A2) → WP2.checker → WP1.checker → user
    Mission/direct:     WP3(A3) → WP1.checker → user
    Mission/convert:    WP3(A3 converts) → WP3.checker → WP1.checker
                        → WP2(A2) → WP2.checker → WP1.checker → user
    """

    def __init__(
        self,
        api,
        memory,
        wp2: WP2Tas,
        wp3: WP3Mis,
        interaction: UserInteraction | None = None,
        selector_prompt: str | None = None,
        headless_mission_route: MissionRoute | Literal["auto"] = "auto",
    ):
        super().__init__(api, memory)
        self.wp2 = wp2
        self.wp3 = wp3
        self.selector = Selector(api, system_prompt=selector_prompt)
        self.interaction = interaction
        self._headless_route = headless_mission_route

    async def process(self, user_input: str) -> str:
        input_type = await self.selector.classify_and_maybe_confirm(user_input, self.interaction)

        if input_type == InputType.TASK:
            return await self._route_task(user_input)
        return await self._route_mission(user_input)

    async def _route_task(self, task_input: str) -> str:
        result = await self.wp2.process(task_input)
        return await self._wp1_check(result)

    async def _route_mission(self, mission_input: str) -> str:
        if self.interaction:
            chosen = await self.interaction.ask(
                "How should I handle this mission?",
                [r.value for r in MissionRoute],
            )
            route = MissionRoute(chosen)
        else:
            route = await self._resolve_headless_route(mission_input)

        if route == MissionRoute.DIRECT:
            result = await self.wp3.answer_directly(mission_input)
            return await self._wp1_check(result)

        # Convert path
        task_form = await self.wp3.convert_to_task(mission_input)
        if self.wp3.checker:
            _, task_form = await self.wp3.checker.validate(task_form, self.wp3.memory)
        if self.checker:
            _, task_form = await self.checker.validate(task_form, self.memory)
        return await self._route_task(task_form)

    async def _resolve_headless_route(self, mission_input: str) -> MissionRoute:
        if self._headless_route != "auto":
            return self._headless_route
        return await self._auto_decide_route(mission_input)

    async def _auto_decide_route(self, mission_input: str) -> MissionRoute:
        """A3 autonomously decides whether to answer directly or convert to a task."""
        messages = [
            Message(role=Role.SYSTEM, content=_AUTO_ROUTE_SYSTEM),
            Message(role=Role.USER, content=mission_input),
        ]
        try:
            response = await self.wp3.api.complete(messages, max_tokens=32)
            data = json.loads(response.strip())
            return MissionRoute(data["route"])
        except (json.JSONDecodeError, KeyError, ValueError):
            return MissionRoute.DIRECT

    async def _wp1_check(self, output: str) -> str:
        if self.checker:
            _, output = await self.checker.validate(output, self.memory)
        return output

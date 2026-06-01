from .base import WorkspaceBase
from .wp2 import WP2Tas
from .wp3 import WP3Mis
from ..types import InputType
from ..components.selector import Selector


class WP1Tot(WorkspaceBase):
    """Total workspace. Contains WP2 and WP3. Routes user input via Selector."""

    def __init__(self, api, memory, wp2: WP2Tas, wp3: WP3Mis):
        super().__init__(api, memory)
        self.wp2 = wp2
        self.wp3 = wp3
        self.selector = Selector(api)

    async def process(self, user_input: str) -> str:
        input_type = await self.selector.classify(user_input)

        if input_type == InputType.TASK:
            result = await self.wp2.process(user_input)
        else:
            result = await self.wp3.process(user_input)

        if self.checker:
            _, result = await self.checker.validate(result, self.memory)

        return result

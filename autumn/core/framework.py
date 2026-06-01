from .config import AutumnConfig
from .interaction import UserInteraction
from .api.interfaces import A1, A2, A3
from .memory.backends import DictBackend
from .memory.shared import SharedZone
from .memory.mom1 import Mom1
from .memory.mom2 import Mom2
from .memory.mom3 import Mom3
from .workspace.wp1 import WP1Tot
from .workspace.wp2 import WP2Tas
from .workspace.wp3 import WP3Mis
from .components.checker import Checker
from ..plugins.loader import PluginLoader


class Autumn:
    """秋/Autumn — Multi-Model Collaborative Workflow Framework.

    Usage:
        async with Autumn(config) as autumn:
            result = await autumn.process(user_input)

        # With user interaction (CLI confirmation prompts):
        from autumn.core.interaction import CLIInteraction
        async with Autumn(config, interaction=CLIInteraction()) as autumn:
            result = await autumn.process(user_input)
    """

    def __init__(self, config: AutumnConfig, interaction: UserInteraction | None = None):
        self.config = config
        self.plugins = PluginLoader()
        self._build(config, interaction)

    def _build(self, config: AutumnConfig, interaction: UserInteraction | None) -> None:
        self.a1 = A1(config.a1)
        self.a2 = A2(config.a2)
        self.a3 = A3(config.a3)

        shared = SharedZone(DictBackend())
        self.mom2 = Mom2(DictBackend(), shared)
        self.mom3 = Mom3(DictBackend(), shared)
        self.mom1 = Mom1(DictBackend(), self.mom2, self.mom3)

        self.wp2 = WP2Tas(self.a2, self.mom2)
        self.wp3 = WP3Mis(self.a3, self.mom3)
        self.wp1 = WP1Tot(self.a1, self.mom1, self.wp2, self.wp3, interaction=interaction)

        self.wp1.checker = Checker("wp1", self.a1)
        self.wp2.checker = Checker("wp2", self.a2)
        self.wp3.checker = Checker("wp3", self.a3)

    async def process(self, user_input: str) -> str:
        return await self.wp1.process(user_input)

    async def close(self) -> None:
        await self.a1.close()
        await self.a2.close()
        await self.a3.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

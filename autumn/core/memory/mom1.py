from typing import Any
from .base import MemoryArea, MemoryBackend
from .mom2 import Mom2
from .mom3 import Mom3


class Mom1(MemoryArea):
    """Total workspace memory (WP1).

    Access: full read over Mom1, Mom2, and Mom3.
    Mom2 and Mom3 cannot read Mom1.
    """

    def __init__(self, backend: MemoryBackend, mom2: Mom2, mom3: Mom3, history_limit: int = 50):
        super().__init__("mom1", backend, history_limit=history_limit)
        self.mom2 = mom2
        self.mom3 = mom3

    async def read_mom2(self, key: str) -> Any:
        return await self.mom2.get(key)

    async def read_mom3(self, key: str) -> Any:
        return await self.mom3.get(key)

    async def snapshot(self) -> dict[str, list[str]]:
        """Returns all keys across Mom1, Mom2, and Mom3."""
        return {
            "mom1": await self.keys(),
            "mom2": await self.mom2.keys(),
            "mom3": await self.mom3.keys(),
        }

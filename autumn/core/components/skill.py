import asyncio
from typing import Any, Callable


class Skill:
    """A named, reusable capability. Higher-level than a Tool; may compose multiple tools."""

    def __init__(self, name: str, description: str, handler: Callable):
        self.name = name
        self.description = description
        self.handler = handler

    async def execute(self, context: dict[str, Any]) -> Any:
        if asyncio.iscoroutinefunction(self.handler):
            return await self.handler(context)
        return self.handler(context)

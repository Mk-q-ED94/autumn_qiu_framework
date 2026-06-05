import asyncio
from typing import Any, Callable

from .tool import ToolParameter, build_openai_schema, build_anthropic_schema


class Skill:
    """A named, reusable capability. Higher-level than a Tool; may compose multiple tools.

    Like a Tool, a Skill is exposed to the model as a callable function, so an
    Agent can invoke it by name during its ReAct loop. Declare ``parameters``
    to tell the model what arguments to pass; the handler receives them as a
    single context dict (whereas a Tool's fn receives them as **kwargs).
    """

    def __init__(
        self,
        name: str,
        description: str,
        handler: Callable,
        parameters: list[ToolParameter] | None = None,
    ):
        self.name = name
        self.description = description
        self.handler = handler
        self.parameters = parameters or []

    async def execute(self, context: dict[str, Any]) -> Any:
        if asyncio.iscoroutinefunction(self.handler):
            return await self.handler(context)
        return self.handler(context)

    def to_openai_schema(self) -> dict:
        return build_openai_schema(self.name, self.description, self.parameters)

    def to_anthropic_schema(self) -> dict:
        return build_anthropic_schema(self.name, self.description, self.parameters)

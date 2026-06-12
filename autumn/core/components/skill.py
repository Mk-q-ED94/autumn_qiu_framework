import asyncio
from collections.abc import Callable
from typing import Any

from .tool import ToolParameter, build_anthropic_schema, build_openai_schema


class Skill:
    """A named, reusable capability — a higher-level operation that may compose
    multiple tools or steps internally.

    Both Tool and Skill are exposed to the model as callable functions; the
    distinction is organizational, not protocol-level. A Skill is the right
    abstraction when the operation is a workflow ("draft_release_notes",
    "review_pull_request") rather than a single primitive call ("read_file").

    The handler receives the model's arguments as keyword arguments, matching
    the convention used by :class:`Tool.fn`. Declare ``parameters`` to tell
    the model what arguments to pass.
    """

    def __init__(
        self,
        name: str,
        description: str,
        handler: Callable,
        parameters: list[ToolParameter] | None = None,
        source_terr: str | None = None,
        source_terr_description: str | None = None,
    ):
        self.name = name
        self.description = description
        self.handler = handler
        self.parameters = parameters or []
        self.source_terr = source_terr
        self.source_terr_description = source_terr_description

    async def execute(self, **kwargs: Any) -> Any:
        if asyncio.iscoroutinefunction(self.handler):
            return await self.handler(**kwargs)
        return self.handler(**kwargs)

    def to_openai_schema(self) -> dict:
        return build_openai_schema(self.name, self.description, self.parameters)

    def to_anthropic_schema(self) -> dict:
        return build_anthropic_schema(self.name, self.description, self.parameters)

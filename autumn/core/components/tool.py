import asyncio
from typing import Any, Callable
from pydantic import BaseModel


class ToolParameter(BaseModel):
    name: str
    type: str
    description: str
    required: bool = True


class Tool:
    """A callable tool with schemas compatible with OpenAI and Anthropic tool-use formats."""

    def __init__(
        self,
        name: str,
        description: str,
        fn: Callable,
        parameters: list[ToolParameter] | None = None,
    ):
        self.name = name
        self.description = description
        self.fn = fn
        self.parameters = parameters or []

    async def call(self, **kwargs: Any) -> Any:
        if asyncio.iscoroutinefunction(self.fn):
            return await self.fn(**kwargs)
        return self.fn(**kwargs)

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        p.name: {"type": p.type, "description": p.description}
                        for p in self.parameters
                    },
                    "required": [p.name for p in self.parameters if p.required],
                },
            },
        }

    def to_anthropic_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": {
                    p.name: {"type": p.type, "description": p.description}
                    for p in self.parameters
                },
                "required": [p.name for p in self.parameters if p.required],
            },
        }

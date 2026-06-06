import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolParameter:
    name: str
    type: str
    description: str
    required: bool = True
    # Free-form JSON Schema fields merged into this property's schema.
    # Use this to pass through `enum`, `items`, `default`, nested `properties`,
    # `minimum`, `maximum`, etc. — anything the model should see beyond the
    # base ``type`` / ``description``.
    extra: dict[str, Any] = field(default_factory=dict)


def _property_schema(p: ToolParameter) -> dict:
    schema: dict[str, Any] = {"type": p.type, "description": p.description}
    if p.extra:
        # `extra` wins on conflict so callers can override type/description if needed.
        schema.update(p.extra)
    return schema


def _json_schema(parameters: list[ToolParameter]) -> dict:
    return {
        "type": "object",
        "properties": {p.name: _property_schema(p) for p in parameters},
        "required": [p.name for p in parameters if p.required],
    }


def build_openai_schema(name: str, description: str, parameters: list[ToolParameter]) -> dict:
    """OpenAI function-calling schema. Shared by Tool and Skill."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": _json_schema(parameters),
        },
    }


def build_anthropic_schema(name: str, description: str, parameters: list[ToolParameter]) -> dict:
    """Anthropic tool-use schema. Shared by Tool and Skill."""
    return {
        "name": name,
        "description": description,
        "input_schema": _json_schema(parameters),
    }


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
        return build_openai_schema(self.name, self.description, self.parameters)

    def to_anthropic_schema(self) -> dict:
        return build_anthropic_schema(self.name, self.description, self.parameters)

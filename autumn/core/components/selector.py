import json
from ..types import InputType, Message, Role

_SYSTEM = """\
You are an input classifier for the Autumn framework.

Classify the user input as exactly one of:
- "task": Highly structured, directly executable content — e.g. todo lists, precise task descriptions in markdown.
- "mission": General human-model conversation or requests that require interpretation.

Respond with ONLY valid JSON: {"type": "task"} or {"type": "mission"}"""


class Selector:
    """WP1-exclusive input classifier. Determines whether input routes to WP2 (task) or WP3 (mission)."""

    def __init__(self, api_interface):
        self.api = api_interface

    async def classify(self, user_input: str) -> InputType:
        messages = [
            Message(role=Role.SYSTEM, content=_SYSTEM),
            Message(role=Role.USER, content=user_input),
        ]
        response = await self.api.complete(messages, max_tokens=32)
        try:
            data = json.loads(response.strip())
            return InputType(data["type"])
        except (json.JSONDecodeError, KeyError, ValueError):
            return InputType.MISSION

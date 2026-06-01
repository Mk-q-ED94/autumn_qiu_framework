import json
from ..types import InputType, Message, Role, SelectorResult

_DEFAULT_SYSTEM = """\
You are an input classifier for the Autumn framework.

Classify the user input as exactly one of:
- "task": Highly structured, directly executable content — e.g. todo lists, precise task descriptions in markdown.
- "mission": General human-model conversation or requests that require interpretation.

Respond with ONLY valid JSON:
{"type": "task", "confidence": 0.95}

confidence is a float 0.0–1.0 reflecting how certain you are."""

_CONFIRM_THRESHOLD = 0.75


class Selector:
    """WP1-exclusive input classifier. Triggers user confirmation only when confidence is low."""

    def __init__(self, api_interface, system_prompt: str | None = None):
        self.api = api_interface
        self._system = system_prompt or _DEFAULT_SYSTEM

    async def classify(self, user_input: str) -> SelectorResult:
        messages = [
            Message(role=Role.SYSTEM, content=self._system),
            Message(role=Role.USER, content=user_input),
        ]
        response = await self.api.complete(messages, max_tokens=64)
        try:
            data = json.loads(response.strip())
            return SelectorResult(
                input_type=InputType(data["type"]),
                confidence=float(data.get("confidence", 1.0)),
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            return SelectorResult(InputType.MISSION, 0.5)

    async def classify_and_maybe_confirm(self, user_input: str, interaction) -> InputType:
        """Classify; ask user to confirm only if confidence < threshold."""
        result = await self.classify(user_input)
        if interaction and result.confidence < _CONFIRM_THRESHOLD:
            confirmed = await interaction.ask(
                f"Input classified as [{result.input_type.value.upper()}] "
                f"(confidence {result.confidence:.0%}). Confirm or correct?",
                [t.value for t in InputType],
            )
            return InputType(confirmed)
        return result.input_type

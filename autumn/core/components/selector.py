import json
from ..types import InputType, TaskType, Message, Role, SelectorResult

_DEFAULT_SYSTEM = """\
You are an input classifier for the Autumn framework.

Classify the user input as exactly one of:
- "task": Highly structured, directly executable content — e.g. todo lists, precise task descriptions in markdown.
- "mission": General human-model conversation or requests that require interpretation.

For "task" inputs, also provide a task sub-type:
- "code": writing, debugging, reviewing, or refactoring code
- "search": looking up information, summarizing documents, Q&A over data
- "write": drafting prose, emails, reports, or creative writing (no code)
- "data": analyzing or transforming data, calculations, spreadsheet work
- "general": any structured task not clearly fitting the above

Respond with ONLY valid JSON.
Task example:  {"type": "task", "task_type": "code", "confidence": 0.95}
Mission example: {"type": "mission", "confidence": 0.9}

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
            input_type = InputType(data["type"])
            task_type: TaskType | None = None
            if input_type == InputType.TASK:
                raw = data.get("task_type", "general")
                try:
                    task_type = TaskType(raw)
                except ValueError:
                    task_type = TaskType.GENERAL
            return SelectorResult(
                input_type=input_type,
                confidence=float(data.get("confidence", 1.0)),
                task_type=task_type,
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            return SelectorResult(InputType.MISSION, 0.5)

    async def classify_and_maybe_confirm(self, user_input: str, interaction) -> SelectorResult:
        """Classify; ask user to confirm only if confidence < threshold."""
        result = await self.classify(user_input)
        if interaction and result.confidence < _CONFIRM_THRESHOLD:
            confirmed = await interaction.ask(
                f"Input classified as [{result.input_type.value.upper()}] "
                f"(confidence {result.confidence:.0%}). Confirm or correct?",
                [t.value for t in InputType],
            )
            confirmed_type = InputType(confirmed)
            task_type = result.task_type if confirmed_type == InputType.TASK else None
            return SelectorResult(confirmed_type, result.confidence, task_type)
        return result

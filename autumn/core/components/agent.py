from .tool import Tool
from .skill import Skill
from ..api.base import ModelAPIInterface
from ..types import Protocol

_MAX_STEPS = 10
_MAX_HISTORY_CONTEXT = 5

_REACT_SYSTEM = """\
You are {name}, an autonomous agent in the Autumn framework.
Tools and skills are exposed to you as callable functions. Reason step by step:
- Call a function to gather information, take an action, or reuse a capability.
When you have a final answer, respond in plain text without calling any function."""


def _format_memory_context(history: list[dict]) -> str:
    """Render recent memory history into a compact context block for the system prompt.

    Pulls the task/input and output of the most recent turns so the agent can
    reason with continuity. Best-effort: unknown entry shapes are skipped.
    """
    lines: list[str] = []
    for entry in history[-_MAX_HISTORY_CONTEXT:]:
        if not isinstance(entry, dict):
            continue
        task = entry.get("task") or entry.get("input") or ""
        output = entry.get("output") or ""
        if not (task or output):
            continue
        snippet = output if len(output) <= 200 else output[:200] + "…"
        lines.append(f"- {task}\n  → {snippet}")
    if not lines:
        return ""
    return "Recent context from your memory (oldest first):\n" + "\n".join(lines)


class Agent:
    """Autonomous agent with a ReAct (Reason + Act) loop.

    Maintains conversation state in the model's native provider format so that
    each round correctly carries the assistant's tool_calls and the tool results
    back to the model.

    Parameters
    ----------
    name : str
        Agent identity, woven into the ReAct system prompt.
    api : ModelAPIInterface
        Backing model. Any protocol works — OpenAI, Anthropic, or Hermes — since
        tool wire-format details are encapsulated by the interface.
    tools, skills : list
        Callable capabilities. Tools are exposed to the model as schemas; skills
        are invoked by name when the model calls them.
    instructions : str | None
        Extra system guidance appended after the ReAct base prompt. WP2 uses this
        to keep its task-executor persona while gaining tool access.
    """

    def __init__(
        self,
        name: str,
        api: ModelAPIInterface,
        tools: list[Tool] | None = None,
        skills: list[Skill] | None = None,
        instructions: str | None = None,
    ):
        self.name = name
        self.api = api
        self.tools: dict[str, Tool] = {t.name: t for t in (tools or [])}
        self.skills: dict[str, Skill] = {s.name: s for s in (skills or [])}
        self.instructions = instructions

    async def _build_system(self, memory) -> str:
        system = _REACT_SYSTEM.format(name=self.name)
        if self.instructions:
            system = f"{system}\n\n{self.instructions}"
        if memory is not None and hasattr(memory, "get_history"):
            try:
                history = await memory.get_history()
            except Exception:  # noqa: BLE001 — memory context is best-effort
                history = []
            ctx = _format_memory_context(history)
            if ctx:
                system = f"{system}\n\n{ctx}"
        return system

    async def run(self, task: str, memory=None) -> str:
        system = await self._build_system(memory)
        is_openai = self.api.protocol == Protocol.OPENAI

        # Provider-native message accumulator
        if is_openai:
            msgs: list[dict] = [
                {"role": "system", "content": system},
                {"role": "user", "content": task},
            ]
            api_system = None
        else:
            msgs = [{"role": "user", "content": task}]
            api_system = system

        # Both tools and skills are exposed to the model as callable functions.
        # On a name clash, the tool wins at execution time (checked first below).
        callables = [*self.tools.values(), *self.skills.values()]
        tool_schemas = [
            c.to_openai_schema() if is_openai else c.to_anthropic_schema()
            for c in callables
        ]

        for _ in range(_MAX_STEPS):
            text, tool_calls = await self.api.complete_with_tools_raw(
                msgs, tool_schemas, system=api_system
            )

            if not tool_calls:
                return text

            # Execute every requested tool
            results: list[str] = []
            for tc in tool_calls:
                try:
                    if tc.name in self.tools:
                        result = await self.tools[tc.name].call(**tc.arguments)
                    elif tc.name in self.skills:
                        result = await self.skills[tc.name].execute(tc.arguments)
                    else:
                        result = f"[error: unknown tool '{tc.name}']"
                except Exception as e:  # noqa: BLE001 — feed error back to model for ReAct recovery
                    result = f"[tool error: {e}]"
                results.append(str(result))

            msgs.append(self.api.build_assistant_tool_message(text, tool_calls))
            msgs.extend(self.api.build_tool_result_messages(tool_calls, results))

        return "[agent: max steps reached without a final answer]"

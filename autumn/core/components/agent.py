from .tool import Tool
from .skill import Skill
from ..api.base import ModelAPIInterface
from ..types import Protocol

_MAX_STEPS = 10

_REACT_SYSTEM = """\
You are {name}, an autonomous agent in the Autumn framework.
You have access to tools and skills. Reason step by step:
- Use tools to gather information or take actions.
- Invoke skills (via the run_skill tool, if available) to reuse pre-built capabilities.
When you have a final answer, respond in plain text without calling any tool."""


class Agent:
    """Autonomous agent with a ReAct (Reason + Act) loop.

    Maintains conversation state in the model's native provider format so that
    each round correctly carries the assistant's tool_calls and the tool results
    back to the model.
    """

    def __init__(
        self,
        name: str,
        api: ModelAPIInterface,
        tools: list[Tool] | None = None,
        skills: list[Skill] | None = None,
    ):
        self.name = name
        self.api = api
        self.tools: dict[str, Tool] = {t.name: t for t in (tools or [])}
        self.skills: dict[str, Skill] = {s.name: s for s in (skills or [])}

    async def run(self, task: str, memory=None) -> str:
        system = _REACT_SYSTEM.format(name=self.name)
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

        tool_schemas = [
            t.to_openai_schema() if is_openai else t.to_anthropic_schema()
            for t in self.tools.values()
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

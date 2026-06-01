import json
from .tool import Tool
from .skill import Skill
from ..api.base import ModelAPIInterface
from ..types import Message, Role, ToolCall

_MAX_STEPS = 10

_REACT_SYSTEM = """\
You are {name}, an autonomous agent in the Autumn framework.
You have access to tools. Use them step by step to complete the task.
When you have a final answer, respond in plain text without calling any tool."""


class Agent:
    """Autonomous agent with a ReAct (Reason + Act) loop.

    Each step: call the model → if tool call, execute tool and feed result back →
    repeat until the model returns a text answer or max steps is reached.
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
        raw_messages: list[dict] = [
            {"role": Role.SYSTEM.value, "content": system},
            {"role": Role.USER.value, "content": task},
        ]
        tool_schemas = [t.to_openai_schema() if self.api.protocol.value == "openai"
                        else t.to_anthropic_schema() for t in self.tools.values()]

        for _ in range(_MAX_STEPS):
            messages = [Message(role=Role(m["role"]), content=m["content"])
                        for m in raw_messages if isinstance(m.get("content"), str)]

            if tool_schemas:
                text, tool_calls = await self.api.complete_with_tools(messages, tool_schemas)
            else:
                text = await self.api.complete(messages)
                tool_calls = []

            if not tool_calls:
                return text or ""

            # Execute all tool calls
            results: list[str] = []
            for tc in tool_calls:
                if tc.name in self.tools:
                    result = await self.tools[tc.name].call(**tc.arguments)
                    results.append(str(result))
                else:
                    results.append(f"[error: unknown tool '{tc.name}']")

            # Append assistant message + tool results
            raw_messages.append({"role": "assistant", "content": None, "_tool_calls": tool_calls})
            for msg in self.api.make_tool_result_messages(tool_calls, results):
                raw_messages.append(msg)

        return "[agent: max steps reached without a final answer]"

"""Tests for the Agent ReAct loop using a mock API interface."""
import json
import pytest

from autumn.core.components.agent import Agent
from autumn.core.components.skill import Skill
from autumn.core.components.tool import Tool, ToolParameter
from autumn.core.types import Protocol, ToolCall


class MockAPI:
    """Replays a scripted sequence of (text, tool_calls) responses."""

    def __init__(self, protocol: Protocol, script: list[tuple[str, list[ToolCall]]]):
        self.protocol = protocol
        self._script = list(script)
        self.message_log: list[list[dict]] = []

    async def complete_with_tools_raw(self, messages, tools, system=None, **kwargs):
        self.message_log.append(list(messages))
        if not self._script:
            return "[exhausted]", []
        return self._script.pop(0)

    def build_assistant_tool_message(self, text, tool_calls):
        if self.protocol == Protocol.OPENAI:
            return {
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                    for tc in tool_calls
                ],
            }
        content = []
        if text:
            content.append({"type": "text", "text": text})
        for tc in tool_calls:
            content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
        return {"role": "assistant", "content": content}

    def build_tool_result_messages(self, tool_calls, results):
        if self.protocol == Protocol.OPENAI:
            return [{"role": "tool", "tool_call_id": tc.id, "content": r}
                    for tc, r in zip(tool_calls, results)]
        return [{
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tc.id, "content": r}
                        for tc, r in zip(tool_calls, results)],
        }]


@pytest.mark.parametrize("protocol", [Protocol.OPENAI, Protocol.ANTHROPIC])
async def test_agent_no_tools_returns_text(protocol):
    api = MockAPI(protocol, [("Final answer.", [])])
    agent = Agent("tester", api)
    result = await agent.run("Hello?")
    assert result == "Final answer."


@pytest.mark.parametrize("protocol", [Protocol.OPENAI, Protocol.ANTHROPIC])
async def test_agent_react_loop_executes_tool(protocol):
    calls = {"n": 0}

    async def add(a: int, b: int) -> int:
        calls["n"] += 1
        return a + b

    tool = Tool("add", "Add two ints", add, [
        ToolParameter(name="a", type="integer", description="a"),
        ToolParameter(name="b", type="integer", description="b"),
    ])

    api = MockAPI(protocol, [
        ("Calling tool", [ToolCall(id="t1", name="add", arguments={"a": 2, "b": 3})]),
        ("Result is 5", []),
    ])
    agent = Agent("tester", api, tools=[tool])
    result = await agent.run("What is 2 + 3?")
    assert result == "Result is 5"
    assert calls["n"] == 1

    # Critical: second call must include the assistant tool_use AND the tool_result
    second_call_msgs = api.message_log[1]
    assert len(second_call_msgs) > 2  # task + assistant tool_use + tool_result


async def test_agent_exposes_skill_as_function_and_invokes_it():
    invoked = {"ctx": None}

    async def handler(ctx):
        invoked["ctx"] = ctx
        return "summary text"

    skill = Skill("summarize", "summarize text", handler,
                  [ToolParameter(name="text", type="string", description="text")])

    api = MockAPI(Protocol.OPENAI, [
        ("Using skill", [ToolCall(id="s1", name="summarize", arguments={"text": "long input"})]),
        ("Done summarizing", []),
    ])
    agent = Agent("tester", api, skills=[skill])
    result = await agent.run("Summarize this.")
    assert result == "Done summarizing"
    assert invoked["ctx"] == {"text": "long input"}

    # The skill must have been advertised to the model as a function schema
    # (the MockAPI ignores tools, so assert on what Agent built instead).
    assert "summarize" in agent.skills


async def test_agent_skill_schema_sent_to_model():
    """Skills should appear in the tool schema list passed to the API."""
    seen_schemas = {}

    class CapturingAPI(MockAPI):
        async def complete_with_tools_raw(self, messages, tools, system=None, **kwargs):
            seen_schemas["tools"] = tools
            return await super().complete_with_tools_raw(messages, tools, system, **kwargs)

    skill = Skill("translate", "translate text", lambda ctx: "hola")
    tool = Tool("noop", "noop", lambda: "x", [])
    api = CapturingAPI(Protocol.OPENAI, [("final", [])])
    agent = Agent("tester", api, tools=[tool], skills=[skill])
    await agent.run("...")
    names = {t["function"]["name"] for t in seen_schemas["tools"]}
    assert names == {"noop", "translate"}


async def test_agent_unknown_tool_returns_error_to_model():
    api = MockAPI(Protocol.OPENAI, [
        ("Try this", [ToolCall(id="t1", name="nope", arguments={})]),
        ("OK, gave up", []),
    ])
    agent = Agent("tester", api)
    result = await agent.run("...")
    assert result == "OK, gave up"

    # Second-round messages should carry the tool_result with the error
    second = api.message_log[1]
    tool_results = [m for m in second if m.get("role") == "tool"]
    assert tool_results and "unknown tool" in tool_results[0]["content"]


async def test_agent_tool_exception_is_caught():
    async def boom(**kwargs):
        raise ValueError("kaboom")

    tool = Tool("boom", "explodes", boom, [])
    api = MockAPI(Protocol.OPENAI, [
        ("call it", [ToolCall(id="t1", name="boom", arguments={})]),
        ("recovered", []),
    ])
    agent = Agent("tester", api, tools=[tool])
    result = await agent.run("...")
    assert result == "recovered"
    second = api.message_log[1]
    assert any("tool error" in str(m.get("content", "")) for m in second)

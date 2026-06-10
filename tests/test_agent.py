"""Tests for the Agent ReAct loop using a mock API interface."""
import asyncio
import json
import pytest

from autumn.core.components.agent import Agent
from autumn.core.components.skill import Skill
from autumn.core.components.tool import Tool, ToolParameter
from autumn.core.types import AgentStep, Protocol, ToolCall


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
    captured = {}

    async def handler(**kwargs):
        captured.update(kwargs)
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
    assert captured == {"text": "long input"}

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

    skill = Skill("translate", "translate text", lambda **kw: "hola")
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


def test_agent_raises_on_tool_skill_name_collision():
    """A tool and skill with the same name would shadow at the model layer —
    must be caught at construction, not silently."""
    tool = Tool("search", "atomic search", lambda q: q,
                [ToolParameter(name="q", type="string", description="q")])
    skill = Skill("search", "high-level search", lambda **kw: "x",
                  [ToolParameter(name="q", type="string", description="q")])
    with pytest.raises(ValueError) as exc_info:
        Agent("tester", MockAPI(Protocol.OPENAI, []), tools=[tool], skills=[skill])
    assert "search" in str(exc_info.value)
    assert "collision" in str(exc_info.value)


def test_agent_multiple_collisions_listed():
    t1 = Tool("foo", "", lambda: None, [])
    t2 = Tool("bar", "", lambda: None, [])
    s1 = Skill("foo", "", lambda **kw: None)
    s2 = Skill("bar", "", lambda **kw: None)
    with pytest.raises(ValueError) as exc_info:
        Agent("x", MockAPI(Protocol.OPENAI, []), tools=[t1, t2], skills=[s1, s2])
    msg = str(exc_info.value)
    assert "foo" in msg and "bar" in msg


async def test_agent_max_steps_default_is_10():
    """Empty script + endless tool calls would loop forever; verify default cap."""
    # Construct a script that always issues a tool call, never finishes.
    api = MockAPI(Protocol.OPENAI, [
        (f"step {i}", [ToolCall(id=f"t{i}", name="noop", arguments={})])
        for i in range(20)
    ])
    tool = Tool("noop", "noop", lambda: "ok", [])
    agent = Agent("tester", api, tools=[tool])
    result = await agent.run("...")
    assert "max steps reached" in result
    assert agent.max_steps == 10
    # The mock got exactly max_steps tool-issuing turns
    assert len(api.message_log) == 10


async def test_agent_max_steps_configurable():
    """Custom max_steps bounds the loop differently."""
    api = MockAPI(Protocol.OPENAI, [
        (f"step {i}", [ToolCall(id=f"t{i}", name="noop", arguments={})])
        for i in range(20)
    ])
    tool = Tool("noop", "noop", lambda: "ok", [])
    agent = Agent("tester", api, tools=[tool], max_steps=3)
    result = await agent.run("...")
    assert "max steps reached" in result
    assert len(api.message_log) == 3


async def test_agent_skill_handler_receives_kwargs_not_dict():
    """G4: Skill handler signature is unified with Tool — receives **kwargs."""
    received = {}

    def handler(text: str, n: int):
        received["text"] = text
        received["n"] = n
        return "done"

    skill = Skill("op", "op", handler, [
        ToolParameter(name="text", type="string", description="t"),
        ToolParameter(name="n", type="integer", description="n"),
    ])
    api = MockAPI(Protocol.OPENAI, [
        ("calling", [ToolCall(id="s1", name="op", arguments={"text": "hi", "n": 3})]),
        ("done", []),
    ])
    agent = Agent("tester", api, skills=[skill])
    await agent.run("...")
    assert received == {"text": "hi", "n": 3}


async def test_agent_runs_parallel_tool_calls_concurrently():
    """Multiple tool calls in one turn must run concurrently, not serially.

    Two tools rendezvous: each signals its own event, then waits on the other's.
    If the agent awaited them one after another, the first would block forever
    waiting for the second to start — the wait_for timeout would fire. Passing
    proves both were in flight at the same time.
    """
    ev_a = asyncio.Event()
    ev_b = asyncio.Event()

    async def tool_a() -> str:
        ev_a.set()
        await asyncio.wait_for(ev_b.wait(), timeout=1.0)
        return "A"

    async def tool_b() -> str:
        ev_b.set()
        await asyncio.wait_for(ev_a.wait(), timeout=1.0)
        return "B"

    api = MockAPI(Protocol.OPENAI, [
        ("two at once", [
            ToolCall(id="a", name="a", arguments={}),
            ToolCall(id="b", name="b", arguments={}),
        ]),
        ("done", []),
    ])
    agent = Agent("tester", api, tools=[Tool("a", "", tool_a, []), Tool("b", "", tool_b, [])])
    result = await asyncio.wait_for(agent.run("..."), timeout=2.0)
    assert result == "done"


async def test_agent_parallel_results_preserve_order():
    """Concurrent execution must still feed results back in tool_call order."""
    async def slow() -> str:
        await asyncio.sleep(0.02)
        return "slow"

    async def fast() -> str:
        return "fast"

    api = MockAPI(Protocol.OPENAI, [
        ("go", [
            ToolCall(id="1", name="slow", arguments={}),
            ToolCall(id="2", name="fast", arguments={}),
        ]),
        ("final", []),
    ])
    agent = Agent("tester", api, tools=[Tool("slow", "", slow, []), Tool("fast", "", fast, [])])
    steps: list[AgentStep] = []
    await agent.run("...", steps=steps)

    # Result messages are zipped to tool_call ids: the slow tool's result must
    # still occupy slot 0 even though it finished last.
    tool_results = [m for m in api.message_log[1] if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_results] == ["1", "2"]
    assert [m["content"] for m in tool_results] == ["slow", "fast"]
    # Steps follow the same order, and the turn's tokens attach to the first only.
    assert [s.name for s in steps] == ["slow", "fast"]


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

"""Tests for WP2's agent integration: tools trigger a ReAct loop, no tools fall
back to a single completion, and memory history reaches the agent's prompt."""
import json
import pytest

from autumn.core.components.agent import Agent, _format_memory_context
from autumn.core.components.skill import Skill
from autumn.core.components.terr import Terr
from autumn.core.components.tool import Tool, ToolParameter
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.mom2 import Mom2
from autumn.core.memory.shared import SharedZone
from autumn.core.types import Protocol, ToolCall
from autumn.core.workspace.wp2 import WP2Tas


# ── test doubles ────────────────────────────────────────────────────────────────

class ScriptedAPI:
    """Mock API: scripts complete_with_tools_raw responses, records prompts."""

    def __init__(self, protocol=Protocol.OPENAI, script=None, completion="PLAIN-RESULT"):
        self.protocol = protocol
        self._script = list(script or [])
        self.completion = completion
        self.tool_prompts: list[list[dict]] = []  # messages passed to tool calls
        self.complete_prompts: list[list[dict]] = []  # messages passed to plain complete
        self.completion_called = False
        self.tools_called = False

    async def complete(self, messages, **kwargs):
        self.completion_called = True
        # Record so tests can introspect the system prompt that reached _run_plain.
        self.complete_prompts.append(list(messages))
        return self.completion

    async def complete_with_tools_raw(self, messages, tools, system=None, **kwargs):
        self.tools_called = True
        self.tool_prompts.append(list(messages))
        if not self._script:
            return "[exhausted]", []
        return self._script.pop(0)

    def build_assistant_tool_message(self, text, tool_calls):
        return {
            "role": "assistant",
            "content": text or None,
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                for tc in tool_calls
            ],
        }

    def build_tool_result_messages(self, tool_calls, results):
        return [{"role": "tool", "tool_call_id": tc.id, "content": r}
                for tc, r in zip(tool_calls, results)]


def make_memory() -> Mom2:
    shared = SharedZone(DictBackend())
    return Mom2(DictBackend(), shared)


def _system_of(api: ScriptedAPI, call_index: int = 0) -> str:
    """Extract the system message content from a recorded OpenAI-style prompt."""
    return api.tool_prompts[call_index][0]["content"]


# ── fallback path (no tools) ───────────────────────────────────────────────────

async def test_wp2_falls_back_to_completion_without_provider():
    api = ScriptedAPI(completion="plain done")
    wp2 = WP2Tas(api, make_memory())
    result = await wp2.process("do X")
    assert result == "plain done"
    assert api.completion_called
    assert not api.tools_called


async def test_wp2_falls_back_when_provider_empty():
    api = ScriptedAPI(completion="plain")
    wp2 = WP2Tas(api, make_memory(), tool_provider=lambda: ([], []))
    result = await wp2.process("x")
    assert result == "plain"
    assert not api.tools_called


# ── agent path (tools / skills present) ────────────────────────────────────────

async def test_wp2_runs_agent_when_tool_present():
    calls = {"n": 0}

    async def echo(text: str) -> str:
        calls["n"] += 1
        return f"echoed:{text}"

    tool = Tool("echo", "echo text", echo, [ToolParameter("text", "string", "t")])
    api = ScriptedAPI(script=[
        ("", [ToolCall(id="c1", name="echo", arguments={"text": "hi"})]),
        ("final from agent", []),
    ])
    wp2 = WP2Tas(api, make_memory(), tool_provider=lambda: ([tool], []))
    result = await wp2.process("use echo")
    assert result == "final from agent"
    assert calls["n"] == 1
    assert api.tools_called
    assert not api.completion_called


async def test_wp2_runs_agent_when_only_skill_present():
    api = ScriptedAPI(script=[("done", [])])
    skill = Skill("greet", "greets", lambda **kw: "hi")
    wp2 = WP2Tas(api, make_memory(), tool_provider=lambda: ([], [skill]))
    await wp2.process("x")
    assert api.tools_called
    assert not api.completion_called


async def test_wp2_agent_carries_system_instructions():
    api = ScriptedAPI(script=[("done", [])])
    tool = Tool("noop", "n", lambda: "x", [])
    wp2 = WP2Tas(api, make_memory(), system_prompt="CUSTOM-PERSONA",
                 tool_provider=lambda: ([tool], []))
    await wp2.process("task")
    assert "CUSTOM-PERSONA" in _system_of(api)


async def test_wp2_task_type_hint_appended_to_system():
    from autumn.core.types import TaskType
    api = ScriptedAPI(script=[("done", [])])
    tool = Tool("noop", "n", lambda: "x", [])
    wp2 = WP2Tas(api, make_memory(), system_prompt="BASE",
                 tool_provider=lambda: ([tool], []))
    await wp2.process("write code", task_type=TaskType.CODE)
    system = _system_of(api)
    assert "BASE" in system
    assert "correctness" in system  # from CODE hint


async def test_wp2_task_type_general_no_extra_hint():
    from autumn.core.types import TaskType
    api = ScriptedAPI(completion="plain")
    wp2 = WP2Tas(api, make_memory(), system_prompt="BASE")
    await wp2.process("do something", task_type=TaskType.GENERAL)
    # GENERAL maps to an empty hint, so the system prompt reaching the model
    # must be exactly the base persona — no trailing hint paragraph appended.
    assert api.completion_called
    system = api.complete_prompts[0][0].content
    assert system == "BASE"


async def test_wp2_plain_task_type_hint_in_system():
    from autumn.core.types import TaskType
    api = ScriptedAPI(completion="plain answer")
    wp2 = WP2Tas(api, make_memory(), system_prompt="BASE")
    # No tools → _run_plain path
    await wp2.process("find info", task_type=TaskType.SEARCH)
    assert api.completion_called
    # SEARCH appends a hint about retrieval tools to the BASE persona.
    system = api.complete_prompts[0][0].content
    assert system.startswith("BASE")
    assert "search and retrieval" in system
    output, stages, prompt, completion = await wp2.process_with_trace("find info", task_type=TaskType.SEARCH)
    assert output == "plain answer"
    assert stages == []
    assert prompt is None and completion is None


async def test_wp2_agent_injects_memory_history():
    api = ScriptedAPI(script=[("done", [])])
    mom2 = make_memory()
    await mom2.append_history({"task": "earlier task", "output": "earlier output"})
    tool = Tool("noop", "n", lambda: "x", [])
    wp2 = WP2Tas(api, mom2, tool_provider=lambda: ([tool], []))
    await wp2.process("new task")
    system = _system_of(api)
    assert "earlier task" in system
    assert "earlier output" in system


async def test_wp2_process_with_trace_emits_tool_stages():
    async def get_weather(city: str) -> str:
        return f"sunny in {city}"

    tool = Tool("get_weather", "weather", get_weather,
                [ToolParameter("city", "string", "city")])
    api = ScriptedAPI(script=[
        ("", [ToolCall(id="c1", name="get_weather", arguments={"city": "Paris"})]),
        ("It's sunny in Paris.", []),
    ])
    wp2 = WP2Tas(api, make_memory(), tool_provider=lambda: ([tool], []))
    output, stages, _, _ = await wp2.process_with_trace("weather in Paris?")

    assert output == "It's sunny in Paris."
    assert len(stages) == 2
    agent_stage = stages[0]
    assert agent_stage.kind == "agent"
    assert agent_stage.title == "WP2 Agent"
    assert "Agent 接管任务执行" in agent_stage.detail
    stage = stages[1]
    assert stage.kind == "tool"
    assert stage.title == "get_weather"
    assert stage.workspace == "WP2"
    assert "city=Paris" in stage.detail
    assert "sunny in Paris" in stage.detail


async def test_wp2_tool_stage_includes_source_terr():
    async def search(query: str) -> str:
        return f"hit:{query}"

    tool = Tool("web_search", "search", search, [ToolParameter("query", "string", "q")])
    terr = Terr("web", "web tools", tools=[tool])
    api = ScriptedAPI(script=[
        ("", [ToolCall(id="c1", name="web_search", arguments={"query": "autumn"})]),
        ("done", []),
    ])
    wp2 = WP2Tas(api, make_memory(), tool_provider=lambda: (terr.tools, []))

    _, stages, _, _ = await wp2.process_with_trace("search autumn")

    agent_stage = next(stage for stage in stages if stage.kind == "agent")
    tool_stage = next(stage for stage in stages if stage.kind == "tool")
    assert agent_stage.source_terr == "web"
    assert "Terr: web" in agent_stage.detail
    assert tool_stage.source_terr == "web"


async def test_wp2_process_with_trace_no_tools_empty_stages():
    api = ScriptedAPI(completion="plain answer")
    wp2 = WP2Tas(api, make_memory())
    output, stages, _, _ = await wp2.process_with_trace("hello")
    assert output == "plain answer"
    assert stages == []


async def test_wp2_tool_stage_truncates_long_result():
    async def big(x: str) -> str:
        return "y" * 500

    tool = Tool("big", "big output", big, [ToolParameter("x", "string", "x")])
    api = ScriptedAPI(script=[
        ("", [ToolCall(id="c1", name="big", arguments={"x": "go"})]),
        ("done", []),
    ])
    wp2 = WP2Tas(api, make_memory(), tool_provider=lambda: ([tool], []))
    _, stages, _, _ = await wp2.process_with_trace("t")
    tool_stage = next(stage for stage in stages if stage.kind == "tool")
    assert "…" in tool_stage.detail
    assert len(tool_stage.detail) < 200


async def test_agent_steps_collector_records_each_call():
    async def f(a: int) -> int:
        return a * 2

    tool = Tool("dbl", "double", f, [ToolParameter("a", "integer", "a")])
    api = ScriptedAPI(script=[
        ("", [ToolCall(id="c1", name="dbl", arguments={"a": 5})]),
        ("ten", []),
    ])
    agent = Agent("X", api, tools=[tool])
    steps = []
    result = await agent.run("double 5", steps=steps)
    assert result == "ten"
    assert len(steps) == 1
    assert steps[0].name == "dbl"
    assert steps[0].arguments == {"a": 5}
    assert steps[0].result == "10"


async def test_wp2_records_history_after_agent():
    api = ScriptedAPI(script=[("agent-final", [])])
    mom2 = make_memory()
    tool = Tool("noop", "n", lambda: "x", [])
    wp2 = WP2Tas(api, mom2, tool_provider=lambda: ([tool], []))
    await wp2.process("the task")
    hist = await mom2.get_history()
    assert hist[-1].content["task"] == "the task"
    assert hist[-1].content["output"] == "agent-final"


async def test_wp2_agent_respects_checker():
    api = ScriptedAPI(script=[("raw-output", [])])

    class StubChecker:
        async def validate(self, output, memory):
            return True, output + "-checked"

    tool = Tool("noop", "n", lambda: "x", [])
    wp2 = WP2Tas(api, make_memory(), tool_provider=lambda: ([tool], []))
    wp2.checker = StubChecker()
    result = await wp2.process("t")
    assert result == "raw-output-checked"


# ── Agent.instructions + memory unit coverage ──────────────────────────────────

async def test_agent_instructions_appended_to_system():
    api = ScriptedAPI(script=[("ok", [])])
    agent = Agent("X", api, instructions="EXTRA-RULES")
    await agent.run("task")
    system = _system_of(api)
    assert "EXTRA-RULES" in system
    assert "autonomous agent" in system  # base ReAct prompt preserved


async def test_agent_memory_history_in_system():
    api = ScriptedAPI(script=[("ok", [])])
    mom2 = make_memory()
    await mom2.append_history({"task": "prior", "output": "prior-result"})
    agent = Agent("X", api)
    await agent.run("task", memory=mom2)
    assert "prior" in _system_of(api)


async def test_agent_without_memory_has_no_context_block():
    api = ScriptedAPI(script=[("ok", [])])
    agent = Agent("X", api)
    await agent.run("task")
    assert "Recent context" not in _system_of(api)


# ── _format_memory_context helper ──────────────────────────────────────────────

def test_format_memory_context_basic():
    out = _format_memory_context([
        {"task": "t1", "output": "o1"},
        {"input": "t2", "output": "o2"},
    ])
    assert "t1" in out and "o1" in out
    assert "t2" in out and "o2" in out


def test_format_memory_context_empty():
    assert _format_memory_context([]) == ""
    assert _format_memory_context([{"foo": "bar"}]) == ""


def test_format_memory_context_truncates_long_output():
    out = _format_memory_context([{"task": "t", "output": "x" * 500}])
    assert "…" in out
    assert len(out) < 400


def test_format_memory_context_limits_to_recent():
    history = [{"task": f"t{i}", "output": f"o{i}"} for i in range(20)]
    out = _format_memory_context(history)
    assert "t19" in out       # most recent included
    assert "t0" not in out    # oldest dropped (only last 5 kept)


# ── end-to-end: registered tools reach WP2 via Autumn ──────────────────────────

def _autumn_config(tmp_path):
    from autumn.core.config import AutumnConfig, ModelConfig, StorageConfig
    mc = ModelConfig("k", "http://localhost", "m", Protocol.OPENAI)
    return AutumnConfig(a1=mc, a2=mc, a3=mc,
                        storage=StorageConfig(db_path=str(tmp_path / "mem.db")))


def test_collect_plugins_separates_tools_and_skills(tmp_path):
    from autumn import Autumn
    autumn = Autumn(_autumn_config(tmp_path))
    tool = Tool("mytool", "d", lambda: "x", [])
    skill = Skill("myskill", "d", lambda **kw: "y")
    autumn.register_tool(tool)
    autumn.register_skill(skill)
    tools, skills = autumn._collect_plugins()
    assert tool in tools
    assert skill in skills


def test_wp2_provider_wired_to_collect_plugins(tmp_path):
    from autumn import Autumn
    autumn = Autumn(_autumn_config(tmp_path))
    # WP2's provider should be the framework's live plugin snapshot.
    tool = Tool("late", "registered after build", lambda: "z", [])
    autumn.register_tool(tool)
    tools, _ = autumn.wp2._tool_provider()
    assert tool in tools


# ── Hermes-backed WP2: full XML tool-call loop ─────────────────────────────────

async def test_hermes_backed_wp2_full_tool_loop():
    """A Hermes-backed A2 runs WP2's agent loop end to end: the model emits a
    <tool_call>, HermesAPIInterface parses it, the tool runs, and the result is
    fed back as a <tool_response> — all transparent to WP2 and the Agent."""
    from autumn.core.api.hermes import HermesAPIInterface

    api = HermesAPIInterface("key", "http://localhost:11434", "hermes3:8b")

    responses = [
        {"choices": [{"message": {"content":
            '<tool_call>\n{"name": "get_time", "arguments": {"tz": "UTC"}}\n</tool_call>'}}]},
        {"choices": [{"message": {"content": "The time is 12:00 UTC."}}]},
    ]
    sent: list[dict] = []

    async def fake_post(endpoint, payload):
        sent.append(payload)
        return responses[len(sent) - 1]

    api._post_with_retry = fake_post  # bypass HTTP, keep all Hermes parsing logic

    async def get_time(tz: str) -> str:
        return f"12:00 {tz}"

    tool = Tool("get_time", "current time", get_time,
                [ToolParameter("tz", "string", "timezone")])

    wp2 = WP2Tas(api, make_memory(), tool_provider=lambda: ([tool], []))
    result = await wp2.process("What time is it?")

    assert result == "The time is 12:00 UTC."
    # First request advertises the tool inside the <tools> system block.
    first_system = next(m for m in sent[0]["messages"] if m["role"] == "system")
    assert "get_time" in first_system["content"]
    assert "<tools>" in first_system["content"]
    # Second request carries the tool result back as a <tool_response>.
    blob = json.dumps(sent[1], ensure_ascii=False)
    assert "<tool_response>" in blob
    assert "12:00 UTC" in blob


# ── WP1 trace integration: tool stages surface in the pipeline trace ───────────

async def test_wp1_trace_includes_wp2_tool_stages():
    from autumn.core.workspace.wp1 import WP1Tot
    from autumn.core.memory.mom1 import Mom1
    from autumn.core.memory.mom2 import Mom2
    from autumn.core.memory.mom3 import Mom3
    from autumn.core.types import WorkflowStage, InputType, TaskType, SelectorResult

    class StubWP2:
        async def process_with_trace(self, task, task_type=None):
            return "wp2 output", [WorkflowStage(
                id="wp2.tool.0.search", title="search", detail="q=x → result",
                workspace="WP2", status="completed", kind="tool",
            )], None, None

    class StubSelector:
        async def classify_and_maybe_confirm(self, inp, interaction):
            return SelectorResult(InputType.TASK, 0.9, TaskType.CODE)

    shared = SharedZone(DictBackend())
    mom2 = Mom2(DictBackend(), shared)
    mom3 = Mom3(DictBackend(), shared)
    mom1 = Mom1(DictBackend(), mom2, mom3)

    wp1 = WP1Tot(api=None, memory=mom1, wp2=StubWP2(), wp3=None)
    wp1.selector = StubSelector()
    wp1.checker = None  # skip final check (no api needed)

    run = await wp1.process_with_trace("do a task")
    tool_stages = [s for s in run.stages if s.kind == "tool"]
    assert len(tool_stages) == 1
    assert tool_stages[0].title == "search"
    # Tool stage must precede the wp2.task completion marker.
    ids = [s.id for s in run.stages]
    assert ids.index("wp2.tool.0.search") < ids.index("wp2.task")
    # task_type surfaced in WorkflowRun
    assert run.task_type == TaskType.CODE
    # classification stage detail includes sub-type
    sel_stage = next(s for s in run.stages if s.id == "wp1.select")
    assert "code" in sel_stage.detail

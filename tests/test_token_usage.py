"""Tests for token usage tracking through the API → Agent → Workspace pipeline."""
import pytest

from autumn.core.api.base import ModelAPIInterface
from autumn.core.api.hermes import HermesAPIInterface
from autumn.core.components.agent import Agent
from autumn.core.components.tool import Tool, ToolParameter
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.mom2 import Mom2
from autumn.core.memory.shared import SharedZone
from autumn.core.types import Protocol, ToolCall
from autumn.core.workspace.wp2 import WP2Tas


# ── ModelAPIInterface._record_usage ───────────────────────────────────────────


def _make_interface(protocol: Protocol) -> ModelAPIInterface:
    return ModelAPIInterface("k", "https://x", "m", protocol)


def test_record_usage_openai_shape():
    api = _make_interface(Protocol.OPENAI)
    api._record_usage({"usage": {"prompt_tokens": 100, "completion_tokens": 25}})
    assert api.last_usage == {"prompt_tokens": 100, "completion_tokens": 25}


def test_record_usage_anthropic_shape():
    api = _make_interface(Protocol.ANTHROPIC)
    api._record_usage({"usage": {"input_tokens": 80, "output_tokens": 30}})
    assert api.last_usage == {"prompt_tokens": 80, "completion_tokens": 30}


def test_record_usage_missing_block_sets_none():
    api = _make_interface(Protocol.OPENAI)
    api.last_usage = {"prompt_tokens": 5, "completion_tokens": 5}
    api._record_usage({"choices": []})
    assert api.last_usage is None


def test_record_usage_partial_values_normalised_to_zero():
    """Providers that only return one side should still produce a complete dict."""
    api = _make_interface(Protocol.OPENAI)
    api._record_usage({"usage": {"prompt_tokens": 50}})
    assert api.last_usage == {"prompt_tokens": 50, "completion_tokens": 0}


def test_record_usage_empty_usage_dict_sets_none():
    api = _make_interface(Protocol.OPENAI)
    api._record_usage({"usage": {}})
    assert api.last_usage is None


def test_record_usage_hermes_inherits_openai_shape():
    """Hermes uses OpenAI's `usage` shape via /v1/chat/completions."""
    api = HermesAPIInterface("k", "https://x", "m")
    api._record_usage({"usage": {"prompt_tokens": 7, "completion_tokens": 3}})
    assert api.last_usage == {"prompt_tokens": 7, "completion_tokens": 3}


def test_last_usage_starts_none():
    api = _make_interface(Protocol.OPENAI)
    assert api.last_usage is None


# ── Agent loop token accumulation ─────────────────────────────────────────────


class _UsageReportingAPI:
    """Mock API that emits one scripted usage dict per call."""

    protocol = Protocol.OPENAI

    def __init__(self, script, usage_per_call):
        self._script = list(script)
        self._usage_per_call = list(usage_per_call)
        self.last_usage = None

    async def complete_with_tools_raw(self, messages, tools, system=None, **kwargs):
        self.last_usage = self._usage_per_call.pop(0) if self._usage_per_call else None
        return self._script.pop(0)

    def build_assistant_tool_message(self, text, tool_calls):
        return {"role": "assistant", "content": text}

    def build_tool_result_messages(self, tool_calls, results):
        return [{"role": "tool", "content": r} for r in results]


async def test_agent_total_tokens_zero_when_no_usage_reported():
    api = _UsageReportingAPI(
        script=[("final answer", [])],
        usage_per_call=[None],
    )
    agent = Agent("a", api)
    await agent.run("hi")
    assert agent.total_prompt_tokens == 0
    assert agent.total_completion_tokens == 0


async def test_agent_total_tokens_accumulate_across_turns():
    tool = Tool("noop", "", lambda: "ok", [])
    api = _UsageReportingAPI(
        script=[
            ("calling", [ToolCall(id="t1", name="noop", arguments={})]),
            ("done", []),
        ],
        usage_per_call=[
            {"prompt_tokens": 100, "completion_tokens": 20},
            {"prompt_tokens": 150, "completion_tokens": 30},
        ],
    )
    agent = Agent("a", api, tools=[tool])
    result = await agent.run("hi")
    assert result == "done"
    assert agent.total_prompt_tokens == 250
    assert agent.total_completion_tokens == 50


async def test_agent_step_attributes_tokens_to_first_call_only():
    """When one LLM turn issues multiple tool calls, only the first AgentStep
    carries the (single) LLM cost so summing per-step doesn't multi-count."""
    from autumn.core.types import AgentStep

    tool_a = Tool("a", "", lambda: "ra", [])
    tool_b = Tool("b", "", lambda: "rb", [])
    api = _UsageReportingAPI(
        script=[
            ("two calls", [
                ToolCall(id="t1", name="a", arguments={}),
                ToolCall(id="t2", name="b", arguments={}),
            ]),
            ("done", []),
        ],
        usage_per_call=[
            {"prompt_tokens": 200, "completion_tokens": 50},
            {"prompt_tokens": 50, "completion_tokens": 5},
        ],
    )
    steps: list[AgentStep] = []
    agent = Agent("a", api, tools=[tool_a, tool_b])
    await agent.run("go", steps=steps)
    assert len(steps) == 2
    assert steps[0].prompt_tokens == 200
    assert steps[0].completion_tokens == 50
    # Second call from the same turn is attributed None to avoid double-counting.
    assert steps[1].prompt_tokens is None
    assert steps[1].completion_tokens is None
    # Aggregate at agent level still counts each turn's usage exactly once.
    assert agent.total_prompt_tokens == 250
    assert agent.total_completion_tokens == 55


async def test_agent_total_resets_on_each_run():
    api = _UsageReportingAPI(
        script=[("done", []), ("done", [])],
        usage_per_call=[
            {"prompt_tokens": 100, "completion_tokens": 10},
            {"prompt_tokens": 200, "completion_tokens": 20},
        ],
    )
    agent = Agent("a", api)
    await agent.run("first")
    assert agent.total_prompt_tokens == 100
    await agent.run("second")
    # Second run starts fresh, not 100+200.
    assert agent.total_prompt_tokens == 200
    assert agent.total_completion_tokens == 20


# ── WP2 surfaces aggregate token totals ───────────────────────────────────────


def _make_memory() -> Mom2:
    shared = SharedZone(DictBackend())
    return Mom2(DictBackend(), shared)


class _ScriptedAPI:
    """Mock API for WP2: serves both complete() and complete_with_tools_raw()."""

    protocol = Protocol.OPENAI

    def __init__(self, completion=None, tool_script=None, usage=None):
        self._completion = completion
        self._tool_script = list(tool_script or [])
        self._usage = usage
        self.last_usage = None

    async def complete(self, messages, **kwargs):
        self.last_usage = self._usage
        return self._completion or ""

    async def complete_with_tools_raw(self, messages, tools, system=None, **kwargs):
        self.last_usage = self._usage
        if not self._tool_script:
            return "[exhausted]", []
        return self._tool_script.pop(0)

    def build_assistant_tool_message(self, text, tool_calls):
        return {"role": "assistant", "content": text}

    def build_tool_result_messages(self, tool_calls, results):
        return [{"role": "tool", "content": r} for r in results]


async def test_wp2_process_with_trace_returns_token_totals_plain():
    api = _ScriptedAPI(
        completion="plain answer",
        usage={"prompt_tokens": 80, "completion_tokens": 12},
    )
    wp2 = WP2Tas(api, _make_memory())
    output, stages, prompt, completion = await wp2.process_with_trace("hi")
    assert output == "plain answer"
    assert stages == []
    assert prompt == 80
    assert completion == 12


async def test_wp2_process_with_trace_returns_none_when_no_usage():
    api = _ScriptedAPI(completion="plain", usage=None)
    wp2 = WP2Tas(api, _make_memory())
    _, _, prompt, completion = await wp2.process_with_trace("hi")
    assert prompt is None
    assert completion is None


async def test_wp2_process_with_trace_returns_agent_aggregate_with_tools():
    tool = Tool("noop", "", lambda: "ok", [])
    api = _ScriptedAPI(
        tool_script=[
            ("calling", [ToolCall(id="t1", name="noop", arguments={})]),
            ("done", []),
        ],
        usage={"prompt_tokens": 60, "completion_tokens": 5},
    )
    wp2 = WP2Tas(api, _make_memory(), tool_provider=lambda: ([tool], []))
    output, stages, prompt, completion = await wp2.process_with_trace("go")
    assert output == "done"
    # Agent made 2 LLM calls; both report the same usage.
    assert prompt == 120     # 60 * 2 turns
    assert completion == 10  # 5 * 2 turns
    # First tool stage carries the first turn's usage.
    tool_stage = next(stage for stage in stages if stage.kind == "tool")
    assert tool_stage.prompt_tokens == 60
    assert tool_stage.completion_tokens == 5
    agent_stage = next(stage for stage in stages if stage.kind == "agent")
    assert agent_stage.prompt_tokens is None
    assert agent_stage.completion_tokens is None


# ── WP1 _capture_usage ────────────────────────────────────────────────────────


def test_capture_usage_reads_and_clears():
    from autumn.core.workspace.wp1 import _capture_usage

    class FakeAPI:
        last_usage = {"prompt_tokens": 11, "completion_tokens": 7}

    api = FakeAPI()
    prompt, completion = _capture_usage(api)
    assert prompt == 11
    assert completion == 7
    assert api.last_usage is None


def test_capture_usage_handles_none_api():
    from autumn.core.workspace.wp1 import _capture_usage

    assert _capture_usage(None) == (None, None)


def test_capture_usage_handles_mock_without_attribute():
    from autumn.core.workspace.wp1 import _capture_usage

    class Bare:
        pass

    assert _capture_usage(Bare()) == (None, None)


def test_capture_usage_handles_empty_dict():
    from autumn.core.workspace.wp1 import _capture_usage

    class FakeAPI:
        last_usage = {}

    assert _capture_usage(FakeAPI()) == (None, None)

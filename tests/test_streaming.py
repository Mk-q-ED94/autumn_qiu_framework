"""Tests for real-time streaming: tokens flow directly, Checker becomes advisory."""
import pytest

from autumn.core.components.checker import Checker
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.mom1 import Mom1
from autumn.core.memory.mom2 import Mom2
from autumn.core.memory.mom3 import Mom3
from autumn.core.memory.shared import SharedZone
from autumn.core.types import (
    InputType,
    MissionRoute,
    Protocol,
    SelectorResult,
    TaskType,
    WorkflowRun,
)
from autumn.core.workspace.wp1 import WP1Tot, _ADVISORY_PREFIX
from autumn.core.workspace.wp2 import WP2Tas
from autumn.core.workspace.wp3 import WP3Mis


# ── test doubles ────────────────────────────────────────────────────────────────


class StreamingAPI:
    """Yields a scripted sequence of tokens; records the prompt it was given."""

    def __init__(self, tokens: list[str], complete_response: str = "ok"):
        self._tokens = list(tokens)
        self.protocol = Protocol.OPENAI
        self.stream_messages: list[list] = []
        self.complete_response = complete_response

    async def complete(self, messages, **kwargs):
        return self.complete_response

    async def stream_complete(self, messages, **kwargs):
        self.stream_messages.append(list(messages))
        for tok in self._tokens:
            yield tok


class StubSelector:
    def __init__(self, sel_result: SelectorResult):
        self._result = sel_result

    async def classify_and_maybe_confirm(self, inp, interaction):
        return self._result


class PassingChecker:
    """Checker stub: inspect always says ok."""

    async def inspect(self, output, memory):
        return True, ""

    async def validate(self, output, memory):
        return True, output


class FlaggingChecker:
    """Checker stub: inspect always says NOT ok with a specific issue."""

    def __init__(self, issue: str = "too vague"):
        self.issue = issue

    async def inspect(self, output, memory):
        return False, self.issue

    async def validate(self, output, memory):
        return True, output


# ── fixtures ──────────────────────────────────────────────────────────────────


def make_memories():
    shared = SharedZone(DictBackend())
    mom2 = Mom2(DictBackend(), shared)
    mom3 = Mom3(DictBackend(), shared)
    mom1 = Mom1(DictBackend(), mom2, mom3)
    return mom1, mom2, mom3


def make_wp1(task_tokens=None, mission_tokens=None, sel_result=None, checker=None,
             headless_route=MissionRoute.DIRECT):
    mom1, mom2, mom3 = make_memories()
    wp2 = WP2Tas(StreamingAPI(task_tokens or []), mom2)
    wp3 = WP3Mis(StreamingAPI(mission_tokens or []), mom3)
    wp1 = WP1Tot(
        api=None, memory=mom1, wp2=wp2, wp3=wp3,
        headless_mission_route=headless_route,
    )
    wp1.selector = StubSelector(
        sel_result or SelectorResult(InputType.MISSION, 0.9, None)
    )
    wp1.checker = checker
    return wp1, wp2, wp3, mom1


# ── WP2 stream ──────────────────────────────────────────────────────────────────


async def test_wp2_stream_yields_tokens_in_order():
    api = StreamingAPI(["Hel", "lo, ", "world", "!"])
    mom1, mom2, _ = make_memories()
    wp2 = WP2Tas(api, mom2)
    chunks = []
    async for tok in wp2.stream("task"):
        chunks.append(tok)
    assert chunks == ["Hel", "lo, ", "world", "!"]


async def test_wp2_stream_persists_memory_after_stream():
    api = StreamingAPI(["a", "b", "c"])
    mom1, mom2, _ = make_memories()
    wp2 = WP2Tas(api, mom2)
    async for _ in wp2.stream("the task"):
        pass
    history = await mom2.get_history()
    assert any(h.get("task") == "the task" and h.get("output") == "abc" for h in history)


async def test_wp2_stream_applies_task_type_hint_to_system():
    api = StreamingAPI(["x"])
    mom1, mom2, _ = make_memories()
    wp2 = WP2Tas(api, mom2, system_prompt="BASE")
    async for _ in wp2.stream("do x", task_type=TaskType.SEARCH):
        pass
    system = api.stream_messages[0][0].content
    assert "BASE" in system
    assert "search and retrieval" in system  # SEARCH hint


async def test_wp2_stream_falls_back_to_buffered_when_tools_registered():
    """Tools require full responses; stream() should still yield chunks via chunking."""
    from autumn.core.components.tool import Tool

    class BufferedAPI:
        """API where stream_complete is intentionally broken; agent loop uses complete_with_tools_raw."""
        protocol = Protocol.OPENAI
        async def complete(self, messages, **kwargs):
            return "fallback result that is long enough to be chunked"
        async def stream_complete(self, messages, **kwargs):
            raise AssertionError("stream_complete must not be called when tools are registered")
            if False:
                yield  # type: ignore
        async def complete_with_tools_raw(self, messages, tools, system=None, **kwargs):
            return ("agent buffered output (no tool calls)", [])
        def build_assistant_tool_message(self, text, tool_calls):
            return {"role": "assistant", "content": text}
        def build_tool_result_messages(self, tool_calls, results):
            return []

    api = BufferedAPI()
    tool = Tool("noop", "noop", lambda: "x", [])
    mom1, mom2, _ = make_memories()
    wp2 = WP2Tas(api, mom2, tool_provider=lambda: ([tool], []))
    chunks = []
    async for tok in wp2.stream("task"):
        chunks.append(tok)
    full = "".join(chunks)
    assert "agent buffered output" in full


# ── WP3 stream ──────────────────────────────────────────────────────────────────


async def test_wp3_stream_direct_yields_tokens():
    api = StreamingAPI(["Once ", "upon ", "a time"])
    _, _, mom3 = make_memories()
    wp3 = WP3Mis(api, mom3)
    chunks = []
    async for tok in wp3.stream_direct("tell me a story"):
        chunks.append(tok)
    assert chunks == ["Once ", "upon ", "a time"]


async def test_wp3_stream_direct_persists_memory_with_direct_route():
    api = StreamingAPI(["hi"])
    _, _, mom3 = make_memories()
    wp3 = WP3Mis(api, mom3)
    async for _ in wp3.stream_direct("greet"):
        pass
    history = await mom3.get_history()
    assert history
    assert history[-1]["mission"] == "greet"
    assert history[-1]["route"] == MissionRoute.DIRECT.value
    assert history[-1]["output"] == "hi"


# ── WP1 orchestration: stream ─────────────────────────────────────────────────


async def test_wp1_stream_task_path_forwards_wp2_tokens():
    wp1, wp2, _, _ = make_wp1(
        task_tokens=["Step1 ", "Step2 ", "Done."],
        sel_result=SelectorResult(InputType.TASK, 0.95, TaskType.CODE),
        checker=PassingChecker(),
    )
    chunks = []
    async for tok in wp1.stream("write code"):
        chunks.append(tok)
    assert "".join(chunks) == "Step1 Step2 Done."


async def test_wp1_stream_mission_direct_forwards_wp3_tokens():
    wp1, _, _, _ = make_wp1(
        mission_tokens=["hello ", "world"],
        sel_result=SelectorResult(InputType.MISSION, 0.9, None),
        checker=PassingChecker(),
    )
    chunks = []
    async for tok in wp1.stream("hi", mission_route=MissionRoute.DIRECT):
        chunks.append(tok)
    assert "".join(chunks) == "hello world"


async def test_wp1_stream_passing_check_emits_no_advisory():
    wp1, _, _, _ = make_wp1(
        task_tokens=["This is a long enough answer."],
        sel_result=SelectorResult(InputType.TASK, 0.9, None),
        checker=PassingChecker(),
    )
    chunks = [tok async for tok in wp1.stream("do x")]
    assert _ADVISORY_PREFIX not in "".join(chunks)


async def test_wp1_stream_failing_check_appends_advisory_chunk():
    wp1, _, _, _ = make_wp1(
        task_tokens=["short text"],
        sel_result=SelectorResult(InputType.TASK, 0.9, None),
        checker=FlaggingChecker(issue="missing details"),
    )
    chunks = [tok async for tok in wp1.stream("do x")]
    full = "".join(chunks)
    assert "short text" in full
    # advisory comes AFTER the streamed content
    assert full.endswith("missing details")
    assert _ADVISORY_PREFIX in full
    assert full.index("short text") < full.index("missing details")


async def test_wp1_stream_no_checker_no_advisory():
    wp1, _, _, _ = make_wp1(
        task_tokens=["plain answer"],
        sel_result=SelectorResult(InputType.TASK, 0.9, None),
        checker=None,
    )
    chunks = [tok async for tok in wp1.stream("do x")]
    assert "".join(chunks) == "plain answer"


async def test_wp1_stream_writes_mom1_history():
    wp1, _, _, mom1 = make_wp1(
        task_tokens=["Final ", "Answer"],
        sel_result=SelectorResult(InputType.TASK, 0.9, TaskType.CODE),
        checker=PassingChecker(),
    )
    async for _ in wp1.stream("code something"):
        pass
    history = await mom1.get_history()
    assert history
    entry = history[-1]
    assert entry["input"] == "code something"
    assert entry["type"] == "task"
    assert entry["output"] == "Final Answer"
    assert entry["route"] is None  # task path has no mission route


async def test_wp1_stream_with_trace_finishes_with_workflow_run():
    wp1, _, _, mom1 = make_wp1(
        task_tokens=["Final ", "Answer"],
        sel_result=SelectorResult(InputType.TASK, 0.9, TaskType.CODE),
        checker=PassingChecker(),
    )

    events = [event async for event in wp1.stream_with_trace("code something")]
    chunks = [event for event in events if isinstance(event, str)]
    runs = [event for event in events if isinstance(event, WorkflowRun)]

    assert "".join(chunks) == "Final Answer"
    assert len(runs) == 1
    assert runs[0].output == "Final Answer"
    assert runs[0].input_type == InputType.TASK
    assert runs[0].task_type == TaskType.CODE
    assert [stage.id for stage in runs[0].stages] == [
        "wp1.select",
        "wp2.task",
        "wp1.final_check",
    ]
    history = await mom1.get_history()
    assert len(history) == 1


async def test_wp1_stream_advisory_included_in_mom1_output():
    """Advisory text should also live in mom1 so the conversation log matches the UI."""
    wp1, _, _, mom1 = make_wp1(
        task_tokens=["text"],
        sel_result=SelectorResult(InputType.TASK, 0.9, None),
        checker=FlaggingChecker(issue="too short"),
    )
    async for _ in wp1.stream("do x"):
        pass
    history = await mom1.get_history()
    assert "too short" in history[-1]["output"]


async def test_wp1_stream_convert_path_uses_buffered_wp2():
    """Convert path runs WP3.convert_to_task synchronously then streams WP2's execution."""
    mom1, mom2, mom3 = make_memories()

    class ConvertingAPI:
        protocol = Protocol.OPENAI
        async def complete(self, messages, **kwargs):
            return "converted-task-form (enough characters here)"
        async def stream_complete(self, messages, **kwargs):
            if False:
                yield  # type: ignore

    class WP2StreamingAPI:
        protocol = Protocol.OPENAI
        async def complete(self, messages, **kwargs):
            return "exec"
        async def stream_complete(self, messages, **kwargs):
            for tok in ["exec ", "result"]:
                yield tok

    wp3 = WP3Mis(ConvertingAPI(), mom3)
    wp2 = WP2Tas(WP2StreamingAPI(), mom2)
    wp1 = WP1Tot(api=None, memory=mom1, wp2=wp2, wp3=wp3,
                 headless_mission_route=MissionRoute.CONVERT)
    wp1.selector = StubSelector(SelectorResult(InputType.MISSION, 0.9, None))
    wp1.checker = PassingChecker()

    chunks = [tok async for tok in wp1.stream("do thing", mission_route=MissionRoute.CONVERT)]
    full = "".join(chunks)
    assert full == "exec result"
    history = await mom1.get_history()
    assert history[-1]["route"] == MissionRoute.CONVERT.value


# ── Checker.inspect ─────────────────────────────────────────────────────────────


async def test_checker_inspect_rule_failure_returns_false_with_reason():
    class _API:
        async def complete(self, msgs, **kw): return '{"ok": true}'
    _, mom2, _ = make_memories()
    checker = Checker("wp2", _API())
    ok, issues = await checker.inspect("", mom2)
    assert ok is False
    assert "empty" in issues


async def test_checker_inspect_model_says_ok():
    class _API:
        async def complete(self, msgs, **kw): return '{"ok": true}'
    _, mom2, _ = make_memories()
    checker = Checker("wp2", _API())
    ok, issues = await checker.inspect("a sufficiently long answer.", mom2)
    assert ok is True
    assert issues == ""


async def test_checker_inspect_model_says_not_ok_with_issue():
    class _API:
        async def complete(self, msgs, **kw):
            return '{"ok": false, "issues": "vague"}'
    _, mom2, _ = make_memories()
    checker = Checker("wp2", _API())
    ok, issues = await checker.inspect("a sufficiently long answer.", mom2)
    assert ok is False
    assert issues == "vague"


async def test_checker_inspect_does_not_auto_correct():
    """validate() rewrites output on failure; inspect() must not call _correct."""
    correct_calls = []

    class _API:
        async def complete(self, msgs, **kw):
            content = msgs[-1].content
            if "Issues:" in content:
                correct_calls.append(content)
                return "corrected"
            return '{"ok": false, "issues": "x"}'

    _, mom2, _ = make_memories()
    checker = Checker("wp2", _API())
    ok, issues = await checker.inspect("a sufficiently long answer.", mom2)
    assert ok is False
    assert correct_calls == []  # never called the correction prompt

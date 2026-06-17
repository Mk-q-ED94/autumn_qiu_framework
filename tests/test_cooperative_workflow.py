"""Tests for the 0.3.0 cooperative-workflow layer.

Covers the pieces wired across A1–A4 that turn the pipeline from "分工" into
"合作": capability-aware routing, A1 supervision of the A2 loop, the A4
execution archive, A4 strong-model delegation (with size threshold), the
knowledge Terr, and the master-switch config gates.
"""
import json

from autumn.core.components.agent import Agent, _inject_note
from autumn.core.components.selector import Selector
from autumn.core.components.skill import Skill
from autumn.core.components.tool import Tool, ToolParameter
from autumn.core.config import BehaviorConfig
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea
from autumn.core.memory.shared import SharedZone
from autumn.core.types import InputType, Protocol, ToolCall
from autumn.core.workspace.wp4 import WP4Mem


# ── shared mock APIs ──────────────────────────────────────────────────────────


class RecordingAPI:
    """Records every complete() call's messages and returns a fixed response."""

    def __init__(self, response="ok"):
        self.response = response
        self.calls: list[list] = []
        self.last_usage = None

    async def complete(self, messages, **kwargs):
        self.calls.append(list(messages))
        return self.response


class ScriptedToolAPI:
    """Scripts complete_with_tools_raw; records messages so we can assert injection."""

    def __init__(self, script, protocol=Protocol.OPENAI):
        self.protocol = protocol
        self._script = list(script)
        self.seen_messages: list[list[dict]] = []
        self.last_usage = None

    async def complete_with_tools_raw(self, messages, tools, system=None, **kwargs):
        # Deep-ish copy so later mutation doesn't rewrite what we recorded.
        self.seen_messages.append([dict(m) for m in messages])
        if not self._script:
            return "done", []
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


# ── 1. capability-aware Selector ──────────────────────────────────────────────


async def test_selector_injects_capability_digest_into_llm_prompt():
    api = RecordingAPI(response='{"type":"task","task_type":"code","confidence":0.9}')
    digest = "Loaded capability domains:\n- web: HTTP fetch"
    sel = Selector(api, capability_provider=lambda: digest)
    # An input that bypasses every heuristic so the LLM path runs.
    await sel.classify("please integrate the third-party billing module end to end")
    system_prompt = api.calls[0][0].content
    assert "web: HTTP fetch" in system_prompt


async def test_selector_without_provider_keeps_base_prompt():
    api = RecordingAPI(response='{"type":"mission","confidence":0.9}')
    sel = Selector(api)
    await sel.classify("walk me through the overall architecture in depth please")
    system_prompt = api.calls[0][0].content
    assert "Available capabilities" not in system_prompt


async def test_selector_capability_provider_failure_is_swallowed():
    api = RecordingAPI(response='{"type":"mission","confidence":0.9}')

    def boom():
        raise RuntimeError("provider down")

    sel = Selector(api, capability_provider=boom)
    result = await sel.classify("explain the tradeoffs of this design at length please")
    assert result.input_type == InputType.MISSION  # still classifies, digest skipped


# ── 2. supervise channel ──────────────────────────────────────────────────────


def test_inject_note_openai_appends_user_message():
    msgs = [{"role": "tool", "tool_call_id": "c1", "content": "r"}]
    _inject_note(msgs, "guidance here")
    assert msgs[-1] == {"role": "user", "content": "guidance here"}


def test_inject_note_anthropic_appends_text_block():
    msgs = [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "r"}]}]
    _inject_note(msgs, "steer left")
    assert msgs[-1]["content"][-1] == {"type": "text", "text": "steer left"}


def test_inject_note_hermes_appends_to_string():
    msgs = [{"role": "user", "content": "<tool_response>r</tool_response>"}]
    _inject_note(msgs, "redo step 2")
    assert msgs[-1]["content"].endswith("redo step 2")


async def test_agent_supervisor_injects_guidance_between_steps():
    tool = Tool("echo", "echo", lambda text: f"e:{text}",
                [ToolParameter("text", "string", "t")])
    api = ScriptedToolAPI(script=[
        ("", [ToolCall(id="c1", name="echo", arguments={"text": "a"})]),
        ("final", []),
    ])
    agent = Agent("T", api, tools=[tool], max_steps=4)

    seen = []

    async def supervisor(iteration, steps):
        seen.append(iteration)
        return "use the other branch"

    result = await agent.run("go", supervisor=supervisor)
    assert result == "final"
    assert seen == [0]  # supervisor invoked after the one tool-bearing step
    # The guidance reached the model on its 2nd turn.
    second_turn = api.seen_messages[1]
    assert any(
        m.get("role") == "user" and "A1 supervisor" in str(m.get("content"))
        for m in second_turn
    )


async def test_agent_supervisor_none_is_noop():
    tool = Tool("echo", "echo", lambda text: f"e:{text}",
                [ToolParameter("text", "string", "t")])
    api = ScriptedToolAPI(script=[
        ("", [ToolCall(id="c1", name="echo", arguments={"text": "a"})]),
        ("final", []),
    ])
    agent = Agent("T", api, tools=[tool], max_steps=4)
    result = await agent.run("go")  # no supervisor
    assert result == "final"


# ── 3. WP4 execution archive ──────────────────────────────────────────────────


def _make_wp4(api=None, **kw) -> WP4Mem:
    shared = SharedZone(DictBackend())
    zones = {"shared": shared}
    audit = MemoryArea("wp4", DictBackend())
    return WP4Mem(api, audit, zones=zones, **kw)


async def test_record_execution_summary_writes_to_shared():
    wp4 = _make_wp4()
    entry = await wp4.record_execution_summary("wp2", "build X", "X built")
    assert entry is not None
    history = await wp4._resolve("shared").get_history()
    assert history
    assert history[-1].content["source"] == "wp2"
    assert history[-1].content["output"] == "X built"
    assert "execution_summary" in history[-1].tags


async def test_record_execution_summary_skips_empty_output():
    wp4 = _make_wp4()
    entry = await wp4.record_execution_summary("wp3", "hi", "   ")
    assert entry is None
    assert not await wp4._resolve("shared").get_history()


# ── 4. A4 cognitive delegation + threshold ────────────────────────────────────


def test_cognitive_api_no_delegation_returns_local():
    local = RecordingAPI()
    wp4 = _make_wp4(local)  # no delegation_api
    assert wp4._cognitive_api(0) is local
    assert wp4._cognitive_api(99999) is local


def test_cognitive_api_delegates_when_above_threshold():
    local, strong = RecordingAPI(), RecordingAPI()
    wp4 = _make_wp4(local, delegation_api=strong, delegation_threshold=2000)
    # Size unknown (0) → always delegate; large → delegate.
    assert wp4._cognitive_api(0) is strong
    assert wp4._cognitive_api(5000) is strong


def test_cognitive_api_stays_local_below_threshold():
    local, strong = RecordingAPI(), RecordingAPI()
    wp4 = _make_wp4(local, delegation_api=strong, delegation_threshold=2000)
    # A small, measured op stays on the cheap local model.
    assert wp4._cognitive_api(100) is local


async def test_project_discussion_always_delegates_regardless_of_size():
    local, strong = RecordingAPI(response="A description."), RecordingAPI(response="A description.")
    from autumn.core.memory.project import ProjectMemory
    projects = ProjectMemory(DictBackend())
    shared = SharedZone(DictBackend())
    wp4 = WP4Mem(
        local, MemoryArea("wp4", DictBackend()),
        zones={"shared": shared}, projects=projects,
        delegation_api=strong, delegation_threshold=100000,  # huge threshold
    )
    await wp4.draft_description("tiny", "p1")
    # Project discussion bypasses the threshold → the strong model was used.
    assert strong.calls and not local.calls


# ── 5. knowledge Terr ─────────────────────────────────────────────────────────


def test_knowledge_terr_structure():
    from autumn.builtin import knowledge_terr
    terr = knowledge_terr()
    assert terr.name == "knowledge"
    names = {s.name for s in terr.skills}
    assert names == {"web_search", "fetch_document", "knowledge_base_query"}
    # Every skill is stamped with the domain identity.
    assert all(s.source_terr == "knowledge" for s in terr.skills)


async def test_knowledge_base_query_uses_recall_fn():
    from autumn.builtin import knowledge_terr

    async def recall_fn(query, k):
        return f"recalled<{query}>[{k}]"

    terr = knowledge_terr(recall_fn=recall_fn)
    kb = next(s for s in terr.skills if s.name == "knowledge_base_query")
    out = await kb.execute(query="deploy target", k="3")
    assert out == "recalled<deploy target>[3]"


async def test_knowledge_base_query_without_store_is_graceful():
    from autumn.builtin import knowledge_terr
    terr = knowledge_terr()  # no recall_fn
    kb = next(s for s in terr.skills if s.name == "knowledge_base_query")
    out = await kb.execute(query="anything")
    assert "unavailable" in out.lower()


async def test_wp4_research_unavailable_without_provider():
    wp4 = _make_wp4(RecordingAPI())
    out = await wp4.research("what is X")
    assert "unavailable" in out.lower()
    assert not wp4.can_research


# ── 6. master-switch config gates ─────────────────────────────────────────────


def test_master_switch_off_disables_every_feature():
    b = BehaviorConfig(
        cooperative_workflow=False,
        a1_task_planning=True,
        a1_supervision=True,
        archive_executions=True,
        a4_delegate_to_a1=True,
        a4_knowledge_terr=True,
        a3_lite_skills=["recall"],
    )
    assert b.task_planning_on is False
    assert b.supervision_on is False
    assert b.archive_on is False
    assert b.delegate_on is False
    assert b.knowledge_terr_on is False
    assert b.lite_skills_on() == []


def test_master_switch_on_respects_individual_flags():
    b = BehaviorConfig(
        cooperative_workflow=True,
        a1_task_planning=True,
        a1_supervision=False,
        a3_lite_skills=["recall", "remember"],
    )
    assert b.task_planning_on is True
    assert b.supervision_on is False
    assert b.lite_skills_on() == ["recall", "remember"]


def test_cooperative_flags_parse_from_env(monkeypatch):
    monkeypatch.setenv("COOPERATIVE_WORKFLOW", "false")
    monkeypatch.setenv("A1_SUPERVISION", "true")
    monkeypatch.setenv("A4_DELEGATION_THRESHOLD", "500")
    monkeypatch.setenv("A4_KNOWLEDGE_TERR", "yes")
    b = BehaviorConfig.from_env()
    assert b.cooperative_workflow is False
    assert b.a1_supervision is True
    assert b.a4_delegation_threshold == 500
    assert b.a4_knowledge_terr is True
    # Master off overrides the individual flags via the gates.
    assert b.supervision_on is False
    assert b.knowledge_terr_on is False

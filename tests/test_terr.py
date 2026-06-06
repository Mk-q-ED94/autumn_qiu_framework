"""Tests for the Terr (域) capability domain abstraction."""
import pytest

from autumn.core.components.terr import Terr
from autumn.core.components.tool import Tool, ToolParameter
from autumn.core.components.skill import Skill
from autumn.core.components.agent import Agent
from autumn.core.types import Protocol, ToolCall


# ── construction & repr ───────────────────────────────────────────────────────


def test_terr_stores_name_and_description():
    terr = Terr("search", "Web search and retrieval")
    assert terr.name == "search"
    assert terr.description == "Web search and retrieval"


def test_terr_defaults_to_empty_lists():
    terr = Terr("empty", "nothing here")
    assert terr.tools == []
    assert terr.skills == []
    assert terr.mcps == []


def test_terr_stores_tools_skills():
    t = Tool("fetch", "fetch a url", lambda url: url, [ToolParameter("url", "string", "url")])
    s = Skill("summarize", "summarize text", lambda **kw: "summary")
    terr = Terr("content", "content ops", tools=[t], skills=[s])
    assert len(terr.tools) == 1
    assert len(terr.skills) == 1
    assert terr.tools[0].name == "fetch"
    assert terr.skills[0].name == "summarize"


def test_terr_repr_shows_counts():
    t = Tool("t1", "", lambda: None, [])
    s = Skill("s1", "", lambda **kw: None)
    terr = Terr("demo", "demo domain", tools=[t, t], skills=[s])
    r = repr(terr)
    assert "demo" in r
    assert "tools=2" in r
    assert "skills=1" in r
    assert "mcps=0" in r


def test_terr_does_not_mutate_input_lists():
    tools = [Tool("t", "", lambda: None, [])]
    skills = [Skill("s", "", lambda **kw: None)]
    terr = Terr("x", "x", tools=tools, skills=skills)
    tools.append(Tool("extra", "", lambda: None, []))
    assert len(terr.tools) == 1  # terr has its own copy


# ── Agent integration ─────────────────────────────────────────────────────────


def _make_tool(name: str) -> Tool:
    return Tool(name, f"{name} tool", lambda **kw: name, [])


def _make_skill(name: str) -> Skill:
    return Skill(name, f"{name} skill", lambda **kw: name)


class _MockAPI:
    """Minimal mock that satisfies Agent.run without real model calls."""
    protocol = Protocol.OPENAI

    def __init__(self, responses):
        self._responses = list(responses)
        self.captured_messages: list[list[dict]] = []
        self.captured_systems: list[str] = []

    async def complete_with_tools_raw(self, messages, tools, system=None, **kwargs):
        self.captured_messages.append(list(messages))
        # For OpenAI the system is in messages[0]; for Anthropic it's the kwarg.
        if system:
            self.captured_systems.append(system)
        elif messages and messages[0].get("role") == "system":
            self.captured_systems.append(messages[0]["content"])
        else:
            self.captured_systems.append("")
        if not self._responses:
            return "[done]", []
        return self._responses.pop(0)

    def build_assistant_tool_message(self, text, tool_calls):
        return {"role": "assistant", "content": text,
                "tool_calls": [{"id": tc.id, "type": "function",
                                "function": {"name": tc.name, "arguments": "{}"}}
                               for tc in tool_calls]}

    def build_tool_result_messages(self, tool_calls, results):
        return [{"role": "tool", "tool_call_id": tc.id, "content": r}
                for tc, r in zip(tool_calls, results)]


def test_agent_terrs_tools_and_skills_flattened():
    t = _make_tool("fetch")
    s = _make_skill("summarize")
    terr = Terr("content", "content domain", tools=[t], skills=[s])
    agent = Agent("a", _MockAPI([]), terrs=[terr])
    assert "fetch" in agent.tools
    assert "summarize" in agent.skills


def test_agent_multiple_terrs_merged():
    terr1 = Terr("search", "search", tools=[_make_tool("brave")])
    terr2 = Terr("code", "code", tools=[_make_tool("run_python")], skills=[_make_skill("review_pr")])
    agent = Agent("a", _MockAPI([]), terrs=[terr1, terr2])
    assert "brave" in agent.tools
    assert "run_python" in agent.tools
    assert "review_pr" in agent.skills


def test_agent_explicit_tools_override_terr_same_name():
    """Explicit tools/skills registered after terr expansion win on same name."""
    terr_tool = Tool("fetch", "old", lambda **kw: "old", [])
    override_tool = Tool("fetch", "new", lambda **kw: "new", [])
    terr = Terr("x", "x", tools=[terr_tool])
    agent = Agent("a", _MockAPI([]), tools=[override_tool], terrs=[terr])
    assert agent.tools["fetch"].description == "new"


def test_agent_terr_skill_collision_raises():
    """A skill in one terr and a tool with the same name from another → error."""
    terr1 = Terr("t1", "t1", tools=[_make_tool("search")])
    terr2 = Terr("t2", "t2", skills=[_make_skill("search")])
    with pytest.raises(ValueError, match="search"):
        Agent("a", _MockAPI([]), terrs=[terr1, terr2])


def test_agent_terr_vs_explicit_collision_raises():
    terr = Terr("x", "x", skills=[_make_skill("lookup")])
    tool = _make_tool("lookup")
    with pytest.raises(ValueError, match="lookup"):
        Agent("a", _MockAPI([]), tools=[tool], terrs=[terr])


def test_agent_without_terrs_unchanged():
    """Agent with no terrs behaves exactly as before."""
    t = _make_tool("noop")
    agent = Agent("a", _MockAPI([]), tools=[t])
    assert "noop" in agent.tools
    assert agent._terr_descriptions == {}


def test_agent_terr_descriptions_stored():
    terr = Terr("search", "Web search and retrieval", tools=[_make_tool("brave")])
    agent = Agent("a", _MockAPI([]), terrs=[terr])
    assert agent._terr_descriptions == {"search": "Web search and retrieval"}


async def test_agent_terr_domain_lines_in_system_prompt():
    """Domain descriptions must appear in the system prompt sent to the model."""
    terr = Terr("search", "Web search and retrieval")
    api = _MockAPI([("[done]", [])])
    agent = Agent("a", api, terrs=[terr])
    await agent.run("test")
    system = api.captured_systems[0]
    assert "search" in system
    assert "Web search and retrieval" in system
    assert "Loaded capability domains" in system


async def test_agent_no_terrs_no_domain_section_in_system_prompt():
    api = _MockAPI([("[done]", [])])
    agent = Agent("a", api)
    await agent.run("test")
    assert "Loaded capability domains" not in api.captured_systems[0]


async def test_agent_invokes_tool_from_terr():
    called = {}

    async def fetcher(**kwargs):
        called.update(kwargs)
        return "content"

    tool = Tool("fetch", "fetch", fetcher, [ToolParameter("url", "string", "url")])
    terr = Terr("web", "web ops", tools=[tool])
    api = _MockAPI([
        ("calling", [ToolCall(id="t1", name="fetch", arguments={"url": "https://example.com"})]),
        ("done", []),
    ])
    agent = Agent("a", api, terrs=[terr])
    result = await agent.run("fetch example.com")
    assert result == "done"
    assert called == {"url": "https://example.com"}


async def test_agent_invokes_skill_from_terr():
    captured = {}

    async def handler(**kwargs):
        captured.update(kwargs)
        return "summary"

    skill = Skill("summarize", "summarize", handler,
                  [ToolParameter("text", "string", "text")])
    terr = Terr("content", "content", skills=[skill])
    api = _MockAPI([
        ("calling", [ToolCall(id="s1", name="summarize", arguments={"text": "long"})]),
        ("done", []),
    ])
    agent = Agent("a", api, terrs=[terr])
    result = await agent.run("summarize this")
    assert result == "done"
    assert captured == {"text": "long"}


# ── PluginLoader terr support ─────────────────────────────────────────────────


def test_plugin_loader_register_terr_and_retrieve():
    from autumn.plugins.loader import PluginLoader

    terr = Terr("search", "search domain", tools=[_make_tool("brave")])
    loader = PluginLoader()
    loader.register_terr(terr)
    assert loader.get_terr("search") is terr


def test_plugin_loader_all_terrs():
    from autumn.plugins.loader import PluginLoader

    t1 = Terr("search", "search")
    t2 = Terr("code", "code")
    loader = PluginLoader()
    loader.register_terr(t1)
    loader.register_terr(t2)
    terrs = loader.all_terrs()
    assert set(terrs.keys()) == {"search", "code"}


def test_plugin_loader_terrs_isolated_from_regular_registry():
    """Terrs don't pollute the flat tool/skill registry and vice-versa."""
    from autumn.plugins.loader import PluginLoader

    loader = PluginLoader()
    tool = _make_tool("brave")
    loader.register("brave", tool)

    terr = Terr("search", "search", tools=[_make_tool("fetch")])
    loader.register_terr(terr)

    assert "search" not in loader.all()  # terr name not in flat registry
    assert loader.get_terr("search") is terr
    assert "brave" not in loader.all_terrs()

import json
import pytest
from autumn.core.components import Tool, ToolParameter, Selector, Checker, Skill
from autumn.core.components.checker import _rule_check
from autumn.core.components.mcp_bridge import _schema_to_parameters
from autumn.core.types import InputType, TaskType, SelectorResult


def test_tool_openai_schema():
    tool = Tool(
        name="search",
        description="Find a thing",
        fn=lambda q: q,
        parameters=[ToolParameter(name="q", type="string", description="query")],
    )
    schema = tool.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "search"
    assert "q" in schema["function"]["parameters"]["properties"]
    assert schema["function"]["parameters"]["required"] == ["q"]


def test_tool_anthropic_schema():
    tool = Tool(
        name="search",
        description="Find a thing",
        fn=lambda q=None: q,
        parameters=[ToolParameter(name="q", type="string", description="query", required=False)],
    )
    schema = tool.to_anthropic_schema()
    assert schema["name"] == "search"
    assert schema["input_schema"]["required"] == []


def test_skill_openai_schema():
    skill = Skill(
        name="summarize",
        description="Summarize text",
        handler=lambda ctx: ctx,
        parameters=[ToolParameter(name="text", type="string", description="text to summarize")],
    )
    schema = skill.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "summarize"
    assert "text" in schema["function"]["parameters"]["properties"]
    assert schema["function"]["parameters"]["required"] == ["text"]


def test_skill_anthropic_schema():
    skill = Skill("greet", "Greet someone", lambda ctx: ctx,
                  [ToolParameter(name="name", type="string", description="who")])
    schema = skill.to_anthropic_schema()
    assert schema["name"] == "greet"
    assert schema["input_schema"]["required"] == ["name"]


def test_skill_default_empty_parameters():
    skill = Skill("ping", "no-arg trigger", lambda ctx: "pong")
    schema = skill.to_openai_schema()
    assert schema["function"]["parameters"]["properties"] == {}
    assert schema["function"]["parameters"]["required"] == []


async def test_skill_execute_receives_context():
    captured = {}

    async def handler(ctx):
        captured.update(ctx)
        return "ok"

    skill = Skill("cap", "captures", handler)
    result = await skill.execute({"a": 1, "b": 2})
    assert result == "ok"
    assert captured == {"a": 1, "b": 2}


async def test_tool_call_async():
    async def double(n: int) -> int:
        return n * 2
    tool = Tool("double", "double n", double, [ToolParameter(name="n", type="integer", description="n")])
    assert await tool.call(n=3) == 6


async def test_tool_call_sync_wraps_to_async():
    tool = Tool("inc", "inc n", lambda n: n + 1, [ToolParameter(name="n", type="integer", description="n")])
    assert await tool.call(n=5) == 6


def test_rule_check_empty():
    assert _rule_check("") == "output is empty"
    assert _rule_check("   ") == "output is empty"


def test_rule_check_too_short():
    assert _rule_check("hi") == "output is too short"


def test_rule_check_pass():
    assert _rule_check("This is a sufficiently long answer.") == ""


def test_schema_to_parameters_required_flag():
    schema = {
        "type": "object",
        "properties": {
            "q": {"type": "string", "description": "query"},
            "n": {"type": "integer", "description": "count"},
        },
        "required": ["q"],
    }
    params = _schema_to_parameters(schema)
    by_name = {p.name: p for p in params}
    assert by_name["q"].required is True
    assert by_name["n"].required is False
    assert by_name["q"].type == "string"


def test_schema_to_parameters_empty():
    assert _schema_to_parameters({}) == []
    assert _schema_to_parameters({"type": "object"}) == []


# ── Selector ──────────────────────────────────────────────────────────────────


class _MockAPI:
    def __init__(self, response: str):
        self._response = response

    async def complete(self, messages, **kwargs) -> str:
        return self._response


async def test_selector_classify_task_with_subtype():
    api = _MockAPI('{"type": "task", "task_type": "code", "confidence": 0.95}')
    selector = Selector(api)
    result = await selector.classify("Fix the bug in my Python function")
    assert result.input_type == InputType.TASK
    assert result.task_type == TaskType.CODE
    assert result.confidence == pytest.approx(0.95)


async def test_selector_classify_mission_no_task_type():
    api = _MockAPI('{"type": "mission", "confidence": 0.88}')
    selector = Selector(api)
    result = await selector.classify("What is the meaning of life?")
    assert result.input_type == InputType.MISSION
    assert result.task_type is None


async def test_selector_classify_task_general_subtype():
    api = _MockAPI('{"type": "task", "task_type": "general", "confidence": 0.80}')
    selector = Selector(api)
    result = await selector.classify("Do the thing")
    assert result.input_type == InputType.TASK
    assert result.task_type == TaskType.GENERAL


async def test_selector_classify_unknown_task_type_defaults_to_general():
    api = _MockAPI('{"type": "task", "task_type": "drawing", "confidence": 0.70}')
    selector = Selector(api)
    result = await selector.classify("Draw a picture")
    assert result.task_type == TaskType.GENERAL


async def test_selector_classify_bad_json_returns_mission():
    api = _MockAPI("not json at all")
    selector = Selector(api)
    result = await selector.classify("something")
    assert result.input_type == InputType.MISSION
    assert result.task_type is None


async def test_selector_classify_and_maybe_confirm_returns_selector_result():
    api = _MockAPI('{"type": "task", "task_type": "search", "confidence": 0.92}')
    selector = Selector(api)
    result = await selector.classify_and_maybe_confirm("Find info about X", interaction=None)
    assert isinstance(result, SelectorResult)
    assert result.input_type == InputType.TASK
    assert result.task_type == TaskType.SEARCH


async def test_selector_all_task_types():
    for tt in ("code", "search", "write", "data", "general"):
        api = _MockAPI(json.dumps({"type": "task", "task_type": tt, "confidence": 0.9}))
        selector = Selector(api)
        result = await selector.classify("x")
        assert result.task_type == TaskType(tt)

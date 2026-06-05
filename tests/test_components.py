from autumn.core.components import Tool, ToolParameter, Selector, Checker, Skill
from autumn.core.components.checker import _rule_check
from autumn.core.components.mcp_bridge import _schema_to_parameters


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

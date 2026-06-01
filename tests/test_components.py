from autumn.core.components import Tool, ToolParameter, Selector, Checker
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

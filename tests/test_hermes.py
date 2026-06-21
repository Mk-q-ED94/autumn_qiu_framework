"""Tests for HermesAPIInterface — XML tool-call parsing and message building."""
import json
import pytest
from unittest.mock import AsyncMock, patch

from autumn.core.api.hermes import HermesAPIInterface
from autumn.core.api.interfaces import A1, A2, A3
from autumn.core.config import ModelConfig
from autumn.core.types import Protocol, ToolCall


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def hermes():
    return HermesAPIInterface(
        api_key="test-key",
        base_url="http://localhost:11434",
        model="hermes3:8b",
    )


@pytest.fixture
def hermes_config():
    return ModelConfig(
        api_key="test-key",
        base_url="http://localhost:11434",
        model="hermes3:8b",
        protocol=Protocol.HERMES,
    )


_SIMPLE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"},
            },
            "required": ["city"],
        },
    },
}


# ── protocol / construction ────────────────────────────────────────────────────

def test_hermes_uses_openai_protocol(hermes):
    assert hermes.protocol == Protocol.OPENAI


def test_a1_returns_hermes_interface(hermes_config):
    api = A1(hermes_config)
    assert isinstance(api, HermesAPIInterface)


def test_a2_returns_hermes_interface(hermes_config):
    assert isinstance(A2(hermes_config), HermesAPIInterface)


def test_a3_returns_hermes_interface(hermes_config):
    assert isinstance(A3(hermes_config), HermesAPIInterface)


def test_a1_openai_returns_base_interface():
    cfg = ModelConfig("key", "https://api.openai.com", "gpt-4o", Protocol.OPENAI)
    from autumn.core.api.base import ModelAPIInterface
    api = A1(cfg)
    assert type(api) is ModelAPIInterface


# ── schema conversion ──────────────────────────────────────────────────────────

def test_schemas_to_hermes_json_openai_format(hermes):
    result = json.loads(hermes._schemas_to_hermes_json([_SIMPLE_TOOL]))
    assert result[0]["name"] == "get_weather"
    assert "parameters" in result[0]


def test_schemas_to_hermes_json_anthropic_format(hermes):
    anthropic_tool = {
        "name": "search",
        "description": "Web search",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }
    result = json.loads(hermes._schemas_to_hermes_json([anthropic_tool]))
    assert result[0]["name"] == "search"
    assert result[0]["parameters"]["properties"]["query"]["type"] == "string"


# ── <thinking> extraction ──────────────────────────────────────────────────────

def test_extract_thinking_strips_tags(hermes):
    text = "<thinking>internal reasoning here</thinking>\nFinal answer."
    clean, thinking = hermes._extract_thinking(text)
    assert "thinking" not in clean.lower()
    assert "Final answer." in clean
    assert "internal reasoning here" in thinking


def test_extract_thinking_no_tags(hermes):
    text = "Plain text response."
    clean, thinking = hermes._extract_thinking(text)
    assert clean == text
    assert thinking == ""


# ── <tool_call> parsing ────────────────────────────────────────────────────────

def test_extract_tool_calls_single(hermes):
    response = 'Sure!\n<tool_call>\n{"name": "get_weather", "arguments": {"city": "Paris"}}\n</tool_call>'
    text, calls = hermes._extract_tool_calls(response)
    assert len(calls) == 1
    assert calls[0].name == "get_weather"
    assert calls[0].arguments == {"city": "Paris"}
    assert "Sure!" in text
    assert "<tool_call>" not in text


def test_extract_tool_calls_multiple(hermes):
    response = (
        '<tool_call>\n{"name": "f1", "arguments": {"a": 1}}\n</tool_call>\n'
        '<tool_call>\n{"name": "f2", "arguments": {"b": 2}}\n</tool_call>'
    )
    _, calls = hermes._extract_tool_calls(response)
    assert len(calls) == 2
    assert calls[0].name == "f1"
    assert calls[1].name == "f2"


def test_extract_tool_calls_none(hermes):
    text, calls = hermes._extract_tool_calls("Here is the answer: 42")
    assert calls == []
    assert text == "Here is the answer: 42"


def test_extract_tool_calls_malformed_json_skipped(hermes):
    response = '<tool_call>\nnot json\n</tool_call>\nFallback text.'
    text, calls = hermes._extract_tool_calls(response)
    assert calls == []
    assert "Fallback text." in text


def test_extract_tool_calls_id_is_unique(hermes):
    response = (
        '<tool_call>\n{"name": "f1", "arguments": {}}\n</tool_call>\n'
        '<tool_call>\n{"name": "f2", "arguments": {}}\n</tool_call>'
    )
    _, calls = hermes._extract_tool_calls(response)
    assert calls[0].id != calls[1].id


# ── tool injection into system prompt ─────────────────────────────────────────

def test_inject_tools_into_existing_system(hermes):
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
    ]
    patched = hermes._inject_tools(messages, [_SIMPLE_TOOL])
    sys_msg = patched[0]
    assert sys_msg["role"] == "system"
    assert "<tools>" in sys_msg["content"]
    assert "get_weather" in sys_msg["content"]
    assert "You are helpful." in sys_msg["content"]


def test_inject_tools_creates_system_when_absent(hermes):
    messages = [{"role": "user", "content": "Hello"}]
    patched = hermes._inject_tools(messages, [_SIMPLE_TOOL])
    assert patched[0]["role"] == "system"
    assert "<tools>" in patched[0]["content"]
    assert patched[1]["role"] == "user"


def test_inject_tools_only_patches_first_system(hermes):
    messages = [
        {"role": "system", "content": "Sys1"},
        {"role": "user", "content": "Hi"},
        {"role": "system", "content": "Sys2"},  # unusual but should not be patched
    ]
    patched = hermes._inject_tools(messages, [_SIMPLE_TOOL])
    # Only first system message should have the tool preamble
    assert "<tools>" in patched[0]["content"]
    assert "<tools>" not in patched[2]["content"]


# ── build_assistant_tool_message ──────────────────────────────────────────────

def test_build_assistant_tool_message(hermes):
    calls = [ToolCall(id="call_abc", name="get_weather", arguments={"city": "Tokyo"})]
    msg = hermes.build_assistant_tool_message("Checking weather.", calls)
    assert msg["role"] == "assistant"
    assert "Checking weather." in msg["content"]
    assert "<tool_call>" in msg["content"]
    assert "get_weather" in msg["content"]
    assert "Tokyo" in msg["content"]


def test_build_assistant_tool_message_no_text(hermes):
    calls = [ToolCall(id="call_x", name="search", arguments={"q": "hello"})]
    msg = hermes.build_assistant_tool_message("", calls)
    assert msg["content"].startswith("<tool_call>")


# ── build_tool_result_messages ────────────────────────────────────────────────

def test_build_tool_result_messages(hermes):
    calls = [ToolCall(id="call_1", name="get_weather", arguments={})]
    msgs = hermes.build_tool_result_messages(calls, ["Sunny, 22°C"])
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert "<tool_response>" in msgs[0]["content"]
    assert "get_weather" in msgs[0]["content"]
    assert "Sunny, 22°C" in msgs[0]["content"]


def test_build_tool_result_messages_multiple_calls(hermes):
    calls = [
        ToolCall(id="c1", name="f1", arguments={}),
        ToolCall(id="c2", name="f2", arguments={}),
    ]
    msgs = hermes.build_tool_result_messages(calls, ["r1", "r2"])
    assert len(msgs) == 1  # packed into one user turn
    content = msgs[0]["content"]
    assert content.count("<tool_response>") == 2
    assert "r1" in content and "r2" in content


# ── complete_with_tools_raw (mocked HTTP) ─────────────────────────────────────

@pytest.mark.asyncio
async def test_complete_with_tools_raw_tool_call(hermes):
    tool_response_body = {
        "choices": [{"message": {"role": "assistant",
                                  "content": '<tool_call>\n{"name": "get_weather", "arguments": {"city": "Berlin"}}\n</tool_call>'}}]
    }
    with patch.object(hermes, "_post_with_retry", new=AsyncMock(return_value=tool_response_body)):
        messages = [{"role": "user", "content": "What's the weather in Berlin?"}]
        text, calls = await hermes.complete_with_tools_raw(messages, [_SIMPLE_TOOL])
    assert len(calls) == 1
    assert calls[0].name == "get_weather"
    assert calls[0].arguments == {"city": "Berlin"}


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{}]}])
async def test_complete_with_tools_raw_tolerates_empty_body(hermes, body):
    # Some OpenAI-compatible servers return {} or {"choices": []} under load.
    # That must degrade to "no text, no tool calls", not raise KeyError/IndexError
    # into the ReAct loop (the base class guards this; the Hermes override now too).
    with patch.object(hermes, "_post_with_retry", new=AsyncMock(return_value=body)):
        text, calls = await hermes.complete_with_tools_raw(
            [{"role": "user", "content": "hi"}], [_SIMPLE_TOOL],
        )
    assert text == ""
    assert calls == []


@pytest.mark.asyncio
async def test_complete_with_tools_raw_final_answer(hermes):
    tool_response_body = {
        "choices": [{"message": {"role": "assistant",
                                  "content": "The weather in Berlin is 15°C and cloudy."}}]
    }
    with patch.object(hermes, "_post_with_retry", new=AsyncMock(return_value=tool_response_body)):
        messages = [{"role": "user", "content": "Hello"}]
        text, calls = await hermes.complete_with_tools_raw(messages, [_SIMPLE_TOOL])
    assert calls == []
    assert "15°C" in text


@pytest.mark.asyncio
async def test_complete_with_tools_raw_strips_thinking(hermes):
    body = {
        "choices": [{"message": {"content": "<thinking>Let me reason.</thinking>\nThe answer is 42."}}]
    }
    with patch.object(hermes, "_post_with_retry", new=AsyncMock(return_value=body)):
        text, calls = await hermes.complete_with_tools_raw(
            [{"role": "user", "content": "What is 6*7?"}], []
        )
    assert "42" in text
    assert "<thinking>" not in text
    assert "Let me reason." in hermes.last_thinking


@pytest.mark.asyncio
async def test_complete_with_tools_raw_system_injected(hermes):
    captured: list[dict] = []

    async def fake_post(endpoint, payload):
        captured.append(payload)
        return {"choices": [{"message": {"content": "Done."}}]}

    with patch.object(hermes, "_post_with_retry", new=fake_post):
        await hermes.complete_with_tools_raw(
            [{"role": "user", "content": "hi"}],
            [_SIMPLE_TOOL],
            system="You are a bot.",
        )

    messages_sent = captured[0]["messages"]
    system_msg = next(m for m in messages_sent if m["role"] == "system")
    assert "<tools>" in system_msg["content"]
    assert "You are a bot." in system_msg["content"]


# ── round-trip: full ReAct single step ────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_react_step(hermes):
    """Simulate one ReAct iteration: tool call → result → final answer."""
    call_step = {
        "choices": [{"message": {"content":
            '<tool_call>\n{"name": "get_weather", "arguments": {"city": "Rome"}}\n</tool_call>'
        }}]
    }
    final_step = {
        "choices": [{"message": {"content": "Rome is 28°C and sunny."}}]
    }

    call_count = 0

    async def mock_post(_endpoint, _payload):
        nonlocal call_count
        call_count += 1
        return call_step if call_count == 1 else final_step

    with patch.object(hermes, "_post_with_retry", new=mock_post):
        # Step 1: model requests a tool
        msgs = [{"role": "user", "content": "Weather in Rome?"}]
        text1, calls = await hermes.complete_with_tools_raw(msgs, [_SIMPLE_TOOL])
        assert len(calls) == 1

        # Build next turn
        msgs.append(hermes.build_assistant_tool_message(text1, calls))
        msgs.extend(hermes.build_tool_result_messages(calls, ["28°C, sunny"]))

        # Step 2: model gives final answer
        text2, calls2 = await hermes.complete_with_tools_raw(msgs, [_SIMPLE_TOOL])
        assert calls2 == []
        assert "28°C" in text2

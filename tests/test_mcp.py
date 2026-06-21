"""Tests for the MCP layer: content-block unwrap, stdio stderr drain,
request timeout, env/cwd, and tool bridge."""
import asyncio
import sys

import pytest

from autumn.core.components.mcp import MCPClient
from autumn.core.components.mcp_bridge import _unwrap_content, _make_caller, mcp_to_tools
from autumn.core.components.mcp_stdio import StdioMCPClient


# ── B1: content-block unwrap ──────────────────────────────────────────────────


def test_unwrap_text_blocks():
    blocks = [{"type": "text", "text": "Hello"}, {"type": "text", "text": "world"}]
    assert _unwrap_content(blocks) == "Hello\nworld"


def test_unwrap_image_block_summarized():
    blocks = [{"type": "image", "data": "BASE64...", "mimeType": "image/png"}]
    assert _unwrap_content(blocks) == "[image: image/png]"


def test_unwrap_image_block_without_mime():
    blocks = [{"type": "image", "data": "..."}]
    assert _unwrap_content(blocks) == "[image: image]"


def test_unwrap_resource_block():
    blocks = [{"type": "resource", "resource": {"uri": "file:///tmp/x.txt"}}]
    assert _unwrap_content(blocks) == "[resource: file:///tmp/x.txt]"


def test_unwrap_resource_block_without_uri():
    assert _unwrap_content([{"type": "resource"}]) == "[resource]"


def test_unwrap_mixed_blocks():
    blocks = [
        {"type": "text", "text": "header"},
        {"type": "image", "mimeType": "image/jpeg"},
        {"type": "text", "text": "footer"},
    ]
    assert _unwrap_content(blocks) == "header\n[image: image/jpeg]\nfooter"


def test_unwrap_empty_list_returns_empty_string():
    assert _unwrap_content([]) == ""


def test_unwrap_string_passthrough():
    assert _unwrap_content("already a string") == "already a string"


def test_unwrap_skips_empty_text_blocks():
    blocks = [{"type": "text", "text": ""}, {"type": "text", "text": "real"}]
    assert _unwrap_content(blocks) == "real"


def test_unwrap_unknown_block_type_falls_back_to_repr():
    blocks = [{"type": "custom", "payload": 42}]
    assert "custom" in _unwrap_content(blocks)


def test_unwrap_non_dict_block_stringified():
    assert _unwrap_content(["plain string in list"]) == "plain string in list"


# ── _make_caller integrates the unwrap ────────────────────────────────────────


class _FakeClient(MCPClient):
    def __init__(self, response):
        self.response = response
        self.received_args = None

    async def connect(self): pass
    async def disconnect(self): pass
    async def list_tools(self): return []

    async def call_tool(self, name, arguments):
        self.received_args = (name, arguments)
        return self.response


async def test_make_caller_unwraps_text_block():
    client = _FakeClient([{"type": "text", "text": "result"}])
    caller = _make_caller(client, "search")
    out = await caller(q="hi")
    assert out == "result"
    assert client.received_args == ("search", {"q": "hi"})


async def test_make_caller_unwraps_multi_block():
    client = _FakeClient([
        {"type": "text", "text": "line1"},
        {"type": "text", "text": "line2"},
    ])
    out = await _make_caller(client, "x")()
    assert out == "line1\nline2"


async def test_mcp_to_tools_preserves_enum_in_schema():
    """Tools built from MCP specs should expose enum/items to the model."""
    class _Lister(_FakeClient):
        async def list_tools(self):
            return [{
                "name": "weather",
                "description": "Get weather",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "city"},
                        "unit": {"type": "string", "enum": ["c", "f"], "description": "unit"},
                    },
                    "required": ["city"],
                },
            }]

    tools = await mcp_to_tools(_Lister(None))
    assert len(tools) == 1
    schema = tools[0].to_openai_schema()
    props = schema["function"]["parameters"]["properties"]
    assert props["unit"]["enum"] == ["c", "f"]
    assert schema["function"]["parameters"]["required"] == ["city"]


# ── StdioMCPClient: stderr drain, timeout, env/cwd ────────────────────────────


def _python_script(body: str) -> list[str]:
    """Build argv that runs an inline Python script."""
    return [sys.executable, "-u", "-c", body]


_SERVER_TEMPLATE = """
import json, sys{extra_import}
def emit(obj): sys.stdout.write(json.dumps(obj) + "\\n"); sys.stdout.flush()

for line in sys.stdin:
    if not line.strip(): continue
    msg = json.loads(line)
    method = msg.get("method")
    if "id" not in msg:
        continue  # notification, no reply
    if method == "initialize":
        emit({{"jsonrpc": "2.0", "id": msg["id"], "result": {{"protocolVersion": "2024-11-05"}}}})
    elif method == "tools/list":
        emit({{"jsonrpc": "2.0", "id": msg["id"], "result": {{"tools": [
            {{"name": "echo", "description": "echo", "inputSchema": {{"type":"object","properties":{{"msg":{{"type":"string"}}}}}}}}
        ]}}}})
    elif method == "tools/call":
        text = msg["params"]["arguments"].get("msg", "")
        {extra_logic}
        emit({{"jsonrpc": "2.0", "id": msg["id"], "result": {{"content": [{{"type":"text","text": text}}]}}}})
"""


def _server_script(extra_import="", extra_logic="pass"):
    return _SERVER_TEMPLATE.format(extra_import=extra_import, extra_logic=extra_logic)


async def test_stdio_initialize_and_list_tools():
    client = StdioMCPClient(_python_script(_server_script()))
    await client.connect()
    try:
        tools = await client.list_tools()
        assert tools[0]["name"] == "echo"
    finally:
        await client.disconnect()


async def test_stdio_call_tool_returns_content_blocks():
    """call_tool itself stays low-level; the bridge does the unwrap."""
    client = StdioMCPClient(_python_script(_server_script()))
    await client.connect()
    try:
        result = await client.call_tool("echo", {"msg": "ping"})
        assert result == [{"type": "text", "text": "ping"}]
    finally:
        await client.disconnect()


async def test_stdio_end_to_end_through_bridge_returns_plain_text():
    """The real fix — agent gets clean text, not Python repr."""
    client = StdioMCPClient(_python_script(_server_script()))
    await client.connect()
    try:
        tools = await mcp_to_tools(client)
        tool = next(t for t in tools if t.name == "echo")
        out = await tool.call(msg="hello agent")
        assert out == "hello agent"  # not "[{'type': 'text', 'text': 'hello agent'}]"
    finally:
        await client.disconnect()


async def test_stdio_drains_stderr_into_tail_buffer():
    """Server writes to stderr; tail buffer should capture recent lines."""
    body = _server_script(
        extra_import="\nimport sys; sys.stderr.write('boot\\n'); sys.stderr.flush()",
    )
    client = StdioMCPClient(_python_script(body))
    await client.connect()
    try:
        # Trigger a request to give stderr time to be drained
        await client.list_tools()
        # Give the background drain task a moment to scoop the line
        for _ in range(10):
            if client._stderr_tail:
                break
            await asyncio.sleep(0.05)
        assert "boot" in "\n".join(client._stderr_tail)
    finally:
        await client.disconnect()


async def test_stdio_request_timeout_raises_with_stderr_tail():
    """Server that never replies to tools/call should trigger a timeout
    with stderr context included."""
    body = """
import json, sys
sys.stderr.write("server alive\\n"); sys.stderr.flush()
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("method") == "initialize":
        sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":{"protocolVersion":"2024-11-05"}}) + "\\n")
        sys.stdout.flush()
    elif msg.get("method") == "tools/list":
        # Sit forever (the timeout test target)
        import time
        time.sleep(60)
"""
    client = StdioMCPClient(_python_script(body), timeout=0.5)
    await client.connect()
    try:
        with pytest.raises(asyncio.TimeoutError) as exc_info:
            await client.list_tools()
        msg = str(exc_info.value)
        assert "tools/list" in msg
        assert "0.5s" in msg
        # stderr tail must be in the error message
        assert "server alive" in msg
    finally:
        await client.disconnect()


async def test_stdio_passes_env_to_subprocess():
    body = """
import json, sys, os
TOKEN = os.environ.get("AUTUMN_TEST_TOKEN", "missing")
for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg: continue
    if msg.get("method") == "initialize":
        sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":{"protocolVersion":"2024-11-05"}}) + "\\n")
    elif msg.get("method") == "tools/call":
        sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":{"content":[{"type":"text","text":TOKEN}]}}) + "\\n")
    sys.stdout.flush()
"""
    client = StdioMCPClient(_python_script(body), env={"AUTUMN_TEST_TOKEN": "secret123"})
    await client.connect()
    try:
        result = await client.call_tool("echo", {})
        assert result == [{"type": "text", "text": "secret123"}]
    finally:
        await client.disconnect()


async def test_stdio_passes_cwd_to_subprocess(tmp_path):
    body = """
import json, sys, os
CWD = os.getcwd()
for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg: continue
    if msg.get("method") == "initialize":
        sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":{"protocolVersion":"2024-11-05"}}) + "\\n")
    elif msg.get("method") == "tools/call":
        sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":{"content":[{"type":"text","text":CWD}]}}) + "\\n")
    sys.stdout.flush()
"""
    client = StdioMCPClient(_python_script(body), cwd=str(tmp_path))
    await client.connect()
    try:
        result = await client.call_tool("echo", {})
        text = result[0]["text"]
        # On macOS /private/var/folders symlinks tmp paths — accept any path that
        # resolves to the same thing.
        import os
        assert os.path.realpath(text) == os.path.realpath(str(tmp_path))
    finally:
        await client.disconnect()


async def test_stdio_disconnect_cancels_stderr_task():
    client = StdioMCPClient(_python_script(_server_script()))
    await client.connect()
    task = client._stderr_task
    assert task is not None and not task.done()
    await client.disconnect()
    assert client._stderr_task is None
    assert task.done()


async def test_stdio_connect_reaps_subprocess_on_init_failure():
    # A server that never answers initialize → connect() times out. The failed
    # handshake must not strand a zombie subprocess + drain task (the caller only
    # tracks the client after a *successful* connect, so connect owns cleanup).
    body = "import sys\nfor _line in sys.stdin:\n    pass\n"
    client = StdioMCPClient(_python_script(body), timeout=0.5)
    with pytest.raises(TimeoutError):
        await client.connect()
    assert client._proc is None          # subprocess reaped
    assert client._stderr_task is None   # drain task cancelled


async def test_stdio_connect_refuses_double_connect():
    # Re-connecting without disconnecting would orphan the first subprocess.
    client = StdioMCPClient(_python_script(_server_script()))
    await client.connect()
    try:
        with pytest.raises(RuntimeError):
            await client.connect()
    finally:
        await client.disconnect()


async def test_stdio_unexpected_close_surfaces_stderr_tail():
    """Server crashes during a request — the error should include stderr context."""
    body = """
import json, sys
sys.stderr.write("about to crash\\n"); sys.stderr.flush()
for line in sys.stdin:
    msg = json.loads(line)
    if msg.get("method") == "initialize":
        sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":{"protocolVersion":"2024-11-05"}}) + "\\n")
        sys.stdout.flush()
    elif msg.get("method") == "tools/list":
        sys.stderr.write("dying now\\n"); sys.stderr.flush()
        sys.exit(1)
"""
    client = StdioMCPClient(_python_script(body), timeout=2.0)
    await client.connect()
    try:
        with pytest.raises(RuntimeError) as exc_info:
            await client.list_tools()
        msg = str(exc_info.value)
        assert "closed connection" in msg
        # Wait a beat to ensure stderr drain got the final lines
        await asyncio.sleep(0.1)
        # Either "about to crash" or "dying now" should be in the tail
        assert "crash" in msg or "dying" in msg
    finally:
        await client.disconnect()

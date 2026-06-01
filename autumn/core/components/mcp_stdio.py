import asyncio
import json
from typing import Any

from .mcp import MCPClient


class StdioMCPClient(MCPClient):
    """MCP client over stdio transport using JSON-RPC 2.0.

    Starts a subprocess and communicates over its stdin/stdout with
    newline-delimited JSON messages, matching the MCP stdio spec.
    """

    _PROTOCOL_VERSION = "2024-11-05"

    def __init__(self, command: list[str]):
        self.command = command
        self._proc: asyncio.subprocess.Process | None = None
        self._req_id = 0

    async def connect(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await self._initialize()

    async def disconnect(self) -> None:
        if self._proc:
            self._proc.stdin.close()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._proc.kill()
            self._proc = None

    async def list_tools(self) -> list[dict]:
        result = await self._request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = await self._request("tools/call", {"name": name, "arguments": arguments})
        return result.get("content", [])

    # ── internals ─────────────────────────────────────────────────────────────

    async def _initialize(self) -> None:
        await self._request("initialize", {
            "protocolVersion": self._PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "autumn", "version": "0.1.0"},
        })
        await self._notify("notifications/initialized", {})

    async def _request(self, method: str, params: dict) -> dict:
        self._req_id += 1
        req_id = self._req_id
        await self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        return await self._recv(req_id)

    async def _notify(self, method: str, params: dict) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _send(self, msg: dict) -> None:
        assert self._proc and self._proc.stdin
        self._proc.stdin.write((json.dumps(msg) + "\n").encode())
        await self._proc.stdin.drain()

    async def _recv(self, expected_id: int) -> dict:
        assert self._proc and self._proc.stdout
        while True:
            raw = await self._proc.stdout.readline()
            if not raw:
                raise RuntimeError("MCP server closed connection unexpectedly")
            msg = json.loads(raw.decode().strip())
            if msg.get("id") == expected_id:
                if "error" in msg:
                    raise RuntimeError(f"MCP error: {msg['error']}")
                return msg.get("result", {})

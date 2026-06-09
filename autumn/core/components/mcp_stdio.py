import asyncio
import json
from collections import deque
from typing import Any

from .mcp import MCPClient

_DEFAULT_TIMEOUT = 30.0
_STDERR_TAIL_LINES = 20


class StdioMCPClient(MCPClient):
    """MCP client over stdio transport using JSON-RPC 2.0.

    Starts a subprocess and communicates over its stdin/stdout with
    newline-delimited JSON messages, matching the MCP stdio spec.

    Parameters
    ----------
    command : list[str]
        Argv for the subprocess, e.g. ``["uvx", "mcp-server-fetch"]``.
    env : dict[str, str] | None
        Extra environment variables. Merged on top of the parent process env;
        if you want a clean environment, pre-build it and pass everything here.
    cwd : str | None
        Working directory for the subprocess.
    timeout : float
        Per-request timeout in seconds. ``initialize`` and ``tools/call`` are
        both bounded by this; raises :class:`asyncio.TimeoutError` on expiry,
        with the recent stderr tail included in the message.
    """

    _PROTOCOL_VERSION = "2024-11-05"

    def __init__(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ):
        self.command = command
        self.env = env
        self.cwd = cwd
        self.timeout = timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._req_id = 0
        self._stderr_tail: deque[str] = deque(maxlen=_STDERR_TAIL_LINES)
        self._stderr_task: asyncio.Task | None = None

    async def connect(self) -> None:
        # Inherit parent env and overlay caller-provided vars so PATH etc. work.
        proc_env: dict[str, str] | None = None
        if self.env is not None:
            import os
            proc_env = {**os.environ, **self.env}

        self._proc = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=proc_env,
            cwd=self.cwd,
        )
        # Drain stderr in the background so the pipe never fills up (which
        # would deadlock the server) and so we can surface the tail on errors.
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        await self._initialize()

    async def disconnect(self) -> None:
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._stderr_task = None

        if self._proc:
            if self._proc.stdin and not self._proc.stdin.is_closing():
                self._proc.stdin.close()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
            self._proc = None

    async def list_tools(self) -> list[dict]:
        result = await self._request("tools/list", {})
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = await self._request("tools/call", {"name": name, "arguments": arguments})
        return result.get("content", [])

    # ── internals ─────────────────────────────────────────────────────────────

    async def _drain_stderr(self) -> None:
        """Continuously read stderr into a rolling tail buffer."""
        assert self._proc and self._proc.stderr
        while True:
            line = await self._proc.stderr.readline()
            if not line:
                return
            try:
                decoded = line.decode("utf-8", errors="replace").rstrip()
            except Exception:  # noqa: BLE001
                continue
            if decoded:
                self._stderr_tail.append(decoded)

    def _stderr_snapshot(self) -> str:
        return "\n".join(self._stderr_tail) if self._stderr_tail else "(no stderr captured)"

    async def _initialize(self) -> None:
        await self._request("initialize", {
            "protocolVersion": self._PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "autumn", "version": "0.2.0"},
        })
        await self._notify("notifications/initialized", {})

    async def _request(self, method: str, params: dict) -> dict:
        self._req_id += 1
        req_id = self._req_id
        await self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        try:
            return await asyncio.wait_for(self._recv(req_id), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            raise asyncio.TimeoutError(
                f"MCP request '{method}' timed out after {self.timeout}s. "
                f"Recent stderr:\n{self._stderr_snapshot()}"
            ) from exc

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
                raise RuntimeError(
                    "MCP server closed connection unexpectedly. "
                    f"Recent stderr:\n{self._stderr_snapshot()}"
                )
            msg = json.loads(raw.decode().strip())
            if msg.get("id") == expected_id:
                if "error" in msg:
                    raise RuntimeError(f"MCP error: {msg['error']}")
                return msg.get("result", {})

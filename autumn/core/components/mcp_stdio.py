import asyncio
import json
import os
from collections import deque
from typing import Any

from .mcp import MCPClient

_DEFAULT_TIMEOUT = 30.0
_STDERR_TAIL_LINES = 20


class MCPConnectionLost(RuntimeError):
    """The MCP subprocess died or closed its pipes mid-request.

    A subclass of :class:`RuntimeError` (so existing ``except RuntimeError``
    handlers still catch it), raised specifically when the *transport* fails —
    EOF on stdout, a broken stdin pipe, or a request issued with no live
    subprocess. It is distinct from the plain ``RuntimeError`` a valid
    ``{"error": ...}`` JSON-RPC reply raises: only a *transport* loss is
    eligible for auto-reconnect, never a server-reported tool error.
    """


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
    max_reconnect_attempts : int
        When > 0, a request that fails because the transport died
        (:class:`MCPConnectionLost`) or timed out triggers up to this many
        respawn-and-retry attempts with exponential backoff, transparently
        recovering from a crashed server. ``0`` (default) keeps the original
        behaviour: the error propagates immediately and the client stays dead.
    reconnect_backoff_base, reconnect_backoff_cap : float
        Backoff schedule for reconnect attempts: the *n*-th attempt waits
        ``min(cap, base * 2**(n-1))`` seconds before respawning.

    """

    _PROTOCOL_VERSION = "2024-11-05"

    def __init__(
        self,
        command: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        max_reconnect_attempts: int = 0,
        reconnect_backoff_base: float = 0.5,
        reconnect_backoff_cap: float = 8.0,
    ):
        self.command = command
        self.env = env
        self.cwd = cwd
        self.timeout = timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._req_id = 0
        self._stderr_tail: deque[str] = deque(maxlen=_STDERR_TAIL_LINES)
        self._stderr_task: asyncio.Task | None = None
        # Reconnect/backoff configuration + state.
        self._max_reconnect_attempts = max(0, max_reconnect_attempts)
        self._reconnect_backoff_base = reconnect_backoff_base
        self._reconnect_backoff_cap = reconnect_backoff_cap
        self._reconnect_lock = asyncio.Lock()
        # True only while (re)connecting, so the in-flight initialize handshake
        # can't itself trigger a reconnect (which would recurse).
        self._connecting = False
        # Set by an intentional disconnect() so a late in-flight request can't
        # resurrect the subprocess after the caller asked to close it.
        self._closed = False
        # Bumped on every successful (re)spawn. Lets a second coroutine that
        # raced into reconnect notice the link was already restored.
        self._generation = 0

    async def connect(self) -> None:
        # Idempotency guard: re-connecting without disconnecting would orphan the
        # previous subprocess + drain task with no handle to reap them.
        if self._proc is not None:
            raise RuntimeError("StdioMCPClient is already connected; disconnect() first")
        self._closed = False
        await self._spawn_and_initialize()

    async def _spawn_and_initialize(self) -> None:
        """Spawn the subprocess and run the initialize handshake.

        Shared by ``connect()`` and the reconnect path. On any handshake failure
        it reaps the just-spawned process so no zombie is stranded, then re-raises.
        """
        # Inherit parent env and overlay caller-provided vars so PATH etc. work.
        proc_env: dict[str, str] | None = None
        if self.env is not None:
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
        self._connecting = True
        try:
            await self._initialize()
        except BaseException:
            # A failed handshake (timeout, server crash on init) must not leave a
            # zombie subprocess behind — callers only track the client after a
            # successful connect, so we own the cleanup here. _teardown() is
            # null-safe and idempotent.
            self._connecting = False
            await self._teardown()
            raise
        self._connecting = False
        self._generation += 1

    async def disconnect(self) -> None:
        # Intentional close: latch _closed so any late, in-flight request that
        # loses the transport won't auto-reconnect behind the caller's back.
        self._closed = True
        await self._teardown()

    async def _teardown(self) -> None:
        """Reap the subprocess + drain task. Null-safe and idempotent."""
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
            except TimeoutError:
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
        """Issue a request, transparently reconnecting on transport loss.

        With reconnect disabled (the default) this is a thin pass-through to
        :meth:`_request_once`. With it enabled, a :class:`MCPConnectionLost` or
        timeout respawns the server (exponential backoff) and retries, up to
        ``max_reconnect_attempts`` times, before giving up and propagating —
        which lets the caller degrade to "this Terr is unavailable".
        """
        attempts = 0
        while True:
            seen_gen = self._generation
            try:
                return await self._request_once(method, params)
            except (MCPConnectionLost, TimeoutError):
                attempts += 1
                if (
                    self._connecting
                    or self._closed
                    or self._max_reconnect_attempts == 0
                    or attempts > self._max_reconnect_attempts
                ):
                    raise
                await self._reconnect(attempts, seen_gen)

    async def _reconnect(self, attempt: int, seen_gen: int) -> None:
        """Best-effort single reconnect with backoff, serialized across callers.

        Never raises: a respawn that fails leaves the client disconnected, and
        the caller's retry will surface :class:`MCPConnectionLost` again to
        either re-attempt or exhaust the budget.
        """
        delay = min(
            self._reconnect_backoff_cap,
            self._reconnect_backoff_base * (2 ** (attempt - 1)),
        )
        async with self._reconnect_lock:
            if self._closed:
                return
            # Another coroutine already brought the link back while we waited for
            # the lock — reuse its fresh subprocess instead of churning again.
            if self._generation != seen_gen:
                return
            if delay > 0:
                await asyncio.sleep(delay)
            await self._teardown()
            try:
                await self._spawn_and_initialize()
            except Exception:  # noqa: BLE001
                pass  # stay down; the request retry decides whether to re-attempt

    async def _request_once(self, method: str, params: dict) -> dict:
        self._req_id += 1
        req_id = self._req_id
        await self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        try:
            return await asyncio.wait_for(self._recv(req_id), timeout=self.timeout)
        except TimeoutError as exc:
            raise TimeoutError(
                f"MCP request '{method}' timed out after {self.timeout}s. "
                f"Recent stderr:\n{self._stderr_snapshot()}",
            ) from exc

    async def _notify(self, method: str, params: dict) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def _send(self, msg: dict) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdin.is_closing():
            raise MCPConnectionLost("MCP subprocess stdin is unavailable (server not connected).")
        try:
            proc.stdin.write((json.dumps(msg) + "\n").encode())
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise MCPConnectionLost("MCP subprocess stdin pipe broke mid-send.") from exc

    async def _recv(self, expected_id: int) -> dict:
        proc = self._proc
        if proc is None or proc.stdout is None:
            raise MCPConnectionLost("MCP subprocess stdout is unavailable (server not connected).")
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                raise MCPConnectionLost(
                    "MCP server closed connection unexpectedly. "
                    f"Recent stderr:\n{self._stderr_snapshot()}",
                )
            msg = json.loads(raw.decode().strip())
            if msg.get("id") == expected_id:
                if "error" in msg:
                    raise RuntimeError(f"MCP error: {msg['error']}")
                return msg.get("result", {})

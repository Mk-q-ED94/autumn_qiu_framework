import asyncio
import json
from typing import AsyncIterator
import httpx
from ..types import Message, Protocol, Role, ToolCall


_RETRY_DELAYS = [1, 2, 4]  # seconds between the 3 attempts


class ModelAPIInterface:
    """Base model API interface. Supports OpenAI and Anthropic protocols,
    with retry-on-failure, streaming, and tool-use for ReAct agents.
    """

    def __init__(self, api_key: str, base_url: str, model: str, protocol: Protocol):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.protocol = protocol
        self._client: httpx.AsyncClient | None = None

    # ── client ────────────────────────────────────────────────────────────────

    def _build_headers(self) -> dict:
        if self.protocol == Protocol.OPENAI:
            return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(headers=self._build_headers(), timeout=120.0)
        return self._client

    # ── request building ──────────────────────────────────────────────────────

    def _build_request(self, messages: list[Message], **kwargs) -> tuple[str, dict]:
        if self.protocol == Protocol.OPENAI:
            payload = {
                "model": self.model,
                "messages": [{"role": m.role.value, "content": m.content} for m in messages],
                **kwargs,
            }
            return f"{self.base_url}/v1/chat/completions", payload

        system_content = None
        chat_messages = []
        for m in messages:
            if m.role == Role.SYSTEM:
                system_content = m.content
            else:
                chat_messages.append({"role": m.role.value, "content": m.content})

        payload: dict = {
            "model": self.model,
            "messages": chat_messages,
            "max_tokens": kwargs.pop("max_tokens", 4096),
            **kwargs,
        }
        if system_content:
            payload["system"] = system_content
        return f"{self.base_url}/v1/messages", payload

    # ── completion ────────────────────────────────────────────────────────────

    async def complete(self, messages: list[Message], **kwargs) -> str:
        endpoint, payload = self._build_request(messages, **kwargs)
        client = self._get_client()
        last_error: Exception | None = None
        for attempt, delay in enumerate([0] + _RETRY_DELAYS):
            if delay:
                await asyncio.sleep(delay)
            try:
                resp = await client.post(endpoint, json=payload)
                resp.raise_for_status()
                return self._extract_content(resp.json())
            except httpx.HTTPError as e:
                last_error = e
        raise last_error  # type: ignore[misc]

    def _extract_content(self, data: dict) -> str:
        if self.protocol == Protocol.OPENAI:
            return data["choices"][0]["message"]["content"]
        return next(b["text"] for b in data["content"] if b["type"] == "text")

    # ── streaming ─────────────────────────────────────────────────────────────

    async def stream_complete(self, messages: list[Message], **kwargs) -> AsyncIterator[str]:
        endpoint, payload = self._build_request(messages, **kwargs)
        payload["stream"] = True
        client = self._get_client()
        async with client.stream("POST", endpoint, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                chunk = self._parse_stream_line(line)
                if chunk is not None:
                    yield chunk

    def _parse_stream_line(self, line: str) -> str | None:
        if not line.startswith("data: "):
            return None
        data = line[6:]
        if data == "[DONE]":
            return None
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            return None
        if self.protocol == Protocol.OPENAI:
            delta = obj.get("choices", [{}])[0].get("delta", {})
            return delta.get("content")
        # Anthropic
        if obj.get("type") == "content_block_delta":
            return obj.get("delta", {}).get("text")
        return None

    # ── tool-use (for ReAct agents) ───────────────────────────────────────────

    async def complete_with_tools(
        self,
        messages: list[Message],
        tools: list[dict],
        **kwargs,
    ) -> tuple[str | None, list[ToolCall]]:
        """Returns (text, []) for final answers or (None, tool_calls) for tool invocations."""
        endpoint, payload = self._build_request(messages, **kwargs)
        payload["tools"] = tools
        if self.protocol == Protocol.ANTHROPIC:
            payload.setdefault("max_tokens", 4096)

        client = self._get_client()
        last_error: Exception | None = None
        for delay in [0] + _RETRY_DELAYS:
            if delay:
                await asyncio.sleep(delay)
            try:
                resp = await client.post(endpoint, json=payload)
                resp.raise_for_status()
                return self._parse_tool_response(resp.json())
            except httpx.HTTPError as e:
                last_error = e
        raise last_error  # type: ignore[misc]

    def _parse_tool_response(self, data: dict) -> tuple[str | None, list[ToolCall]]:
        if self.protocol == Protocol.OPENAI:
            msg = data["choices"][0]["message"]
            raw_calls = msg.get("tool_calls") or []
            if raw_calls:
                calls = [
                    ToolCall(
                        id=tc["id"],
                        name=tc["function"]["name"],
                        arguments=json.loads(tc["function"]["arguments"]),
                    )
                    for tc in raw_calls
                ]
                return None, calls
            return msg.get("content", ""), []

        # Anthropic
        tool_calls = []
        text_parts = []
        for block in data.get("content", []):
            if block["type"] == "tool_use":
                tool_calls.append(ToolCall(id=block["id"], name=block["name"], arguments=block["input"]))
            elif block["type"] == "text":
                text_parts.append(block["text"])
        if tool_calls:
            return None, tool_calls
        return "".join(text_parts), []

    def make_tool_result_messages(
        self, tool_calls: list[ToolCall], results: list[str]
    ) -> list[dict]:
        """Build the follow-up messages to append after tool execution."""
        if self.protocol == Protocol.OPENAI:
            return [
                {"role": "tool", "tool_call_id": tc.id, "content": result}
                for tc, result in zip(tool_calls, results)
            ]
        # Anthropic: single user message containing all tool_result blocks
        return [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": tc.id, "content": result}
                    for tc, result in zip(tool_calls, results)
                ],
            }
        ]

    # ── lifecycle ─────────────────────────────────────────────────────────────

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

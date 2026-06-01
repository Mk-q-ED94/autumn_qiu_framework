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

    @property
    def _completion_endpoint(self) -> str:
        if self.protocol == Protocol.OPENAI:
            return f"{self.base_url}/v1/chat/completions"
        return f"{self.base_url}/v1/messages"

    # ── request building ──────────────────────────────────────────────────────

    def _build_request(self, messages: list[Message], **kwargs) -> tuple[str, dict]:
        if self.protocol == Protocol.OPENAI:
            payload = {
                "model": self.model,
                "messages": [{"role": m.role.value, "content": m.content} for m in messages],
                **kwargs,
            }
            return self._completion_endpoint, payload

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
        return self._completion_endpoint, payload

    # ── retry ────────────────────────────────────────────────────────────────

    async def _post_with_retry(self, endpoint: str, payload: dict) -> dict:
        client = self._get_client()
        last_error: Exception | None = None
        for delay in [0] + _RETRY_DELAYS:
            if delay:
                await asyncio.sleep(delay)
            try:
                resp = await client.post(endpoint, json=payload)
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPError as e:
                last_error = e
        raise last_error  # type: ignore[misc]

    # ── completion ────────────────────────────────────────────────────────────

    async def complete(self, messages: list[Message], **kwargs) -> str:
        endpoint, payload = self._build_request(messages, **kwargs)
        data = await self._post_with_retry(endpoint, payload)
        return self._extract_content(data)

    def _extract_content(self, data: dict) -> str:
        if self.protocol == Protocol.OPENAI:
            return data["choices"][0]["message"]["content"] or ""
        return next((b["text"] for b in data["content"] if b["type"] == "text"), "")

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
        if obj.get("type") == "content_block_delta":
            return obj.get("delta", {}).get("text")
        return None

    # ── tool-use (for ReAct agents) ───────────────────────────────────────────

    async def complete_with_tools(
        self,
        messages: list[Message],
        tools: list[dict],
        **kwargs,
    ) -> tuple[str, list[ToolCall]]:
        """Convenience wrapper over complete_with_tools_raw for simple Message input."""
        if self.protocol == Protocol.OPENAI:
            raw = [{"role": m.role.value, "content": m.content} for m in messages]
            return await self.complete_with_tools_raw(raw, tools, **kwargs)

        system = None
        raw = []
        for m in messages:
            if m.role == Role.SYSTEM:
                system = m.content
            else:
                raw.append({"role": m.role.value, "content": m.content})
        return await self.complete_with_tools_raw(raw, tools, system=system, **kwargs)

    async def complete_with_tools_raw(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str | None = None,
        **kwargs,
    ) -> tuple[str, list[ToolCall]]:
        """Like complete_with_tools but accepts pre-formatted provider-specific messages.

        Returns (text, tool_calls). Both may be non-empty (text = reasoning, tool_calls = actions).
        Empty tool_calls means the model is done.
        """
        if self.protocol == Protocol.OPENAI:
            payload = {"model": self.model, "messages": messages, "tools": tools, **kwargs}
        else:
            payload = {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "max_tokens": kwargs.pop("max_tokens", 4096),
                **kwargs,
            }
            if system:
                payload["system"] = system

        data = await self._post_with_retry(self._completion_endpoint, payload)
        return self._parse_tool_response(data)

    def _parse_tool_response(self, data: dict) -> tuple[str, list[ToolCall]]:
        if self.protocol == Protocol.OPENAI:
            msg = data["choices"][0]["message"]
            text = msg.get("content") or ""
            raw_calls = msg.get("tool_calls") or []
            calls = [
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=json.loads(tc["function"]["arguments"]),
                )
                for tc in raw_calls
            ]
            return text, calls

        # Anthropic
        tool_calls = []
        text_parts = []
        for block in data.get("content", []):
            if block["type"] == "tool_use":
                tool_calls.append(ToolCall(id=block["id"], name=block["name"], arguments=block["input"]))
            elif block["type"] == "text":
                text_parts.append(block["text"])
        return "".join(text_parts), tool_calls

    def build_assistant_tool_message(self, text: str, tool_calls: list[ToolCall]) -> dict:
        """Build the assistant turn that issued tool_calls (in provider format)."""
        if self.protocol == Protocol.OPENAI:
            return {
                "role": "assistant",
                "content": text or None,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in tool_calls
                ],
            }
        # Anthropic
        content: list[dict] = []
        if text:
            content.append({"type": "text", "text": text})
        for tc in tool_calls:
            content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
        return {"role": "assistant", "content": content}

    def build_tool_result_messages(
        self, tool_calls: list[ToolCall], results: list[str]
    ) -> list[dict]:
        """Build the tool-result follow-up messages (in provider format)."""
        if self.protocol == Protocol.OPENAI:
            return [
                {"role": "tool", "tool_call_id": tc.id, "content": result}
                for tc, result in zip(tool_calls, results)
            ]
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

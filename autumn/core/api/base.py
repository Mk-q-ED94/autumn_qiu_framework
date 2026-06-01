import httpx
from ..types import Message, Protocol, Role


class ModelAPIInterface:
    """Base model API interface. Supports OpenAI and Anthropic protocols."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        protocol: Protocol,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.protocol = protocol
        self._client: httpx.AsyncClient | None = None

    def _build_headers(self) -> dict:
        if self.protocol == Protocol.OPENAI:
            return {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=self._build_headers(),
                timeout=120.0,
            )
        return self._client

    def _build_request(self, messages: list[Message], **kwargs) -> tuple[str, dict]:
        if self.protocol == Protocol.OPENAI:
            payload = {
                "model": self.model,
                "messages": [
                    {"role": m.role.value, "content": m.content} for m in messages
                ],
                **kwargs,
            }
            return f"{self.base_url}/v1/chat/completions", payload

        # Anthropic: system message is a top-level field, not in messages array
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

    async def complete(self, messages: list[Message], **kwargs) -> str:
        endpoint, payload = self._build_request(messages, **kwargs)
        client = self._get_client()
        response = await client.post(endpoint, json=payload)
        response.raise_for_status()
        return self._extract_content(response.json())

    def _extract_content(self, data: dict) -> str:
        if self.protocol == Protocol.OPENAI:
            return data["choices"][0]["message"]["content"]
        return data["content"][0]["text"]

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

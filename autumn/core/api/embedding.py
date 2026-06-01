import asyncio
import httpx
from ..config import EmbeddingConfig


class EmbeddingInterface:
    """HTTP client for OpenAI-compatible /v1/embeddings endpoint.

    Used by VectorMemoryArea to encode text before storing or searching.
    Separate from A1/A2/A3 because embedding models have a different API
    path and are usually different models (e.g. text-embedding-3-small).
    """

    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    async def embed(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.post(
            f"{self.config.base_url.rstrip('/')}/v1/embeddings",
            json={"model": self.config.model, "input": texts},
        )
        resp.raise_for_status()
        items = sorted(resp.json()["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in items]

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

from collections import OrderedDict

import httpx
from ..config import EmbeddingConfig

_DEFAULT_CACHE_SIZE = 512


class EmbeddingInterface:
    """HTTP client for OpenAI-compatible /v1/embeddings endpoint.

    Used by VectorMemoryArea to encode text before storing or searching.
    Separate from A1/A2/A3 because embedding models have a different API
    path and are usually different models (e.g. text-embedding-3-small).

    Single-text ``embed`` calls go through a bounded LRU cache: the same query
    text (a recall, a checker's semantic lookup, a repeated index) maps to the
    same vector for a fixed model, so a cache hit skips the embeddings round
    trip entirely. Set ``cache_size=0`` to disable.
    """

    def __init__(self, config: EmbeddingConfig, cache_size: int = _DEFAULT_CACHE_SIZE):
        self.config = config
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = max(0, cache_size)

    async def embed(self, text: str) -> list[float]:
        if self._cache_size:
            cached = self._cache.get(text)
            if cached is not None:
                self._cache.move_to_end(text)
                return cached
        result = (await self.embed_batch([text]))[0]
        if self._cache_size:
            self._cache[text] = result
            self._cache.move_to_end(text)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return result

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

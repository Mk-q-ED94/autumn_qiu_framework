from typing import Any

from ..base import MemoryBackend
from .dict_backend import DictBackend


class HybridBackend(MemoryBackend):
    """Two-layer memory: short-term (in-memory) + long-term (persistent).

    Read strategy:  short-term first; on miss, load from long-term and cache it.
    Write strategy: always write to both layers by default.
                    Use set(..., persist=False) to write only to short-term.
    Session reset:  call clear_session() to drop short-term without touching long-term.
    """

    def __init__(self, long_term: MemoryBackend):
        self._short = DictBackend()
        self._long = long_term

    async def get(self, key: str) -> Any:
        value = await self._short.get(key)
        if value is not None:
            return value
        value = await self._long.get(key)
        if value is not None:
            await self._short.set(key, value)  # warm the cache
        return value

    async def set(self, key: str, value: Any, persist: bool = True) -> None:  # type: ignore[override]
        await self._short.set(key, value)
        if persist:
            await self._long.set(key, value)

    async def delete(self, key: str) -> None:
        await self._short.delete(key)
        await self._long.delete(key)

    async def keys(self) -> list[str]:
        short = set(await self._short.keys())
        long = set(await self._long.keys())
        return list(short | long)

    async def clear(self) -> None:
        await self._short.clear()
        await self._long.clear()

    async def clear_session(self) -> None:
        """Drop short-term (session) memory, preserve long-term."""
        await self._short.clear()

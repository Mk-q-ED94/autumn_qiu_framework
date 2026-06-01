from typing import Any
from ..base import MemoryBackend


class DictBackend(MemoryBackend):
    """In-memory dict backend. For development and testing only."""

    def __init__(self):
        self._store: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self._store.get(key)

    async def set(self, key: str, value: Any) -> None:
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def keys(self) -> list[str]:
        return list(self._store.keys())

    async def clear(self) -> None:
        self._store.clear()

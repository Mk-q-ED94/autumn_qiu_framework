from abc import ABC, abstractmethod
from typing import Any

_HISTORY_KEY = "history"
_MAX_HISTORY = 50


class MemoryBackend(ABC):
    """Abstract storage backend. Implement to plug in a concrete storage system."""

    @abstractmethod
    async def get(self, key: str) -> Any: ...

    @abstractmethod
    async def set(self, key: str, value: Any) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...

    @abstractmethod
    async def keys(self) -> list[str]: ...

    @abstractmethod
    async def clear(self) -> None: ...


class MemoryArea:
    """A named, namespaced area backed by a MemoryBackend."""

    def __init__(self, name: str, backend: MemoryBackend):
        self.name = name
        self._backend = backend

    def _k(self, key: str) -> str:
        return f"{self.name}:{key}"

    async def get(self, key: str) -> Any:
        return await self._backend.get(self._k(key))

    async def set(self, key: str, value: Any) -> None:
        await self._backend.set(self._k(key), value)

    async def delete(self, key: str) -> None:
        await self._backend.delete(self._k(key))

    async def keys(self) -> list[str]:
        prefix = f"{self.name}:"
        return [
            k.removeprefix(prefix)
            for k in await self._backend.keys()
            if k.startswith(prefix)
        ]

    async def clear(self) -> None:
        for key in await self.keys():
            await self.delete(key)

    # ── history helpers ──────────────────────────────────────────────────────

    async def append_history(self, entry: dict, max_entries: int = _MAX_HISTORY) -> None:
        """Append a turn record to history, capped at max_entries (most recent kept)."""
        history = await self.get(_HISTORY_KEY) or []
        history.append(entry)
        if len(history) > max_entries:
            history = history[-max_entries:]
        await self.set(_HISTORY_KEY, history)

    async def get_history(self) -> list[dict]:
        return await self.get(_HISTORY_KEY) or []

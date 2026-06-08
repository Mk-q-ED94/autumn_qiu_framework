from .base import MemoryArea, MemoryBackend, _MAX_HISTORY


class SharedZone(MemoryArea):
    """Shared memory zone between Mom2 and Mom3. Both have read/write access."""

    def __init__(
        self,
        backend: MemoryBackend,
        history_limit: int = _MAX_HISTORY,
        decay_half_life: float | None = None,
    ):
        super().__init__(
            "shared", backend,
            history_limit=history_limit,
            decay_half_life=decay_half_life,
        )

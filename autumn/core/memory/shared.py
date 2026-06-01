from .base import MemoryArea, MemoryBackend


class SharedZone(MemoryArea):
    """Shared memory zone between Mom2 and Mom3. Both have read/write access."""

    def __init__(self, backend: MemoryBackend):
        super().__init__("shared", backend)

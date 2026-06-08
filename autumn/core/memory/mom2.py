from .base import MemoryArea, MemoryBackend
from .shared import SharedZone


class Mom2(MemoryArea):
    """Task workspace memory (WP2).

    Access: private area + shared zone with Mom3.
    Cannot access Mom1.
    """

    def __init__(self, backend: MemoryBackend, shared: SharedZone, history_limit: int = 50):
        super().__init__("mom2", backend, history_limit=history_limit)
        self.shared = shared

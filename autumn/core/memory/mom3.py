from .base import MemoryArea, MemoryBackend
from .shared import SharedZone


class Mom3(MemoryArea):
    """Mission workspace memory (WP3).

    Access: private area + shared zone with Mom2.
    Cannot access Mom1.
    """

    def __init__(self, backend: MemoryBackend, shared: SharedZone, history_limit: int = 50):
        super().__init__("mom3", backend, history_limit=history_limit)
        self.shared = shared

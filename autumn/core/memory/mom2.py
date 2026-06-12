from .access import Mom1Requester
from .base import MemoryArea, MemoryBackend
from .shared import SharedZone


class Mom2(Mom1Requester, MemoryArea):
    """Task workspace memory (WP2).

    Access: private area + shared zone with Mom3. Cannot read Mom1 directly, but
    may *request* read access via :meth:`request_mom1` — A1 adjudicates and A4
    mediates a restricted answer (see :mod:`autumn.core.memory.access`).
    """

    def __init__(
        self,
        backend: MemoryBackend,
        shared: SharedZone,
        history_limit: int = 50,
        decay_half_life: float | None = None,
        fourd_enabled: bool = False,
    ):
        super().__init__(
            "mom2", backend, history_limit=history_limit,
            decay_half_life=decay_half_life, fourd_enabled=fourd_enabled,
        )
        self.shared = shared

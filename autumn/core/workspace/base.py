from abc import ABC, abstractmethod
from ..api.base import ModelAPIInterface
from ..memory.base import MemoryArea


class WorkspaceBase(ABC):
    def __init__(self, api: ModelAPIInterface, memory: MemoryArea):
        self.api = api
        self.memory = memory
        self.checker = None

    @abstractmethod
    async def process(self, input_data: str) -> str: ...

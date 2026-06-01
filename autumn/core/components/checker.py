from ..memory.base import MemoryArea


class Checker:
    """Output validator for a workspace. Coordinates with the workspace's memory."""

    def __init__(self, workspace_id: str, api_interface):
        self.workspace_id = workspace_id
        self.api = api_interface

    async def validate(self, output: str, memory: MemoryArea) -> tuple[bool, str]:
        """Validates output against memory context.

        Returns (is_valid, output).
        Passes through by default — validation logic to be defined per workspace.
        """
        # TODO: implement validation logic once checker requirements are confirmed
        return True, output

from .tool import Tool
from .skill import Skill
from ..api.base import ModelAPIInterface
from ..types import Message, Role


class Agent:
    """Autonomous executor with access to tools and skills."""

    def __init__(
        self,
        name: str,
        api: ModelAPIInterface,
        tools: list[Tool] | None = None,
        skills: list[Skill] | None = None,
    ):
        self.name = name
        self.api = api
        self.tools: dict[str, Tool] = {t.name: t for t in (tools or [])}
        self.skills: dict[str, Skill] = {s.name: s for s in (skills or [])}

    async def run(self, task: str, memory=None) -> str:
        messages = [
            Message(
                role=Role.SYSTEM,
                content=f"You are {self.name}, an autonomous agent in the Autumn framework.",
            ),
            Message(role=Role.USER, content=task),
        ]
        return await self.api.complete(messages)

from enum import Enum
from pydantic import BaseModel


class Protocol(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    role: Role
    content: str


class InputType(str, Enum):
    TASK = "task"
    MISSION = "mission"


class MissionRoute(str, Enum):
    DIRECT = "direct"    # A3 answers the mission directly
    CONVERT = "convert"  # A3 converts mission to task → WP2

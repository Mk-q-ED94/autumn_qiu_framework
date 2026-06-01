from dataclasses import dataclass
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
    DIRECT = "direct"
    CONVERT = "convert"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class SelectorResult:
    input_type: InputType
    confidence: float

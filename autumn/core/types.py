from dataclasses import dataclass
from enum import Enum


class Protocol(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    HERMES = "hermes"


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    role: Role
    content: str


class InputType(str, Enum):
    TASK = "task"
    MISSION = "mission"


class MissionRoute(str, Enum):
    DIRECT = "direct"
    CONVERT = "convert"


@dataclass
class WorkflowStage:
    id: str
    title: str
    detail: str
    workspace: str
    status: str = "completed"
    kind: str = "stage"   # "stage" = workflow step, "tool" = an agent tool call


@dataclass
class AgentStep:
    """One tool/skill invocation inside an Agent's ReAct loop."""
    name: str
    arguments: dict
    result: str


@dataclass
class WorkflowRun:
    output: str
    input_type: InputType
    route: MissionRoute | None
    stages: list[WorkflowStage]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class SelectorResult:
    input_type: InputType
    confidence: float


@dataclass
class SearchResult:
    """Single result from a semantic vector search."""
    id: str
    text: str
    score: float       # cosine similarity in [0, 1]
    metadata: dict

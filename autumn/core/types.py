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


class TaskType(str, Enum):
    CODE = "code"
    SEARCH = "search"
    WRITE = "write"
    DATA = "data"
    GENERAL = "general"


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
    duration_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    source_terr: str | None = None
    cost_usd: float | None = None   # filled in when the slot has pricing configured
    items: list[str] | None = None  # structured detail, e.g. A1's execution plan
    # Structured collaboration identity so the client can show *who* acted and
    # *who they handed to* without parsing the (localized) title. "A1".."A4".
    agent: str | None = None
    handoff_to: str | None = None

    def __post_init__(self):
        # Derive the acting agent from the workspace 1:1 unless set explicitly,
        # so every stage — wherever it's built — carries a machine-readable actor.
        if self.agent is None:
            self.agent = {
                "WP1": "A1", "WP2": "A2", "WP3": "A3", "WP4": "A4",
            }.get(self.workspace)


@dataclass
class AgentStep:
    """One tool/skill invocation inside an Agent's ReAct loop."""

    name: str
    arguments: dict
    result: str
    duration_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    source_terr: str | None = None


@dataclass
class WorkflowRun:
    output: str
    input_type: InputType
    route: MissionRoute | None
    stages: list[WorkflowStage]
    task_type: "TaskType | None" = None
    total_cost_usd: float | None = None   # sum of per-stage cost when any slot is priced


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class SelectorResult:
    input_type: InputType
    confidence: float
    task_type: "TaskType | None" = None
    reasoning: str | None = None


@dataclass
class SearchResult:
    """Single result from a semantic vector search."""

    id: str
    text: str
    score: float       # cosine similarity in [0, 1]
    metadata: dict

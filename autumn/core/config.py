import os
from dataclasses import dataclass, field
from typing import Literal
from .types import Protocol, MissionRoute


def _to_float(value: str | None, default: float = 0.0) -> float:
    """Parse a float from an env string; fall back to ``default`` on junk/empty."""
    if value is None or not str(value).strip():
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: str | None, default: int) -> int:
    """Parse an int from an env string; fall back to ``default`` on junk/empty."""
    if value is None or not str(value).strip():
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value: str | None, default: bool) -> bool:
    """Parse a bool from an env string; fall back to ``default`` on junk/empty."""
    if value is None or not str(value).strip():
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class EmbeddingConfig:
    """Configuration for a separate embedding model (OpenAI-compatible /v1/embeddings)."""
    api_key: str
    base_url: str
    model: str
    dimensions: int = 1536

    @classmethod
    def from_env(cls, prefix: str = "EMBEDDING_") -> "EmbeddingConfig | None":
        """Load from ${prefix}API_KEY/BASE_URL/MODEL/DIMENSIONS. Returns None when API_KEY is unset."""
        key = os.environ.get(f"{prefix}API_KEY")
        if not key:
            return None
        return cls(
            api_key=key,
            base_url=os.environ[f"{prefix}BASE_URL"],
            model=os.environ[f"{prefix}MODEL"],
            dimensions=int(os.environ.get(f"{prefix}DIMENSIONS", "1536")),
        )


@dataclass
class ModelConfig:
    api_key: str
    base_url: str
    model: str
    protocol: Protocol
    # USD price per 1,000,000 tokens. Left at 0 → cost tracking reports nothing
    # for this slot. Set to your provider's published rates to get per-turn cost.
    input_price_per_1m: float = 0.0
    output_price_per_1m: float = 0.0

    @classmethod
    def from_env(cls, prefix: str) -> "ModelConfig":
        """Load from ${prefix}_API_KEY/BASE_URL/MODEL/PROTOCOL (PROTOCOL defaults to openai).

        Optional pricing: ${prefix}_INPUT_PRICE / ${prefix}_OUTPUT_PRICE (USD per 1M tokens).
        """
        return cls(
            api_key=os.environ[f"{prefix}_API_KEY"],
            base_url=os.environ[f"{prefix}_BASE_URL"],
            model=os.environ[f"{prefix}_MODEL"],
            protocol=Protocol(os.environ.get(f"{prefix}_PROTOCOL", "openai")),
            input_price_per_1m=_to_float(os.environ.get(f"{prefix}_INPUT_PRICE")),
            output_price_per_1m=_to_float(os.environ.get(f"{prefix}_OUTPUT_PRICE")),
        )

    def cost(self, prompt_tokens: int | None, completion_tokens: int | None) -> float:
        """USD cost for the given token counts at this slot's prices."""
        return (
            (prompt_tokens or 0) / 1_000_000 * self.input_price_per_1m
            + (completion_tokens or 0) / 1_000_000 * self.output_price_per_1m
        )

    @property
    def has_pricing(self) -> bool:
        return self.input_price_per_1m > 0 or self.output_price_per_1m > 0


@dataclass
class WorkspacePrompts:
    """Override default system prompts for each workspace operation."""
    wp2_task: str | None = None       # A2: task execution
    wp3_direct: str | None = None     # A3: direct mission answer
    wp3_convert: str | None = None    # A3: mission → task conversion
    selector: str | None = None       # Selector classification
    wp1_checker: str | None = None    # WP1 checker evaluation
    wp2_checker: str | None = None    # WP2 checker evaluation
    wp3_checker: str | None = None    # WP3 checker evaluation


@dataclass
class StorageConfig:
    db_path: str = "autumn_memory.db"


@dataclass
class BehaviorConfig:
    """Tunable runtime knobs that used to be hardcoded constants.

    Defaults reproduce the framework's original behavior, so leaving this
    untouched changes nothing.
    """
    agent_max_steps: int = 10      # WP2 Agent ReAct iteration ceiling
    checker_retries: int = 3       # Checker validate/correct attempts before giving up
    confirm_threshold: float = 0.75  # Selector confidence below which the user is asked
    history_limit: int = 50        # Per-area memory history entries retained
    memory_decay_half_life: float = 0.0  # Seconds; importance halves each interval. 0 = off
    fourd_memory_enabled: bool = False  # Rank recall/evict by 4D activation score (off = today's importance×timestamp)
    fourd_push_on_turn: bool = False  # Allow push-activation of CONSTRAIN/REMIND memories at turn start (off = no push)

    @classmethod
    def from_env(cls, prefix: str = "") -> "BehaviorConfig":
        def env(name: str) -> str | None:
            return os.environ.get(f"{prefix}{name}")

        return cls(
            agent_max_steps=_to_int(env("AGENT_MAX_STEPS"), cls.agent_max_steps),
            checker_retries=_to_int(env("CHECKER_RETRIES"), cls.checker_retries),
            confirm_threshold=_to_float(env("CONFIRM_THRESHOLD"), cls.confirm_threshold),
            history_limit=_to_int(env("HISTORY_LIMIT"), cls.history_limit),
            memory_decay_half_life=_to_float(
                env("MEMORY_DECAY_HALF_LIFE"), cls.memory_decay_half_life
            ),
            fourd_memory_enabled=_to_bool(
                env("FOURD_MEMORY_ENABLED"), cls.fourd_memory_enabled
            ),
            fourd_push_on_turn=_to_bool(
                env("FOURD_PUSH_ON_TURN"), cls.fourd_push_on_turn
            ),
        )


@dataclass
class AutumnConfig:
    a1: ModelConfig
    a2: ModelConfig
    a3: ModelConfig
    a4: ModelConfig | None = None  # optional memory model (recall synthesis, cheap local LLM)
    prompts: WorkspacePrompts = field(default_factory=WorkspacePrompts)
    storage: StorageConfig = field(default_factory=StorageConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
    headless_mission_route: MissionRoute | Literal["auto"] = "auto"
    embedding: EmbeddingConfig | None = None
    auto_index: bool = False   # when embedding is set, auto-embed each history entry
    validate_before_stream: bool = True
    """When True (default), the streaming endpoint buffers the full pipeline
    response — including the WP1 checker — before chunking it back to the
    client. Trades real-time feedback for guaranteed validated output.

    When False, tokens flow live as they're produced; the checker runs once
    after the stream completes and appends an advisory chunk if it finds
    issues."""

    @classmethod
    def from_env(cls, prefix: str = "", env_file: str | None = None) -> "AutumnConfig":
        """Build a complete config from environment variables.

        Variables (all optionally prefixed by `prefix`):
            A1_API_KEY / A1_BASE_URL / A1_MODEL / A1_PROTOCOL  (A2/A3 likewise)
            A4_API_KEY / A4_BASE_URL / A4_MODEL / A4_PROTOCOL  (optional memory model)
            EMBEDDING_API_KEY / _BASE_URL / _MODEL / _DIMENSIONS  (optional)
            STORAGE_DB_PATH                          (default: autumn_memory.db)
            HEADLESS_MISSION_ROUTE                   (auto | direct | convert)
            AUTO_INDEX                               (true | false)

        Pass `env_file=".env"` to load values from a KEY=VALUE file before reading
        os.environ. Existing process env wins over file values. See `.env.example`.
        """
        if env_file:
            _load_env_file(env_file)

        def env(name: str, default: str | None = None) -> str:
            return os.environ.get(f"{prefix}{name}", default) or ""

        route_raw = env("HEADLESS_MISSION_ROUTE", "auto")
        route: MissionRoute | Literal["auto"] = (
            "auto" if route_raw == "auto" else MissionRoute(route_raw)
        )

        a4_key = env("A4_API_KEY")
        a4: ModelConfig | None = None
        if a4_key:
            a4 = ModelConfig(
                api_key=a4_key,
                base_url=env("A4_BASE_URL", "http://localhost:11434"),
                model=env("A4_MODEL", ""),
                protocol=Protocol(env("A4_PROTOCOL", "openai")),
            )

        return cls(
            a1=ModelConfig.from_env(f"{prefix}A1"),
            a2=ModelConfig.from_env(f"{prefix}A2"),
            a3=ModelConfig.from_env(f"{prefix}A3"),
            a4=a4,
            storage=StorageConfig(db_path=env("STORAGE_DB_PATH", "autumn_memory.db")),
            behavior=BehaviorConfig.from_env(prefix),
            headless_mission_route=route,
            embedding=EmbeddingConfig.from_env(f"{prefix}EMBEDDING_"),
            auto_index=env("AUTO_INDEX", "false").lower() in ("1", "true", "yes"),
            validate_before_stream=env("VALIDATE_BEFORE_STREAM", "true").lower() in ("1", "true", "yes"),
        )


def _load_env_file(path: str) -> None:
    """Minimal KEY=VALUE loader. Process env wins over file values."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

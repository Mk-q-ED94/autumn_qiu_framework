import os
from dataclasses import dataclass, field
from typing import Literal

from .types import MissionRoute, Protocol


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
            dimensions=_to_int(os.environ.get(f"{prefix}DIMENSIONS"), 1536),
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
    # Long-term backend for memory zones. "sqlite" (default) keeps today's
    # opaque DB; "markdown" stores each entry as a readable .md file with 4D
    # frontmatter under "<db_path>.mdstore/" (RFC 4D-memory P1-A).
    backend: str = "sqlite"


@dataclass
class BehaviorConfig:
    """Tunable runtime knobs that used to be hardcoded constants.

    The 4D memory layer (``fourd_memory_enabled`` / ``fourd_push_on_turn``) is
    **on by default** as of 0.3.x: recall/eviction rank by 4D activation and the
    push engine runs at turn start. Both degrade safely — an un-annotated store
    ranks exactly as ``importance × timestamp`` did, and push is a no-op until a
    CONSTRAIN/REMIND memory exists — so turning them on changes nothing until
    memories carry 4D dimensions. The cooperative interactive behaviours that add
    real model cost (``a1_supervision`` / ``a1_task_planning``) stay off by default.
    """

    agent_max_steps: int = 10      # WP2 Agent ReAct iteration ceiling
    checker_retries: int = 3       # Checker validate/correct attempts before giving up
    confirm_threshold: float = 0.75  # Selector confidence below which the user is asked
    history_limit: int = 50        # Per-area memory history entries retained
    memory_decay_half_life: float = 0.0  # Seconds; importance halves each interval. 0 = off
    fourd_memory_enabled: bool = True  # Rank recall/evict by 4D activation score (degrades to importance×timestamp for un-annotated entries)
    fourd_push_on_turn: bool = True  # Push-activate CONSTRAIN/REMIND memories at turn start (a no-op until such memories exist)
    fourd_pull_on_turn: bool = True  # Pull recent Mom1 cross-turn context into the executor prompt (the read half; no-op when Mom1 is empty)
    mom1_access_enabled: bool = True  # Allow Mom2/Mom3 to request adjudicated Mom1 reads via governed channel
    lexical_recall_enabled: bool = False  # Attach a BM25/FTS5 lexical layer fused into recall (off = vector-only)
    async_index: bool = False  # Index history entries in the background (off = synchronous, blocks append)
    # 0.3.0 cooperative workflow
    cooperative_workflow: bool = True  # Master switch; False reverts every 0.3.0 cooperative feature to 0.2.x behaviour
    a3_lite_skills: list[str] = field(default_factory=list)  # Skills A3 may call on the direct path (empty = off)
    a1_task_planning: bool = False  # A1 generates a step plan before dispatching to A2 (adds one A1 call per task)
    a1_supervision: bool = False  # A1 reviews each A2 ReAct step and may inject guidance (one A1 call per tool step)
    archive_executions: bool = True  # A1 hands each turn's outcome to A4 for a shared-zone execution summary
    a4_delegate_to_a1: bool = True  # A4's heavy memory ops (consolidate/evolve) may use A1
    a4_delegation_threshold: int = 2000  # Min source chars before A4 delegates to A1; smaller ops stay on local A4
    a4_knowledge_terr: bool = False  # Register a web-retrieval Terr and give A4 a research() path over it
    # Codebase-memory token-saving layer (codebase-memory-mcp). When on, the
    # server connects the code-graph MCP at startup so agents query structure
    # (calls/imports/architecture) instead of reading files. Off = today's behaviour.
    codebase_memory_enabled: bool = False
    codebase_memory_repo: str = ""  # Repo to scope/index; empty = server working directory

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
                env("MEMORY_DECAY_HALF_LIFE"), cls.memory_decay_half_life,
            ),
            fourd_memory_enabled=_to_bool(
                env("FOURD_MEMORY_ENABLED"), cls.fourd_memory_enabled,
            ),
            fourd_push_on_turn=_to_bool(
                env("FOURD_PUSH_ON_TURN"), cls.fourd_push_on_turn,
            ),
            fourd_pull_on_turn=_to_bool(
                env("FOURD_PULL_ON_TURN"), cls.fourd_pull_on_turn,
            ),
            mom1_access_enabled=_to_bool(
                env("MOM1_ACCESS_ENABLED"), cls.mom1_access_enabled
            ),
            lexical_recall_enabled=_to_bool(
                env("LEXICAL_RECALL_ENABLED"), cls.lexical_recall_enabled
            ),
            async_index=_to_bool(env("ASYNC_INDEX"), cls.async_index),
            cooperative_workflow=_to_bool(env("COOPERATIVE_WORKFLOW"), cls.cooperative_workflow),
            a3_lite_skills=[
                s.strip() for s in (env("A3_LITE_SKILLS") or "").split(",") if s.strip()
            ],
            a1_task_planning=_to_bool(env("A1_TASK_PLANNING"), cls.a1_task_planning),
            a1_supervision=_to_bool(env("A1_SUPERVISION"), cls.a1_supervision),
            archive_executions=_to_bool(env("ARCHIVE_EXECUTIONS"), cls.archive_executions),
            a4_delegate_to_a1=_to_bool(env("A4_DELEGATE_TO_A1"), cls.a4_delegate_to_a1),
            a4_delegation_threshold=_to_int(
                env("A4_DELEGATION_THRESHOLD"), cls.a4_delegation_threshold,
            ),
            a4_knowledge_terr=_to_bool(env("A4_KNOWLEDGE_TERR"), cls.a4_knowledge_terr),
            codebase_memory_enabled=_to_bool(
                env("CODEBASE_MEMORY_ENABLED"), cls.codebase_memory_enabled,
            ),
            codebase_memory_repo=env("CODEBASE_MEMORY_REPO") or cls.codebase_memory_repo,
        )

    # ── cooperative-workflow effective gates (master switch applied) ─────────────
    # Each feature flag only takes effect when the master ``cooperative_workflow``
    # is also on, so a single switch reverts the whole 0.3.0 layer to 0.2.x.

    @property
    def task_planning_on(self) -> bool:
        return self.cooperative_workflow and self.a1_task_planning

    @property
    def supervision_on(self) -> bool:
        return self.cooperative_workflow and self.a1_supervision

    @property
    def archive_on(self) -> bool:
        return self.cooperative_workflow and self.archive_executions

    @property
    def delegate_on(self) -> bool:
        return self.cooperative_workflow and self.a4_delegate_to_a1

    @property
    def knowledge_terr_on(self) -> bool:
        return self.cooperative_workflow and self.a4_knowledge_terr

    def lite_skills_on(self) -> list[str]:
        return self.a3_lite_skills if self.cooperative_workflow else []


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
            a4_model = env("A4_MODEL", "")
            if not a4_model:
                import warnings
                warnings.warn(
                    "A4_API_KEY is set but A4_MODEL is empty — A4 will be disabled. "
                    "Set A4_MODEL to a valid model name to enable memory operations.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            else:
                a4 = ModelConfig(
                    api_key=a4_key,
                    base_url=env("A4_BASE_URL", "http://127.0.0.1:11434"),
                    model=a4_model,
                    protocol=Protocol(env("A4_PROTOCOL", "openai")),
                    input_price_per_1m=_to_float(os.environ.get(f"{prefix}A4_INPUT_PRICE")),
                    output_price_per_1m=_to_float(os.environ.get(f"{prefix}A4_OUTPUT_PRICE")),
                )

        return cls(
            a1=ModelConfig.from_env(f"{prefix}A1"),
            a2=ModelConfig.from_env(f"{prefix}A2"),
            a3=ModelConfig.from_env(f"{prefix}A3"),
            a4=a4,
            storage=StorageConfig(
                db_path=env("STORAGE_DB_PATH", "autumn_memory.db"),
                backend=env("STORAGE_BACKEND", "sqlite"),
            ),
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

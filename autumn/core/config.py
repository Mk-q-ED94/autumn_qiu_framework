import os
from dataclasses import dataclass, field
from typing import Literal
from .types import Protocol, MissionRoute


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

    @classmethod
    def from_env(cls, prefix: str) -> "ModelConfig":
        """Load from ${prefix}_API_KEY/BASE_URL/MODEL/PROTOCOL (PROTOCOL defaults to openai)."""
        return cls(
            api_key=os.environ[f"{prefix}_API_KEY"],
            base_url=os.environ[f"{prefix}_BASE_URL"],
            model=os.environ[f"{prefix}_MODEL"],
            protocol=Protocol(os.environ.get(f"{prefix}_PROTOCOL", "openai")),
        )


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
class AutumnConfig:
    a1: ModelConfig
    a2: ModelConfig
    a3: ModelConfig
    a4: ModelConfig | None = None  # optional memory model (recall synthesis, cheap local LLM)
    prompts: WorkspacePrompts = field(default_factory=WorkspacePrompts)
    storage: StorageConfig = field(default_factory=StorageConfig)
    headless_mission_route: MissionRoute | Literal["auto"] = "auto"
    embedding: EmbeddingConfig | None = None
    auto_index: bool = False   # when embedding is set, auto-embed each history entry

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
            headless_mission_route=route,
            embedding=EmbeddingConfig.from_env(f"{prefix}EMBEDDING_"),
            auto_index=env("AUTO_INDEX", "false").lower() in ("1", "true", "yes"),
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

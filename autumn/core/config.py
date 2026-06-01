from typing import Literal
from pydantic import BaseModel
from .types import Protocol, MissionRoute


class ModelConfig(BaseModel):
    api_key: str
    base_url: str
    model: str
    protocol: Protocol


class WorkspacePrompts(BaseModel):
    """Override default system prompts for each workspace operation."""
    wp2_task: str | None = None       # A2: task execution
    wp3_direct: str | None = None     # A3: direct mission answer
    wp3_convert: str | None = None    # A3: mission → task conversion
    selector: str | None = None       # Selector classification
    wp1_checker: str | None = None    # WP1 checker evaluation
    wp2_checker: str | None = None    # WP2 checker evaluation
    wp3_checker: str | None = None    # WP3 checker evaluation


class StorageConfig(BaseModel):
    db_path: str = "autumn_memory.db"


class AutumnConfig(BaseModel):
    a1: ModelConfig
    a2: ModelConfig
    a3: ModelConfig
    prompts: WorkspacePrompts = WorkspacePrompts()
    storage: StorageConfig = StorageConfig()
    headless_mission_route: MissionRoute | Literal["auto"] = "auto"

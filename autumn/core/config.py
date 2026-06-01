from pydantic import BaseModel
from .types import Protocol


class ModelConfig(BaseModel):
    api_key: str
    base_url: str
    model: str
    protocol: Protocol


class AutumnConfig(BaseModel):
    a1: ModelConfig
    a2: ModelConfig
    a3: ModelConfig

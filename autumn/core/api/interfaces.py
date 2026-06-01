from .base import ModelAPIInterface
from ..config import ModelConfig


class A1(ModelAPIInterface):
    """Model API interface — governs WP1 (Total)."""

    def __init__(self, config: ModelConfig):
        super().__init__(config.api_key, config.base_url, config.model, config.protocol)


class A2(ModelAPIInterface):
    """Model API interface — governs WP2 (Task)."""

    def __init__(self, config: ModelConfig):
        super().__init__(config.api_key, config.base_url, config.model, config.protocol)


class A3(ModelAPIInterface):
    """Model API interface — governs WP3 (Mission)."""

    def __init__(self, config: ModelConfig):
        super().__init__(config.api_key, config.base_url, config.model, config.protocol)

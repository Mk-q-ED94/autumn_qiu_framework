from .base import ModelAPIInterface
from .hermes import HermesAPIInterface
from ..config import ModelConfig
from ..types import Protocol


def _build_interface(config: ModelConfig) -> ModelAPIInterface:
    """Return the right interface subclass based on config.protocol."""
    if config.protocol == Protocol.HERMES:
        return HermesAPIInterface(config.api_key, config.base_url, config.model)
    return ModelAPIInterface(config.api_key, config.base_url, config.model, config.protocol)


class A1(ModelAPIInterface):
    """Model API interface — governs WP1 (Total).

    Returns a :class:`HermesAPIInterface` when ``config.protocol`` is
    ``Protocol.HERMES``; otherwise a plain :class:`ModelAPIInterface`.
    """

    def __new__(cls, config: ModelConfig) -> ModelAPIInterface:  # type: ignore[override]
        return _build_interface(config)


class A2(ModelAPIInterface):
    """Model API interface — governs WP2 (Task)."""

    def __new__(cls, config: ModelConfig) -> ModelAPIInterface:  # type: ignore[override]
        return _build_interface(config)


class A3(ModelAPIInterface):
    """Model API interface — governs WP3 (Mission)."""

    def __new__(cls, config: ModelConfig) -> ModelAPIInterface:  # type: ignore[override]
        return _build_interface(config)

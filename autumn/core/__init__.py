from importlib import import_module

_EXPORTS = {
    "Autumn": ("autumn.core.framework", "Autumn"),
    "AutumnConfig": ("autumn.core.config", "AutumnConfig"),
    "ModelConfig": ("autumn.core.config", "ModelConfig"),
    "WorkspacePrompts": ("autumn.core.config", "WorkspacePrompts"),
    "StorageConfig": ("autumn.core.config", "StorageConfig"),
    "EmbeddingConfig": ("autumn.core.config", "EmbeddingConfig"),
    "Protocol": ("autumn.core.types", "Protocol"),
    "InputType": ("autumn.core.types", "InputType"),
    "MissionRoute": ("autumn.core.types", "MissionRoute"),
    "Message": ("autumn.core.types", "Message"),
    "Role": ("autumn.core.types", "Role"),
    "ToolCall": ("autumn.core.types", "ToolCall"),
    "SelectorResult": ("autumn.core.types", "SelectorResult"),
    "SearchResult": ("autumn.core.types", "SearchResult"),
    "UserInteraction": ("autumn.core.interaction", "UserInteraction"),
    "CLIInteraction": ("autumn.core.interaction", "CLIInteraction"),
    "EmbeddingInterface": ("autumn.core.api.embedding", "EmbeddingInterface"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module 'autumn.core' has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value

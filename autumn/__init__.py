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
    "TaskType": ("autumn.core.types", "TaskType"),
    "MissionRoute": ("autumn.core.types", "MissionRoute"),
    "WorkflowRun": ("autumn.core.types", "WorkflowRun"),
    "WorkflowStage": ("autumn.core.types", "WorkflowStage"),
    "AgentStep": ("autumn.core.types", "AgentStep"),
    "ToolCall": ("autumn.core.types", "ToolCall"),
    "Message": ("autumn.core.types", "Message"),
    "Role": ("autumn.core.types", "Role"),
    "SearchResult": ("autumn.core.types", "SearchResult"),
    "UserInteraction": ("autumn.core.interaction", "UserInteraction"),
    "CLIInteraction": ("autumn.core.interaction", "CLIInteraction"),
    "EmbeddingInterface": ("autumn.core.api.embedding", "EmbeddingInterface"),
    "HermesAPIInterface": ("autumn.core.api.hermes", "HermesAPIInterface"),
    "Agent": ("autumn.core.components", "Agent"),
    "Skill": ("autumn.core.components", "Skill"),
    "Tool": ("autumn.core.components", "Tool"),
    "ToolParameter": ("autumn.core.components", "ToolParameter"),
    "Terr": ("autumn.core.components", "Terr"),
    "MCPClient": ("autumn.core.components", "MCPClient"),
    "StdioMCPClient": ("autumn.core.components", "StdioMCPClient"),
    "mcp_to_tools": ("autumn.core.components", "mcp_to_tools"),
    "Selector": ("autumn.core.components", "Selector"),
    "Checker": ("autumn.core.components", "Checker"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module 'autumn' has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value

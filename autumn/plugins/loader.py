import importlib.util
from pathlib import Path
from typing import Any

from ..core.components import Agent, Skill, Tool, MCPClient

_PLUGIN_TYPES = (Agent, Skill, Tool, MCPClient)


class PluginLoader:
    """Loads and manages agent, skill, tool, and mcp plugins."""

    def __init__(self):
        self._registry: dict[str, Any] = {}

    def register(self, name: str, plugin: Any) -> None:
        self._registry[name] = plugin

    def get(self, name: str) -> Any:
        return self._registry[name]

    def all(self) -> dict[str, Any]:
        return dict(self._registry)

    def load_from_directory(self, plugin_dir: str | Path) -> None:
        plugin_dir = Path(plugin_dir)
        if not plugin_dir.exists():
            return
        for path in sorted(plugin_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(path.stem, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if isinstance(obj, _PLUGIN_TYPES):
                    self.register(obj.name, obj)

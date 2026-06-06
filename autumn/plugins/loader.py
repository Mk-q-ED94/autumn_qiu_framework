import importlib.util
import warnings
from pathlib import Path
from typing import Any

from ..core.components import Agent, Skill, Tool, MCPClient, Terr

_PLUGIN_TYPES = (Agent, Skill, Tool, MCPClient)


class PluginLoader:
    """Loads and manages agent, skill, tool, mcp, and terr plugins."""

    def __init__(self):
        self._registry: dict[str, Any] = {}
        self._terrs: dict[str, Terr] = {}

    def register(self, name: str, plugin: Any) -> None:
        existing = self._registry.get(name)
        if existing is not None and type(existing) is not type(plugin):
            warnings.warn(
                f"Plugin name {name!r} reused across types: "
                f"{type(existing).__name__} → {type(plugin).__name__}. "
                "The new registration wins; the old one is no longer reachable.",
                stacklevel=2,
            )
        self._registry[name] = plugin

    def get(self, name: str) -> Any:
        return self._registry[name]

    def all(self) -> dict[str, Any]:
        return dict(self._registry)

    def register_terr(self, terr: Terr) -> None:
        """Record a Terr domain by name. Individual tools/skills it contains must
        be registered separately (Autumn.add_terr handles this automatically)."""
        self._terrs[terr.name] = terr

    def get_terr(self, name: str) -> Terr:
        return self._terrs[name]

    def all_terrs(self) -> dict[str, Terr]:
        return dict(self._terrs)

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

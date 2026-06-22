import importlib.util
import warnings
from pathlib import Path
from typing import Any

from ..core.components import Agent, MCPClient, Skill, Terr, Tool

_PLUGIN_TYPES = (Agent, Skill, Tool, MCPClient)


class PluginLoader:
    """Loads and manages agent, skill, tool, mcp, and terr plugins."""

    def __init__(self):
        self._registry: dict[str, Any] = {}
        self._terrs: dict[str, Terr] = {}
        self._terr_enabled: dict[str, bool] = {}
        # Per-Terr list of callable names it registered, so a Terr can be removed
        # (and hot-reloaded) precisely instead of leaking orphan tools/skills.
        self._terr_callables: dict[str, list[str]] = {}
        # Terr names contributed by a directory load, for reload_from_directory.
        self._dir_terrs: set[str] = set()

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

    def register_terr(self, terr: Terr, extra_callables: tuple[str, ...] = ()) -> None:
        """Record a Terr domain by name. Individual tools/skills it contains must
        be registered separately (Autumn.add_terr handles this automatically).

        Tracks which callables the Terr owns so it can later be removed cleanly.
        ``extra_callables`` carries names registered outside ``terr.tools`` /
        ``terr.skills`` — e.g. the MCP-bridged tools the framework adds — so a
        later :meth:`remove_terr` unregisters those too.
        """
        self._terrs[terr.name] = terr
        self._terr_enabled.setdefault(terr.name, True)
        owned = [t.name for t in terr.tools] + [s.name for s in terr.skills]
        owned.extend(extra_callables)
        self._terr_callables[terr.name] = owned

    def get_terr(self, name: str) -> Terr:
        return self._terrs[name]

    def all_terrs(self) -> dict[str, Terr]:
        return dict(self._terrs)

    def is_terr_enabled(self, name: str) -> bool:
        return self._terr_enabled.get(name, True)

    def set_terr_enabled(self, name: str, enabled: bool) -> None:
        if name not in self._terrs:
            raise KeyError(name)
        self._terr_enabled[name] = enabled

    def unregister(self, name: str) -> None:
        self._registry.pop(name, None)

    def unregister_terr(self, name: str) -> None:
        self._terrs.pop(name, None)
        self._terr_enabled.pop(name, None)
        self._terr_callables.pop(name, None)
        self._dir_terrs.discard(name)

    def remove_terr(self, name: str) -> list[str]:
        """Unregister a Terr *and every callable it owns*, returning the removed
        callable names. Idempotent — removing an unknown Terr returns ``[]``.

        The caller owns any external resources (e.g. MCP clients): this only
        touches the in-memory registry. ``Autumn.remove_terr`` wraps this to also
        disconnect the domain's MCP servers.
        """
        removed = self._terr_callables.pop(name, [])
        for cb in removed:
            self._registry.pop(cb, None)
        self._terrs.pop(name, None)
        self._terr_enabled.pop(name, None)
        self._dir_terrs.discard(name)
        return removed

    def load_from_directory(self, plugin_dir: str | Path) -> None:
        plugin_dir = Path(plugin_dir)
        if not plugin_dir.exists():
            return
        for path in sorted(plugin_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(path.stem, path)
            if spec is None or spec.loader is None:
                warnings.warn(
                    f"Plugin {path.name!r} is not a loadable module. Skipping.",
                    stacklevel=2,
                )
                continue
            try:
                module = importlib.util.module_from_spec(spec)
                # Compile from source on every load instead of exec_module(), whose
                # bytecode cache keys on (mtime, size) — a hot reload of a same-size
                # edit (e.g. a one-char change, or "v1tool"→"v2tool") would otherwise
                # serve stale code from __pycache__.
                source = path.read_text(encoding="utf-8")
                exec(compile(source, str(path), "exec"), module.__dict__)  # noqa: S102
            except Exception as e:  # noqa: BLE001 — one broken plugin must not abort the rest
                warnings.warn(
                    f"Failed to load plugin {path.name!r}: {type(e).__name__}: {e}. Skipping.",
                    stacklevel=2,
                )
                continue
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if isinstance(obj, Terr):
                    # Register constituent tools/skills individually so
                    # _collect_plugins() can pick them up, and track the terr
                    # as a unit. MCP clients in the terr are NOT connected here
                    # (sync context) — use Autumn.add_terr() for that.
                    for tool in obj.tools:
                        self.register(tool.name, tool)
                    for skill in obj.skills:
                        self.register(skill.name, skill)
                    self.register_terr(obj)
                    self._dir_terrs.add(obj.name)
                elif isinstance(obj, _PLUGIN_TYPES):
                    self.register(obj.name, obj)

    def reload_from_directory(self, plugin_dir: str | Path) -> dict[str, list[str]]:
        """Re-load a plugin directory at runtime, applying the delta.

        Every ``.py`` file is re-executed from disk (modules are never cached in
        ``sys.modules`` here, so edits take effect), and Terrs are reconciled:
        a Terr that vanished from the files is removed along with its callables;
        new or changed Terrs are re-registered. Enables editing a plugin and
        having it take effect without restarting the process.

        MCP clients embedded in a Terr are *not* connected (same constraint as
        :meth:`load_from_directory`) — for an MCP-bearing domain use
        :meth:`Autumn.reload_terr`. Returns ``{"removed": [...], "loaded": [...]}``
        listing the Terr names dropped and present after the reload.
        """
        previous = set(self._dir_terrs)
        for name in previous:
            self.remove_terr(name)
        self._dir_terrs.clear()
        self.load_from_directory(plugin_dir)
        current = set(self._dir_terrs)
        return {
            "removed": sorted(previous - current),
            "loaded": sorted(current),
        }

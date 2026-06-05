from importlib import import_module

_EXPORTS = {
    "ModelAPIInterface": ("autumn.core.api.base", "ModelAPIInterface"),
    "HermesAPIInterface": ("autumn.core.api.hermes", "HermesAPIInterface"),
    "A1": ("autumn.core.api.interfaces", "A1"),
    "A2": ("autumn.core.api.interfaces", "A2"),
    "A3": ("autumn.core.api.interfaces", "A3"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module 'autumn.core.api' has no attribute {name!r}") from exc
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value

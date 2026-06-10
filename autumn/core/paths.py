"""Cross-platform application paths.

The framework writes a few things to disk — the SQLite memory database, an
optional ``.env``, server logs — and where those belong differs per OS:

* **Windows** — per-user data lives under ``%APPDATA%`` (roaming) and logs under
  ``%LOCALAPPDATA%``; writing next to the executable (often ``Program Files``)
  is denied for non-admin users.
* **macOS** — ``~/Library/Application Support`` for data, ``~/Library/Logs`` for logs.
* **Linux** — the XDG base-directory spec: ``$XDG_DATA_HOME`` (``~/.local/share``)
  and ``$XDG_STATE_HOME`` (``~/.local/state``).

These helpers centralise that knowledge so the desktop clients (the macOS
SwiftUI app and the Windows WinUI app) and the server agree on where per-user
files go. Nothing here changes the historical default of writing
``autumn_memory.db`` into the current working directory — that only happens when
a caller opts in via ``AUTUMN_DATA_DIR`` or passes an explicit ``data_dir``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "app_data_dir",
    "app_log_dir",
    "resolve_data_path",
    "DATA_DIR_ENV",
]

#: Environment variable a launcher can set to root relative storage paths.
DATA_DIR_ENV = "AUTUMN_DATA_DIR"


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def app_data_dir(app_name: str = "Autumn") -> Path:
    """Return the per-user data directory for ``app_name`` on this OS.

    Windows → ``%APPDATA%\\Autumn``; macOS → ``~/Library/Application Support/Autumn``;
    Linux/other → ``$XDG_DATA_HOME/autumn`` (falling back to ``~/.local/share/autumn``).
    The directory is **not** created — call :meth:`pathlib.Path.mkdir` if needed.
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(_home() / "AppData" / "Roaming")
        return Path(base) / app_name
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / app_name
    base = os.environ.get("XDG_DATA_HOME") or str(_home() / ".local" / "share")
    return Path(base) / app_name.lower()


def app_log_dir(app_name: str = "Autumn") -> Path:
    """Return the per-user log directory for ``app_name`` on this OS.

    Windows → ``%LOCALAPPDATA%\\Autumn\\logs``; macOS → ``~/Library/Logs/Autumn``;
    Linux/other → ``$XDG_STATE_HOME/autumn/logs`` (falling back to
    ``~/.local/state/autumn/logs``). The directory is **not** created.
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(_home() / "AppData" / "Local")
        return Path(base) / app_name / "logs"
    if sys.platform == "darwin":
        return _home() / "Library" / "Logs" / app_name
    base = os.environ.get("XDG_STATE_HOME") or str(_home() / ".local" / "state")
    return Path(base) / app_name.lower() / "logs"


def resolve_data_path(path: str, *, data_dir: str | None = None) -> str:
    """Resolve a storage ``path``, optionally rooting relatives under a data dir.

    The rules, in order:

    1. ``~`` is expanded (``~/foo`` → home-relative).
    2. An **absolute** path is returned unchanged.
    3. A **relative** path is joined onto ``data_dir`` when given, else onto the
       :data:`AUTUMN_DATA_DIR` environment variable when set.
    4. Otherwise the path is returned as-is — i.e. relative to the current
       working directory, preserving the framework's historical behaviour.

    This lets a Windows/macOS launcher point storage at :func:`app_data_dir`
    (per-user, writable) just by exporting ``AUTUMN_DATA_DIR``, without any
    caller that passes an absolute ``STORAGE_DB_PATH`` being affected.
    """
    expanded = Path(path).expanduser()
    if expanded.is_absolute():
        return str(expanded)
    base = data_dir if data_dir is not None else os.environ.get(DATA_DIR_ENV)
    if base:
        return str(Path(base).expanduser() / expanded)
    return str(expanded)

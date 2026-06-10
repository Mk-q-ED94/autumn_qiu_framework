"""Tests for cross-platform application paths (autumn.core.paths)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from autumn.core import paths


# ── app_data_dir / app_log_dir per platform ──────────────────────────────────


def test_app_data_dir_windows(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", r"C:\Users\me\AppData\Roaming")
    got = paths.app_data_dir()
    assert got == Path(r"C:\Users\me\AppData\Roaming") / "Autumn"


def test_app_data_dir_windows_falls_back_without_appdata(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)
    got = paths.app_data_dir()
    # Falls back to ~/AppData/Roaming/Autumn
    assert got.parts[-3:] == ("AppData", "Roaming", "Autumn")


def test_app_data_dir_macos(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    got = paths.app_data_dir()
    assert got.parts[-3:] == ("Library", "Application Support", "Autumn")


def test_app_data_dir_linux_uses_xdg(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", "/home/me/.local/share")
    got = paths.app_data_dir()
    assert got == Path("/home/me/.local/share/autumn")


def test_app_data_dir_linux_fallback(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    got = paths.app_data_dir()
    assert got.parts[-3:] == (".local", "share", "autumn")


def test_app_log_dir_windows(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\me\AppData\Local")
    got = paths.app_log_dir()
    assert got == Path(r"C:\Users\me\AppData\Local") / "Autumn" / "logs"


def test_app_log_dir_macos(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    got = paths.app_log_dir()
    assert got.parts[-3:] == ("Library", "Logs", "Autumn")


def test_app_log_dir_linux_uses_xdg_state(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setenv("XDG_STATE_HOME", "/home/me/.local/state")
    got = paths.app_log_dir()
    assert got == Path("/home/me/.local/state/autumn/logs")


def test_custom_app_name(monkeypatch):
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    got = paths.app_data_dir("MyAgent")
    assert got.parts[-1] == "MyAgent"


# ── resolve_data_path ─────────────────────────────────────────────────────────


def test_resolve_absolute_path_unchanged():
    p = os.path.abspath(os.sep + os.path.join("var", "data", "x.db"))
    assert paths.resolve_data_path(p) == str(Path(p))


def test_resolve_relative_without_data_dir_is_cwd_relative(monkeypatch):
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    # Historical behaviour preserved: returned as-is (cwd-relative).
    assert paths.resolve_data_path("autumn_memory.db") == "autumn_memory.db"


def test_resolve_relative_roots_under_explicit_data_dir():
    got = paths.resolve_data_path("autumn_memory.db", data_dir="/srv/autumn")
    assert got == str(Path("/srv/autumn") / "autumn_memory.db")


def test_resolve_relative_roots_under_env_data_dir(monkeypatch):
    monkeypatch.setenv(paths.DATA_DIR_ENV, "/srv/autumn")
    got = paths.resolve_data_path("autumn_memory.db")
    assert got == str(Path("/srv/autumn") / "autumn_memory.db")


def test_resolve_explicit_data_dir_overrides_env(monkeypatch):
    monkeypatch.setenv(paths.DATA_DIR_ENV, "/srv/from-env")
    got = paths.resolve_data_path("x.db", data_dir="/srv/explicit")
    assert got == str(Path("/srv/explicit") / "x.db")


def test_resolve_expands_user(monkeypatch):
    home = os.path.expanduser("~")
    got = paths.resolve_data_path("~/agent.db")
    assert got == str(Path(home) / "agent.db")


# ── SQLite backend creates a missing parent directory ─────────────────────────


async def test_sqlite_backend_creates_parent_dir(tmp_path):
    from autumn.core.memory.backends.sqlite_backend import SQLiteBackend

    nested = tmp_path / "fresh" / "appdata" / "Autumn"
    assert not nested.exists()
    backend = SQLiteBackend(str(nested / "autumn_memory.db"))
    await backend.set("k", "v")
    assert await backend.get("k") == "v"
    assert nested.exists()


def test_config_from_env_roots_db_under_data_dir(monkeypatch, tmp_path):
    from autumn.core.config import AutumnConfig

    monkeypatch.setenv(paths.DATA_DIR_ENV, str(tmp_path))
    for slot in ("A1", "A2", "A3"):
        monkeypatch.setenv(f"{slot}_API_KEY", "k")
        monkeypatch.setenv(f"{slot}_BASE_URL", "https://api.openai.com")
        monkeypatch.setenv(f"{slot}_MODEL", "gpt-4o-mini")
        monkeypatch.setenv(f"{slot}_PROTOCOL", "openai")
    monkeypatch.delenv("STORAGE_DB_PATH", raising=False)

    config = AutumnConfig.from_env()
    assert config.storage.db_path == str(tmp_path / "autumn_memory.db")

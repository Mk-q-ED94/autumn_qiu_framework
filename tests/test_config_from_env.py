"""Tests for AutumnConfig.from_env, ModelConfig.from_env, EmbeddingConfig.from_env."""
import os
import pytest

from autumn.core.config import (
    AutumnConfig,
    ModelConfig,
    EmbeddingConfig,
    _load_env_file,
)
from autumn.core.types import Protocol, MissionRoute


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every Autumn-related env var before each test."""
    for key in list(os.environ):
        if any(key.startswith(p) for p in (
            "A1_", "A2_", "A3_", "A4_", "X_", "EMBEDDING_", "STORAGE_", "HEADLESS_",
            "AUTO_INDEX", "VALIDATE_", "AGENT_MAX_STEPS", "CHECKER_RETRIES",
            "CONFIRM_THRESHOLD", "HISTORY_LIMIT",
        )):
            monkeypatch.delenv(key, raising=False)
    return monkeypatch


def _set_minimum(env, a3_protocol: str = "openai"):
    for prefix in ("A1", "A2", "A3"):
        env.setenv(f"{prefix}_API_KEY", f"k-{prefix.lower()}")
        env.setenv(f"{prefix}_BASE_URL", f"https://{prefix.lower()}.example")
        env.setenv(f"{prefix}_MODEL", f"{prefix.lower()}-model")
    env.setenv("A3_PROTOCOL", a3_protocol)


# ── ModelConfig ───────────────────────────────────────────────────────────────

def test_model_config_from_env(clean_env):
    clean_env.setenv("X_API_KEY", "k")
    clean_env.setenv("X_BASE_URL", "https://x")
    clean_env.setenv("X_MODEL", "m")
    clean_env.setenv("X_PROTOCOL", "anthropic")
    cfg = ModelConfig.from_env("X")
    assert cfg.api_key == "k"
    assert cfg.protocol == Protocol.ANTHROPIC


def test_model_config_defaults_protocol_to_openai(clean_env):
    clean_env.setenv("X_API_KEY", "k")
    clean_env.setenv("X_BASE_URL", "https://x")
    clean_env.setenv("X_MODEL", "m")
    cfg = ModelConfig.from_env("X")
    assert cfg.protocol == Protocol.OPENAI


def test_model_config_missing_key_raises(clean_env):
    with pytest.raises(KeyError):
        ModelConfig.from_env("MISSING")


# ── EmbeddingConfig ───────────────────────────────────────────────────────────

def test_embedding_config_none_when_key_unset(clean_env):
    assert EmbeddingConfig.from_env() is None


def test_embedding_config_from_env(clean_env):
    clean_env.setenv("EMBEDDING_API_KEY", "ek")
    clean_env.setenv("EMBEDDING_BASE_URL", "https://e")
    clean_env.setenv("EMBEDDING_MODEL", "em")
    clean_env.setenv("EMBEDDING_DIMENSIONS", "768")
    cfg = EmbeddingConfig.from_env()
    assert cfg is not None
    assert cfg.dimensions == 768
    assert cfg.model == "em"


def test_embedding_config_default_dimensions(clean_env):
    clean_env.setenv("EMBEDDING_API_KEY", "ek")
    clean_env.setenv("EMBEDDING_BASE_URL", "https://e")
    clean_env.setenv("EMBEDDING_MODEL", "em")
    cfg = EmbeddingConfig.from_env()
    assert cfg.dimensions == 1536


# ── AutumnConfig ──────────────────────────────────────────────────────────────

def test_autumn_config_from_env_minimal(clean_env):
    _set_minimum(clean_env)
    cfg = AutumnConfig.from_env()
    assert cfg.a1.api_key == "k-a1"
    assert cfg.a2.base_url == "https://a2.example"
    assert cfg.a3.protocol == Protocol.OPENAI
    assert cfg.headless_mission_route == "auto"
    assert cfg.storage.db_path == "autumn_memory.db"
    assert cfg.embedding is None
    assert cfg.auto_index is False


def test_autumn_config_explicit_route(clean_env):
    _set_minimum(clean_env)
    clean_env.setenv("HEADLESS_MISSION_ROUTE", "direct")
    cfg = AutumnConfig.from_env()
    assert cfg.headless_mission_route == MissionRoute.DIRECT


def test_autumn_config_invalid_route_raises(clean_env):
    _set_minimum(clean_env)
    clean_env.setenv("HEADLESS_MISSION_ROUTE", "bogus")
    with pytest.raises(ValueError):
        AutumnConfig.from_env()


def test_autumn_config_auto_index_truthy(clean_env):
    _set_minimum(clean_env)
    for truthy in ("true", "TRUE", "1", "yes"):
        clean_env.setenv("AUTO_INDEX", truthy)
        assert AutumnConfig.from_env().auto_index is True


def test_autumn_config_auto_index_falsy(clean_env):
    _set_minimum(clean_env)
    for falsy in ("false", "0", "no", ""):
        clean_env.setenv("AUTO_INDEX", falsy)
        assert AutumnConfig.from_env().auto_index is False


def test_autumn_config_prefix(clean_env):
    for prefix in ("A1", "A2", "A3"):
        clean_env.setenv(f"MY_{prefix}_API_KEY", "x")
        clean_env.setenv(f"MY_{prefix}_BASE_URL", "https://x")
        clean_env.setenv(f"MY_{prefix}_MODEL", "m")
    cfg = AutumnConfig.from_env(prefix="MY_")
    assert cfg.a1.api_key == "x"
    assert cfg.a2.model == "m"


def test_autumn_config_includes_embedding(clean_env):
    _set_minimum(clean_env)
    clean_env.setenv("EMBEDDING_API_KEY", "ek")
    clean_env.setenv("EMBEDDING_BASE_URL", "https://e")
    clean_env.setenv("EMBEDDING_MODEL", "em")
    cfg = AutumnConfig.from_env()
    assert cfg.embedding is not None
    assert cfg.embedding.model == "em"


# ── env file loader ───────────────────────────────────────────────────────────

def test_load_env_file_basic(clean_env, tmp_path):
    f = tmp_path / ".env"
    f.write_text("FOO=bar\nBAZ=qux\n")
    _load_env_file(str(f))
    assert os.environ["FOO"] == "bar"
    assert os.environ["BAZ"] == "qux"


def test_load_env_file_skips_comments_blank(clean_env, tmp_path):
    f = tmp_path / ".env"
    f.write_text("# this is a comment\n\nFOO=bar\n  # indented comment\n")
    _load_env_file(str(f))
    assert os.environ["FOO"] == "bar"


def test_load_env_file_strips_quotes(clean_env, tmp_path):
    f = tmp_path / ".env"
    f.write_text('SINGLE=\'hello\'\nDOUBLE="world"\n')
    _load_env_file(str(f))
    assert os.environ["SINGLE"] == "hello"
    assert os.environ["DOUBLE"] == "world"


def test_load_env_file_process_env_wins(clean_env, tmp_path):
    clean_env.setenv("FOO", "from_process")
    f = tmp_path / ".env"
    f.write_text("FOO=from_file\n")
    _load_env_file(str(f))
    assert os.environ["FOO"] == "from_process"


def test_load_env_file_missing_is_silent(clean_env):
    # Should not raise — missing file is OK.
    _load_env_file("/nonexistent/path/.env")


def test_autumn_config_from_env_with_file(clean_env, tmp_path):
    f = tmp_path / ".env"
    f.write_text(
        "A1_API_KEY=k1\nA1_BASE_URL=https://a1\nA1_MODEL=m1\n"
        "A2_API_KEY=k2\nA2_BASE_URL=https://a2\nA2_MODEL=m2\n"
        "A3_API_KEY=k3\nA3_BASE_URL=https://a3\nA3_MODEL=m3\n"
    )
    cfg = AutumnConfig.from_env(env_file=str(f))
    assert cfg.a1.api_key == "k1"
    assert cfg.a3.model == "m3"


# ── ModelConfig pricing ─────────────────────────────────────────────────────────

def test_model_config_pricing_from_env(clean_env):
    clean_env.setenv("X_API_KEY", "k")
    clean_env.setenv("X_BASE_URL", "https://x")
    clean_env.setenv("X_MODEL", "m")
    clean_env.setenv("X_INPUT_PRICE", "2.5")
    clean_env.setenv("X_OUTPUT_PRICE", "10")
    cfg = ModelConfig.from_env("X")
    assert cfg.input_price_per_1m == 2.5
    assert cfg.output_price_per_1m == 10.0
    assert cfg.has_pricing is True


def test_model_config_pricing_defaults_to_zero(clean_env):
    clean_env.setenv("X_API_KEY", "k")
    clean_env.setenv("X_BASE_URL", "https://x")
    clean_env.setenv("X_MODEL", "m")
    cfg = ModelConfig.from_env("X")
    assert cfg.input_price_per_1m == 0.0
    assert cfg.has_pricing is False


def test_model_config_pricing_junk_falls_back(clean_env):
    clean_env.setenv("X_API_KEY", "k")
    clean_env.setenv("X_BASE_URL", "https://x")
    clean_env.setenv("X_MODEL", "m")
    clean_env.setenv("X_INPUT_PRICE", "not-a-number")
    cfg = ModelConfig.from_env("X")
    assert cfg.input_price_per_1m == 0.0


def test_model_config_cost_computation():
    cfg = ModelConfig("k", "u", "m", Protocol.OPENAI,
                      input_price_per_1m=3.0, output_price_per_1m=15.0)
    # 1000 prompt @ $3/1M + 500 completion @ $15/1M = 0.003 + 0.0075
    assert cfg.cost(1000, 500) == pytest.approx(0.0105)
    assert cfg.cost(None, None) == 0.0


# ── BehaviorConfig ──────────────────────────────────────────────────────────────

def test_behavior_config_defaults():
    from autumn.core.config import BehaviorConfig
    b = BehaviorConfig()
    assert b.agent_max_steps == 10
    assert b.checker_retries == 3
    assert b.confirm_threshold == 0.75
    assert b.history_limit == 50


def test_behavior_config_from_env(clean_env):
    from autumn.core.config import BehaviorConfig
    clean_env.setenv("AGENT_MAX_STEPS", "20")
    clean_env.setenv("CHECKER_RETRIES", "1")
    clean_env.setenv("CONFIRM_THRESHOLD", "0.5")
    clean_env.setenv("HISTORY_LIMIT", "200")
    b = BehaviorConfig.from_env()
    assert b.agent_max_steps == 20
    assert b.checker_retries == 1
    assert b.confirm_threshold == 0.5
    assert b.history_limit == 200


def test_behavior_config_from_env_partial_keeps_defaults(clean_env):
    from autumn.core.config import BehaviorConfig
    clean_env.setenv("AGENT_MAX_STEPS", "7")
    b = BehaviorConfig.from_env()
    assert b.agent_max_steps == 7
    assert b.checker_retries == 3  # untouched default


def test_autumn_config_from_env_includes_behavior(clean_env):
    _set_minimum(clean_env)
    clean_env.setenv("AGENT_MAX_STEPS", "15")
    clean_env.setenv("A1_INPUT_PRICE", "1.0")
    cfg = AutumnConfig.from_env()
    assert cfg.behavior.agent_max_steps == 15
    assert cfg.a1.input_price_per_1m == 1.0

"""Tests for tunable BehaviorConfig knobs and USD cost annotation.

Covers the parameters that used to be hardcoded module constants
(agent_max_steps, checker_retries, confirm_threshold, history_limit) plus the
per-stage cost tracking added alongside them.
"""
import pytest

from autumn import Autumn
from autumn.core.config import AutumnConfig, BehaviorConfig, ModelConfig, StorageConfig
from autumn.core.framework import _annotate_costs
from autumn.core.components.checker import Checker
from autumn.core.components.selector import Selector
from autumn.core.memory.base import MemoryArea
from autumn.core.memory.backends import DictBackend
from autumn.core.types import (
    InputType,
    Protocol,
    SelectorResult,
    WorkflowRun,
    WorkflowStage,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _config(tmp_path, behavior: BehaviorConfig | None = None, **slot_kwargs) -> AutumnConfig:
    mc = ModelConfig("k", "http://localhost", "m", Protocol.OPENAI, **slot_kwargs)
    return AutumnConfig(
        a1=mc, a2=mc, a3=mc,
        storage=StorageConfig(db_path=str(tmp_path / "mem.db")),
        behavior=behavior or BehaviorConfig(),
    )


class _RecordingAPI:
    """Mock model API that records calls and returns canned completions."""

    def __init__(self, completions: list[str]):
        self._completions = list(completions)
        self.calls: list[list] = []
        self.last_usage = None

    async def complete(self, messages, **kwargs):
        self.calls.append(messages)
        return self._completions.pop(0) if self._completions else "ok"


class _StubInteraction:
    def __init__(self):
        self.asked = False

    async def ask(self, question, options):
        self.asked = True
        return options[0]


# ── BehaviorConfig wiring through Autumn ────────────────────────────────────────


def test_autumn_threads_behavior_into_components(tmp_path):
    behavior = BehaviorConfig(
        agent_max_steps=42, checker_retries=5, confirm_threshold=0.6, history_limit=123,
        memory_decay_half_life=3600,
    )
    autumn = Autumn(_config(tmp_path, behavior=behavior))
    assert autumn.wp2._agent_max_steps == 42
    assert autumn.wp1.selector._confirm_threshold == 0.6
    assert autumn.wp1.checker._retries == 5
    assert autumn.wp2.checker._retries == 5
    assert autumn.wp3.checker._retries == 5
    assert autumn.mom1._history_limit == 123
    assert autumn.mom2._history_limit == 123
    assert autumn.mom3._history_limit == 123
    # Decay reaches every zone, including project zones.
    assert autumn.mom1._decay_half_life == 3600
    assert autumn.shared._decay_half_life == 3600
    assert autumn.projects.zone("p")._decay_half_life == 3600


def test_autumn_defaults_unchanged(tmp_path):
    autumn = Autumn(_config(tmp_path))
    assert autumn.wp2._agent_max_steps == 10
    assert autumn.wp1.checker._retries == 3
    assert autumn.wp1.selector._confirm_threshold == 0.75
    assert autumn.mom1._history_limit == 50
    assert autumn.mom1._decay_half_life is None  # decay off by default


# ── Checker retries ─────────────────────────────────────────────────────────────


async def test_checker_retries_one_runs_single_pass():
    # retries=1 means: one model check, no correction loop even on failure.
    api = _RecordingAPI(['{"ok": false, "issues": "bad"}'])
    checker = Checker("wp2", api, retries=1)
    mem = MemoryArea("m", DictBackend())
    ok, result = await checker.validate("a long enough output string", mem)
    assert ok is False
    assert "[CHECK_FAILED(wp2): bad]" in result
    assert len(api.calls) == 1  # only the model check; no _correct call


async def test_checker_honours_fenced_json_verdict():
    # A judge wrapping its verdict in a ```json fence must still be honoured —
    # the old behaviour silently passed (fail-open) on unparseable fenced JSON.
    api = _RecordingAPI(['```json\n{"ok": false, "issues": "too vague"}\n```'])
    checker = Checker("wp2", api, retries=1)
    mem = MemoryArea("m", DictBackend())
    ok, result = await checker.validate("a long enough output string", mem)
    assert ok is False
    assert "too vague" in result


async def test_checker_honours_fenced_passing_verdict():
    api = _RecordingAPI(['```json\n{"ok": true}\n```'])
    checker = Checker("wp2", api, retries=1)
    mem = MemoryArea("m", DictBackend())
    ok, result = await checker.validate("a long enough output string", mem)
    assert ok is True
    assert result == "a long enough output string"


def test_wp1_check_detail_surfaces_advisory_on_failure():
    # A failed buffered-path check must reach the user, not be silently stripped.
    from autumn.core.workspace.wp1 import _ADVISORY_PREFIX, _check_detail

    checked = "[CHECK_FAILED(wp1): missing sources]\n\nThe answer body."
    output, detail = _check_detail(False, checked, "passed", "failed")
    assert output.startswith("The answer body.")
    assert _ADVISORY_PREFIX in output
    assert output.endswith("missing sources")
    assert "missing sources" in detail


def test_wp1_check_detail_passes_clean_output_unchanged():
    from autumn.core.workspace.wp1 import _ADVISORY_PREFIX, _check_detail

    output, detail = _check_detail(True, "The answer body.", "passed", "failed")
    assert output == "The answer body."
    assert _ADVISORY_PREFIX not in output
    assert detail == "passed"


async def test_checker_retries_allow_correction():
    # First check fails → correct → second check passes.
    api = _RecordingAPI(['{"ok": false, "issues": "x"}', "corrected output", '{"ok": true}'])
    checker = Checker("wp2", api, retries=3)
    mem = MemoryArea("m", DictBackend())
    ok, result = await checker.validate("original output here", mem)
    assert ok is True
    assert result == "corrected output"
    assert len(api.calls) == 3  # check → correct → check


# ── Selector confirm_threshold ──────────────────────────────────────────────────


async def test_selector_asks_below_threshold():
    api = _RecordingAPI(['{"type": "mission", "confidence": 0.6}'])
    selector = Selector(api, confirm_threshold=0.75)
    interaction = _StubInteraction()
    await selector.classify_and_maybe_confirm("ambiguous input", interaction)
    assert interaction.asked is True


async def test_selector_skips_confirm_when_threshold_low():
    api = _RecordingAPI(['{"type": "mission", "confidence": 0.6}'])
    selector = Selector(api, confirm_threshold=0.5)  # 0.6 >= 0.5 → no ask
    interaction = _StubInteraction()
    result = await selector.classify_and_maybe_confirm("ambiguous input", interaction)
    assert interaction.asked is False
    assert result.confidence == 0.6


# ── MemoryArea history_limit ────────────────────────────────────────────────────


async def test_memory_history_limit_caps_entries():
    area = MemoryArea("m", DictBackend(), history_limit=3)
    for i in range(6):
        await area.append_history({"i": i})
    history = await area.get_history()
    assert len(history) == 3
    assert [e.content["i"] for e in history] == [3, 4, 5]  # most recent kept


async def test_memory_history_explicit_max_entries_overrides():
    area = MemoryArea("m", DictBackend(), history_limit=3)
    for i in range(6):
        await area.append_history({"i": i}, max_entries=2)
    history = await area.get_history()
    assert len(history) == 2


# ── cost annotation ─────────────────────────────────────────────────────────────


def _run_with_stages() -> WorkflowRun:
    return WorkflowRun(
        output="out",
        input_type=InputType.TASK,
        route=None,
        stages=[
            WorkflowStage(id="s1", title="A1", detail="", workspace="WP1",
                          prompt_tokens=1000, completion_tokens=200),
            WorkflowStage(id="s2", title="A2", detail="", workspace="WP2",
                          prompt_tokens=2000, completion_tokens=500),
            WorkflowStage(id="s3", title="tool", detail="", workspace="WP2", kind="tool"),
        ],
    )


def test_annotate_costs_prices_by_workspace(tmp_path):
    config = AutumnConfig(
        a1=ModelConfig("k", "u", "m", Protocol.OPENAI, input_price_per_1m=1.0, output_price_per_1m=2.0),
        a2=ModelConfig("k", "u", "m", Protocol.OPENAI, input_price_per_1m=3.0, output_price_per_1m=6.0),
        a3=ModelConfig("k", "u", "m", Protocol.OPENAI),
        storage=StorageConfig(db_path=str(tmp_path / "x.db")),
    )
    run = _annotate_costs(_run_with_stages(), config)
    # WP1: 1000/1M*1 + 200/1M*2 = 0.001 + 0.0004 = 0.0014
    assert run.stages[0].cost_usd == pytest.approx(0.0014)
    # WP2: 2000/1M*3 + 500/1M*6 = 0.006 + 0.003 = 0.009
    assert run.stages[1].cost_usd == pytest.approx(0.009)
    # tool stage has no tokens → no cost
    assert run.stages[2].cost_usd is None
    assert run.total_cost_usd == pytest.approx(0.0104)


def test_annotate_costs_noop_without_pricing(tmp_path):
    config = AutumnConfig(
        a1=ModelConfig("k", "u", "m", Protocol.OPENAI),
        a2=ModelConfig("k", "u", "m", Protocol.OPENAI),
        a3=ModelConfig("k", "u", "m", Protocol.OPENAI),
        storage=StorageConfig(db_path=str(tmp_path / "x.db")),
    )
    run = _annotate_costs(_run_with_stages(), config)
    assert run.total_cost_usd is None
    assert all(s.cost_usd is None for s in run.stages)

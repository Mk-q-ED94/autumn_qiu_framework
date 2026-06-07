"""Tests for the validate-before-stream mode of WP1Tot.stream()."""
import pytest

from autumn.core.memory.backends import DictBackend
from autumn.core.memory.mom1 import Mom1
from autumn.core.memory.mom2 import Mom2
from autumn.core.memory.mom3 import Mom3
from autumn.core.memory.shared import SharedZone
from autumn.core.types import (
    InputType,
    MissionRoute,
    Protocol,
    SelectorResult,
    TaskType,
)
from autumn.core.workspace.wp1 import WP1Tot
from autumn.core.workspace.wp2 import WP2Tas
from autumn.core.workspace.wp3 import WP3Mis


# ── test doubles ──────────────────────────────────────────────────────────────


class _CompleteOnlyAPI:
    """API stub for the validated-stream path — only complete() is exercised.

    Records that stream_complete() was NOT used so we can assert the
    validate-before-stream code never streams from the workspace mid-pipeline.
    """

    protocol = Protocol.OPENAI

    def __init__(self, response: str):
        self.response = response
        self.streamed = False

    async def complete(self, messages, **kwargs):
        return self.response

    async def stream_complete(self, messages, **kwargs):
        self.streamed = True
        if False:
            yield  # type: ignore


class _PassingChecker:
    async def inspect(self, output, memory): return True, ""
    async def validate(self, output, memory): return True, output


class _CorrectingChecker:
    """Validator that rewrites the output to ``replacement``."""

    def __init__(self, replacement: str):
        self.replacement = replacement
        self.validate_calls = 0

    async def inspect(self, output, memory): return True, ""

    async def validate(self, output, memory):
        self.validate_calls += 1
        return True, self.replacement


class _StubSelector:
    def __init__(self, result):
        self._r = result

    async def classify_and_maybe_confirm(self, inp, interaction):
        return self._r


def _memories():
    shared = SharedZone(DictBackend())
    mom2 = Mom2(DictBackend(), shared)
    mom3 = Mom3(DictBackend(), shared)
    mom1 = Mom1(DictBackend(), mom2, mom3)
    return mom1, mom2, mom3


def _make_wp1(*, task_response="task result long enough to pass rule check.",
              mission_response="mission answer long enough to pass rule check.",
              sel_result=None, checker=None,
              headless_route=MissionRoute.DIRECT):
    mom1, mom2, mom3 = _memories()
    wp2_api = _CompleteOnlyAPI(task_response)
    wp3_api = _CompleteOnlyAPI(mission_response)
    wp1_api = _CompleteOnlyAPI("")
    wp2 = WP2Tas(wp2_api, mom2)
    wp3 = WP3Mis(wp3_api, mom3)
    wp1 = WP1Tot(
        api=wp1_api, memory=mom1, wp2=wp2, wp3=wp3,
        headless_mission_route=headless_route,
        validate_before_stream=True,
    )
    wp1.selector = _StubSelector(
        sel_result or SelectorResult(InputType.TASK, 0.95, TaskType.CODE)
    )
    wp1.checker = checker
    return wp1, wp2, wp3, mom1


# ── behavioural tests ────────────────────────────────────────────────────────


async def test_validated_stream_returns_full_output_in_chunks():
    text = "A precise validated answer that is longer than chunk_size for sure."
    wp1, _, _, _ = _make_wp1(task_response=text, checker=_PassingChecker())
    chunks = [tok async for tok in wp1.stream("do x", chunk_size=8)]
    assert "".join(chunks) == text
    assert len(chunks) > 1  # the output was actually split, not delivered in one piece


async def test_validated_stream_runs_checker_before_streaming():
    """Checker's validate() must run; its rewritten output is what gets streamed."""
    wp1, _, _, _ = _make_wp1(
        task_response="original poor answer that is long enough.",
        checker=_CorrectingChecker(replacement="corrected good answer"),
    )
    full = "".join([t async for t in wp1.stream("do x", chunk_size=64)])
    assert full == "corrected good answer"


async def test_validated_stream_persists_history_once():
    """process_with_trace appends history; stream() must not duplicate it."""
    wp1, _, _, mom1 = _make_wp1(
        task_response="some valid output content here for length.",
        checker=_PassingChecker(),
    )
    async for _ in wp1.stream("do something"):
        pass
    history = await mom1.get_history()
    matching = [h for h in history if h.get("input") == "do something"]
    assert len(matching) == 1


async def test_validated_stream_records_task_type_in_history():
    wp1, _, _, mom1 = _make_wp1(
        task_response="answer long enough to pass.",
        sel_result=SelectorResult(InputType.TASK, 0.9, TaskType.CODE),
        checker=_PassingChecker(),
    )
    async for _ in wp1.stream("write code"):
        pass
    history = await mom1.get_history()
    assert history[-1]["type"] == "task"


async def test_validated_stream_records_mission_route_in_history():
    wp1, _, _, mom1 = _make_wp1(
        mission_response="answer long enough to pass.",
        sel_result=SelectorResult(InputType.MISSION, 0.9, None),
        checker=_PassingChecker(),
        headless_route=MissionRoute.DIRECT,
    )
    async for _ in wp1.stream("hi", mission_route=MissionRoute.DIRECT):
        pass
    history = await mom1.get_history()
    assert history[-1]["route"] == "direct"


async def test_validated_stream_uses_complete_not_stream_complete():
    """In validate-before-stream mode, no live tokens flow; workspace complete() is used."""
    wp1, wp2, wp3, _ = _make_wp1(
        task_response="answer that is sufficiently long to pass rule check.",
        sel_result=SelectorResult(InputType.TASK, 0.95, None),
        checker=_PassingChecker(),
    )
    async for _ in wp1.stream("task"):
        pass
    assert wp2.api.streamed is False


async def test_default_validate_before_stream_is_true():
    """The flag defaults to True so users get validated output by default."""
    from autumn.core.config import AutumnConfig, ModelConfig
    from autumn.core.types import Protocol as P
    cfg = AutumnConfig(
        a1=ModelConfig("k", "u", "m", P.OPENAI),
        a2=ModelConfig("k", "u", "m", P.OPENAI),
        a3=ModelConfig("k", "u", "m", P.OPENAI),
    )
    assert cfg.validate_before_stream is True


async def test_config_env_var_can_disable_validate_before_stream(monkeypatch):
    from autumn.core.config import AutumnConfig

    for var in ["A1_API_KEY", "A1_BASE_URL", "A1_MODEL",
                "A2_API_KEY", "A2_BASE_URL", "A2_MODEL",
                "A3_API_KEY", "A3_BASE_URL", "A3_MODEL"]:
        monkeypatch.setenv(var, "x")
    monkeypatch.setenv("VALIDATE_BEFORE_STREAM", "false")
    cfg = AutumnConfig.from_env()
    assert cfg.validate_before_stream is False


async def test_legacy_live_path_still_works():
    """Confirm the live-streaming path is preserved when the flag is False."""
    from autumn.core.workspace.wp1 import WP1Tot

    mom1, mom2, mom3 = _memories()

    class _StreamingAPI:
        protocol = Protocol.OPENAI
        async def complete(self, messages, **kwargs): return "x"
        async def stream_complete(self, messages, **kwargs):
            for tok in ["live ", "tokens"]:
                yield tok

    wp2 = WP2Tas(_StreamingAPI(), mom2)
    wp3 = WP3Mis(_StreamingAPI(), mom3)
    wp1 = WP1Tot(api=None, memory=mom1, wp2=wp2, wp3=wp3,
                 validate_before_stream=False)
    wp1.selector = _StubSelector(SelectorResult(InputType.TASK, 0.95, None))
    wp1.checker = _PassingChecker()
    chunks = [t async for t in wp1.stream("x")]
    assert "".join(chunks) == "live tokens"

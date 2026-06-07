"""Direct unit tests for the ``Autumn`` framework facade.

These exercise the public surface that was previously only reachable via
stubbed mocks in the server tests — describe_terrs, classify_intent,
end_session, add_memory_skills — to lock in their behaviour against
future refactors.
"""
import pytest

from autumn import Autumn
from autumn.core.components.skill import Skill
from autumn.core.components.terr import Terr
from autumn.core.components.tool import Tool, ToolParameter
from autumn.core.config import AutumnConfig, ModelConfig, StorageConfig
from autumn.core.types import InputType, MissionRoute, Protocol, SelectorResult, TaskType


# ── helpers ───────────────────────────────────────────────────────────────────


def _config(tmp_path) -> AutumnConfig:
    mc = ModelConfig("k", "http://localhost", "m", Protocol.OPENAI)
    return AutumnConfig(
        a1=mc, a2=mc, a3=mc,
        storage=StorageConfig(db_path=str(tmp_path / "mem.db")),
    )


class _StubSelector:
    def __init__(self, result: SelectorResult):
        self._result = result

    async def classify_and_maybe_confirm(self, user_input, interaction):
        return self._result


# ── describe_terrs ────────────────────────────────────────────────────────────


def test_describe_terrs_serializes_tools_skills_mcps(tmp_path):
    autumn = Autumn(_config(tmp_path))
    fetch = Tool(
        "fetch", "Fetch a URL", lambda url: url,
        [ToolParameter("url", "string", "URL")],
    )
    summarise = Skill("summarise", "Summarise text", lambda **kw: "ok")
    terr = Terr("content", "Content ops", tools=[fetch], skills=[summarise])
    autumn.register_terr(terr)

    summaries = autumn.describe_terrs()
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["name"] == "content"
    assert summary["description"] == "Content ops"
    assert summary["tools"][0]["name"] == "fetch"
    assert summary["tools"][0]["parameters"][0]["name"] == "url"
    assert summary["skills"][0]["name"] == "summarise"
    assert summary["mcps"] == []


def test_describe_terrs_empty_when_no_domains_registered(tmp_path):
    autumn = Autumn(_config(tmp_path))
    assert autumn.describe_terrs() == []


# ── classify_intent ───────────────────────────────────────────────────────────


async def test_classify_intent_returns_selector_and_route(tmp_path):
    autumn = Autumn(_config(tmp_path))
    autumn.wp1.selector = _StubSelector(
        SelectorResult(InputType.MISSION, 0.91, None, reasoning="looks like chat"),
    )

    sel, route = await autumn.classify_intent(
        "tell me a joke", mission_route=MissionRoute.DIRECT,
    )
    assert sel.input_type == InputType.MISSION
    assert sel.confidence == 0.91
    assert sel.reasoning == "looks like chat"
    # Explicit mission_route is forwarded only when input is a mission.
    assert route == MissionRoute.DIRECT


async def test_classify_intent_explicit_input_type_skips_selector(tmp_path):
    """When the caller already knows the input_type, the classifier is bypassed
    and a synthetic SelectorResult with confidence=1.0 is returned."""
    autumn = Autumn(_config(tmp_path))
    autumn.wp1.selector = _StubSelector(  # would be wrong if consulted
        SelectorResult(InputType.MISSION, 0.5, None),
    )

    sel, route = await autumn.classify_intent(
        "anything", input_type=InputType.TASK, task_type=TaskType.CODE,
    )
    assert sel.input_type == InputType.TASK
    assert sel.task_type == TaskType.CODE
    assert sel.confidence == 1.0
    assert route is None


# ── add_memory_skills ─────────────────────────────────────────────────────────


def test_add_memory_skills_registers_recall_and_remember(tmp_path):
    autumn = Autumn(_config(tmp_path))
    autumn.add_memory_skills("shared")

    names = {name for name, obj in autumn.plugins.all().items() if isinstance(obj, Skill)}
    assert "recall" in names
    assert "remember" in names


def test_add_memory_skills_accepts_each_known_area(tmp_path):
    for area in ("shared", "mom1", "mom2", "mom3"):
        # Fresh framework per area so duplicate names don't collide in PluginLoader.
        sub = tmp_path / area
        sub.mkdir()
        a = Autumn(_config(sub))
        a.add_memory_skills(area)
        names = {name for name, obj in a.plugins.all().items() if isinstance(obj, Skill)}
        assert {"recall", "remember"} <= names


def test_add_memory_skills_unknown_area_raises(tmp_path):
    autumn = Autumn(_config(tmp_path))
    with pytest.raises(ValueError, match="Unknown memory area"):
        autumn.add_memory_skills("nonexistent")


# ── end_session ───────────────────────────────────────────────────────────────


async def test_end_session_invokes_clear_session_on_each_mom(tmp_path):
    """Each Mom whose backend exposes clear_session() should see it called once."""
    autumn = Autumn(_config(tmp_path))
    cleared: list[str] = []

    class _Recorder:
        def __init__(self, label):
            self.label = label

        async def clear_session(self):
            cleared.append(self.label)

    autumn.mom1._backend = _Recorder("mom1")
    autumn.mom2._backend = _Recorder("mom2")
    autumn.mom3._backend = _Recorder("mom3")

    await autumn.end_session()
    assert cleared == ["mom1", "mom2", "mom3"]


async def test_end_session_tolerates_backend_without_clear_session(tmp_path):
    """A backend that lacks clear_session() (e.g. plain DictBackend) must not crash."""
    autumn = Autumn(_config(tmp_path))

    class _Bare:
        pass

    autumn.mom1._backend = _Bare()
    autumn.mom2._backend = _Bare()
    autumn.mom3._backend = _Bare()
    # No raise.
    await autumn.end_session()

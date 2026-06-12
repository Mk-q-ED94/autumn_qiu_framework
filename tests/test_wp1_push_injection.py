"""P4b tests: turn auto-injection of 4D push context into WP1/WP2/WP3.

``WP1Tot.process_with_trace`` accepts ``push_context/push_count/push_ms``; when
non-empty it inserts a ``kind="push"`` stage at the head of the trace and passes
the fragment as ``turn_context`` to WP2/WP3 so active CONSTRAIN/REMIND memories
gate model behaviour without touching the base configuration.

``Autumn._compute_push`` runs the push engine and produces the tuple that the
four public entry points (process, process_with_trace, stream, stream_with_trace)
hand to WP1 at the start of every turn.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from autumn import Autumn
from autumn.core.config import AutumnConfig, BehaviorConfig, ModelConfig
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea
from autumn.core.memory.dimensions import Use, UseMode
from autumn.core.memory.project import ProjectMemory
from autumn.core.memory.shared import SharedZone
from autumn.core.types import InputType, Protocol, WorkflowRun
from autumn.core.workspace.wp4 import WP4Mem


# ── helpers ───────────────────────────────────────────────────────────────────

def _cfg(push: bool) -> AutumnConfig:
    m = ModelConfig(api_key="k", base_url="http://x", model="m", protocol=Protocol("openai"))
    return AutumnConfig(a1=m, a2=m, a3=m, behavior=BehaviorConfig(fourd_push_on_turn=push))


async def _make_autumn(tmp_path, push: bool) -> Autumn:
    cfg = _cfg(push)
    cfg.storage.db_path = str(tmp_path / "mem.db")
    return Autumn(cfg)


# ── Autumn._compute_push ─────────────────────────────────────────────────────

async def test_compute_push_disabled_returns_empty(tmp_path):
    async with await _make_autumn(tmp_path, push=False) as autumn:
        fragment, count, ms = await autumn._compute_push("anything")
    assert fragment == ""
    assert count == 0
    assert ms == 0.0


async def test_compute_push_enabled_no_memories_returns_empty(tmp_path):
    async with await _make_autumn(tmp_path, push=True) as autumn:
        fragment, count, ms = await autumn._compute_push("deploy now")
    assert fragment == ""
    assert count == 0


async def test_compute_push_fires_constrain_memory(tmp_path):
    async with await _make_autumn(tmp_path, push=True) as autumn:
        await autumn.mom1.append_history("no prod writes", use=Use(mode=UseMode.CONSTRAIN))
        fragment, count, ms = await autumn._compute_push("deploy to prod")
    assert count == 1
    assert "no prod writes" in fragment
    assert "Active constraints" in fragment


# ── WP1 push stage in trace ───────────────────────────────────────────────────

def _make_wp1_with_mocks():
    """Build a WP1Tot with minimal async mock WP2/WP3 (no real API calls)."""
    from autumn.core.workspace.wp1 import WP1Tot
    from autumn.core.workspace.wp2 import WP2Tas
    from autumn.core.workspace.wp3 import WP3Mis

    class _FakeAPI:
        last_usage = None
        async def complete(self, messages, **kw):
            return "result"

    class _FakeMem:
        shared = MagicMock()
        shared.set = AsyncMock()
        async def append_history(self, *a, **kw): pass
        async def get_history(self): return []

    wp2 = WP2Tas(_FakeAPI(), _FakeMem())
    wp3 = WP3Mis(_FakeAPI(), _FakeMem())
    wp1 = WP1Tot(
        _FakeAPI(),
        _FakeMem(),
        wp2=wp2,
        wp3=wp3,
        headless_mission_route="direct",
    )
    return wp1


async def test_push_stage_absent_when_no_context():
    """No push stage when push_context is empty (the default)."""
    wp1 = _make_wp1_with_mocks()
    run = await wp1.process_with_trace("hello", input_type=InputType.TASK)
    push_stages = [s for s in run.stages if s.kind == "push"]
    assert push_stages == []


async def test_push_stage_present_when_context_provided():
    """When push_context is non-empty, first stage has kind='push' and workspace='WP4'."""
    wp1 = _make_wp1_with_mocks()
    run = await wp1.process_with_trace(
        "hello",
        input_type=InputType.TASK,
        push_context="Active constraints (must follow):\n- no prod writes",
        push_count=1,
        push_ms=3.5,
    )
    assert run.stages[0].kind == "push"
    assert run.stages[0].workspace == "WP4"
    assert run.stages[0].id == "wp4.push"
    assert "1" in run.stages[0].detail
    assert run.stages[0].duration_ms == 3.5


# ── turn_context injected into WP2 system prompt ─────────────────────────────

async def test_wp2_run_plain_injects_turn_context():
    """turn_context appears in the system message sent to the API."""
    from autumn.core.workspace.wp2 import WP2Tas
    from autumn.core.memory.base import MemoryArea

    captured: list = []

    class _FakeAPI:
        last_usage = None
        async def complete(self, messages):
            captured.extend(messages)
            return "done"

    area = MemoryArea("wp2", DictBackend())
    wp2 = WP2Tas(_FakeAPI(), area)
    await wp2.process_with_trace("do the thing", turn_context="Active constraints:\n- never delete")

    sys_msg = next(m for m in captured if m.role.value == "system")
    assert "Active constraints" in sys_msg.content
    assert "never delete" in sys_msg.content


# ── turn_context injected into WP3 system prompt ─────────────────────────────

async def test_wp3_answer_directly_injects_turn_context():
    from autumn.core.workspace.wp3 import WP3Mis

    captured: list = []

    class _FakeAPI:
        last_usage = None
        async def complete(self, messages):
            captured.extend(messages)
            return "answer"

    class _FakeMom3:
        shared = MagicMock()
        shared.set = AsyncMock()
        async def append_history(self, *a, **kw): pass

    wp3 = WP3Mis(_FakeAPI(), _FakeMom3())
    await wp3.answer_directly("what should I do?", turn_context="Active reminders:\n- prefer metric")

    sys_msg = next(m for m in captured if m.role.value == "system")
    assert "Active reminders" in sys_msg.content
    assert "prefer metric" in sys_msg.content


async def test_wp3_convert_to_task_injects_turn_context():
    from autumn.core.workspace.wp3 import WP3Mis

    captured: list = []

    class _FakeAPI:
        last_usage = None
        async def complete(self, messages):
            captured.extend(messages)
            return "## Task\n- step 1"

    class _FakeMom3:
        shared = MagicMock()
        shared.set = AsyncMock()
        async def append_history(self, *a, **kw): pass

    wp3 = WP3Mis(_FakeAPI(), _FakeMom3())
    await wp3.convert_to_task("do stuff", turn_context="Active constraints:\n- no sudo")

    sys_msg = next(m for m in captured if m.role.value == "system")
    assert "no sudo" in sys_msg.content


# ── base system unchanged when no context ────────────────────────────────────

async def test_wp2_no_turn_context_leaves_system_unchanged():
    from autumn.core.workspace.wp2 import WP2Tas, _DEFAULT_SYSTEM

    captured: list = []

    class _FakeAPI:
        last_usage = None
        async def complete(self, messages):
            captured.extend(messages)
            return "done"

    area = MemoryArea("wp2", DictBackend())
    wp2 = WP2Tas(_FakeAPI(), area)
    await wp2.process_with_trace("do the thing")

    sys_msg = next(m for m in captured if m.role.value == "system")
    assert sys_msg.content == _DEFAULT_SYSTEM
    assert "---" not in sys_msg.content


# ── Autumn._compute_push wires into process_with_trace ───────────────────────

async def test_autumn_compute_push_feeds_wp1_trace(tmp_path):
    """When push fires, Autumn.process_with_trace includes the push stage."""
    cfg = _cfg(push=True)
    cfg.storage.db_path = str(tmp_path / "mem.db")
    async with Autumn(cfg) as autumn:
        await autumn.mom1.append_history("no prod writes", use=Use(mode=UseMode.CONSTRAIN))
        # Patch wp1.process_with_trace to capture kwargs without real API calls.
        received: dict = {}
        _original = autumn.wp1.process_with_trace

        async def _capture(*args, **kwargs):
            received.update(kwargs)
            # Return a minimal WorkflowRun stub.
            from autumn.core.types import WorkflowRun, InputType as IT
            return WorkflowRun(
                output="ok", input_type=IT.TASK, route=None, stages=[]
            )

        autumn.wp1.process_with_trace = _capture
        await autumn.process_with_trace("deploy to prod", input_type=InputType.TASK)

    assert received.get("push_context") != ""
    assert received.get("push_count") == 1


async def test_autumn_compute_push_empty_when_disabled(tmp_path):
    """When push is off, Autumn passes empty push_context to wp1."""
    cfg = _cfg(push=False)
    cfg.storage.db_path = str(tmp_path / "mem.db")
    async with Autumn(cfg) as autumn:
        await autumn.mom1.append_history("no prod writes", use=Use(mode=UseMode.CONSTRAIN))
        received: dict = {}
        _original = autumn.wp1.process_with_trace

        async def _capture(*args, **kwargs):
            received.update(kwargs)
            from autumn.core.types import WorkflowRun, InputType as IT
            return WorkflowRun(
                output="ok", input_type=IT.TASK, route=None, stages=[]
            )

        autumn.wp1.process_with_trace = _capture
        await autumn.process_with_trace("deploy to prod", input_type=InputType.TASK)

    assert received.get("push_context") == ""
    assert received.get("push_count") == 0

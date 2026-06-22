"""End-to-end 4D-push tests: the full stitch through ``Autumn.process()``.

The existing push tests cover each layer in isolation — ``activate_push``
(candidate filtering / gating), ``render_push_context`` (rendering), the WP1
push stage, and WP2/WP3 ``turn_context`` injection — or they mock
``wp1.process_with_trace`` outright. None drives the *whole real chain* through
the public entry point.

These do. With a fired CONSTRAIN/REMIND memory in mom1 and capturing fake model
APIs on the workspaces, they assert the activated memory's text actually lands
in the system prompt the workspace sends to its model:

    Autumn.process() → _compute_push → WP4.activate_push → render_push_context
        → WP1.process_with_trace → WP2 / WP3 → the real model prompt

That is the contract a user relies on when they switch ``fourd_push_on_turn``
on: a guardrail memory genuinely reaches the model, not just the trace.
"""
from autumn import Autumn
from autumn.core.config import AutumnConfig, BehaviorConfig, ModelConfig
from autumn.core.memory.dimensions import Use, UseMode
from autumn.core.types import InputType, MissionRoute, Protocol, WorkflowRun


# ── fakes / wiring ──────────────────────────────────────────────────────────────

class _CapturingAPI:
    """Fake model API that records every prompt it is asked to complete."""

    def __init__(self, reply="ok"):
        self.protocol = Protocol.OPENAI
        self.last_usage = None
        self._reply = reply
        self.prompts: list[list] = []

    async def complete(self, messages, **kw):
        self.prompts.append(list(messages))
        return self._reply

    def system_texts(self) -> list[str]:
        """Every system-role message content this API was asked to complete."""
        return [
            m.content
            for msgs in self.prompts
            for m in msgs
            if m.role.value == "system"
        ]


def _cfg(push: bool) -> AutumnConfig:
    m = ModelConfig(api_key="k", base_url="http://x", model="m", protocol=Protocol("openai"))
    cfg = AutumnConfig(a1=m, a2=m, a3=m, behavior=BehaviorConfig(fourd_push_on_turn=push))
    # Keep only the real push path producing model prompts: no A4 archive call.
    cfg.behavior.archive_executions = False
    return cfg


def _wire(autumn: Autumn) -> tuple[_CapturingAPI, _CapturingAPI, _CapturingAPI]:
    """Swap each workspace's model API for a capturing fake and silence the
    checkers — so the only system prompts produced are the ones the real push
    path feeds into WP2/WP3."""
    a1 = _CapturingAPI(reply="plan step")
    a2 = _CapturingAPI(reply="done")
    a3 = _CapturingAPI(reply="answer")
    autumn.wp1.api = a1
    autumn.wp2.api = a2
    autumn.wp3.api = a3
    autumn.wp1.checker = None
    autumn.wp2.checker = None
    autumn.wp3.checker = None
    return a1, a2, a3


# ── direct (mission) route: constraint reaches the WP3 prompt ────────────────────

async def test_push_constraint_reaches_wp3_prompt_end_to_end(tmp_path):
    cfg = _cfg(push=True)
    cfg.storage.db_path = str(tmp_path / "mem.db")
    async with Autumn(cfg) as autumn:
        _a1, _a2, a3 = _wire(autumn)
        await autumn.mom1.append_history(
            "never write to prod directly", use=Use(mode=UseMode.CONSTRAIN),
        )
        out = await autumn.process(
            "deploy the release",
            input_type=InputType.MISSION,
            mission_route=MissionRoute.DIRECT,
        )
    assert out == "answer"  # WP3 actually produced the turn's answer
    sys_texts = a3.system_texts()
    assert any("never write to prod directly" in t for t in sys_texts)
    assert any("Active constraints (must follow):" in t for t in sys_texts)


async def test_push_reminder_reaches_wp3_prompt_end_to_end(tmp_path):
    cfg = _cfg(push=True)
    cfg.storage.db_path = str(tmp_path / "mem.db")
    async with Autumn(cfg) as autumn:
        _a1, _a2, a3 = _wire(autumn)
        await autumn.mom1.append_history(
            "user prefers metric units", use=Use(mode=UseMode.REMIND),
        )
        await autumn.process(
            "what's the distance?",
            input_type=InputType.MISSION,
            mission_route=MissionRoute.DIRECT,
        )
    sys_texts = a3.system_texts()
    assert any("user prefers metric units" in t for t in sys_texts)
    assert any("Active reminders:" in t for t in sys_texts)


# ── task route: constraint reaches the WP2 prompt ────────────────────────────────

async def test_push_constraint_reaches_wp2_prompt_end_to_end(tmp_path):
    cfg = _cfg(push=True)
    cfg.storage.db_path = str(tmp_path / "mem.db")
    async with Autumn(cfg) as autumn:
        _a1, a2, _a3 = _wire(autumn)
        await autumn.mom1.append_history(
            "never delete user data", use=Use(mode=UseMode.CONSTRAIN),
        )
        await autumn.process("clean up the database", input_type=InputType.TASK)
    assert any("never delete user data" in t for t in a2.system_texts())


# ── negative: push off → nothing injected, even with a CONSTRAIN memory ──────────

async def test_push_off_constraint_absent_from_prompt_end_to_end(tmp_path):
    cfg = _cfg(push=False)
    cfg.storage.db_path = str(tmp_path / "mem.db")
    async with Autumn(cfg) as autumn:
        _a1, _a2, a3 = _wire(autumn)
        await autumn.mom1.append_history(
            "never write to prod directly", use=Use(mode=UseMode.CONSTRAIN),
        )
        await autumn.process(
            "deploy the release",
            input_type=InputType.MISSION,
            mission_route=MissionRoute.DIRECT,
        )
    sys_texts = a3.system_texts()
    assert not any("never write to prod directly" in t for t in sys_texts)
    assert not any("Active constraints" in t for t in sys_texts)


# ── a CONTEXT-mode memory must NOT push, even end-to-end ─────────────────────────

async def test_context_memory_does_not_push_end_to_end(tmp_path):
    cfg = _cfg(push=True)
    cfg.storage.db_path = str(tmp_path / "mem.db")
    async with Autumn(cfg) as autumn:
        _a1, _a2, a3 = _wire(autumn)
        # CONTEXT is pull-only — it must never be auto-surfaced by the push engine.
        await autumn.mom1.append_history(
            "just some background", use=Use(mode=UseMode.CONTEXT),
        )
        await autumn.process(
            "hello there",
            input_type=InputType.MISSION,
            mission_route=MissionRoute.DIRECT,
        )
    assert not any("just some background" in t for t in a3.system_texts())


# ── streaming entry points also feed the push engine ─────────────────────────────

def _stub_wp1_stream(received: dict):
    """A wp1.stream_with_trace replacement that records the push kwargs and
    yields a minimal chunk + WorkflowRun, so the streaming entry points can be
    exercised without real model calls."""
    async def _capture(*args, **kwargs):
        received.update(kwargs)
        yield "chunk"
        yield WorkflowRun(output="ok", input_type=InputType.MISSION, route=None, stages=[])
    return _capture


async def test_stream_with_trace_feeds_push(tmp_path):
    cfg = _cfg(push=True)
    cfg.storage.db_path = str(tmp_path / "mem.db")
    async with Autumn(cfg) as autumn:
        await autumn.mom1.append_history("rule X", use=Use(mode=UseMode.CONSTRAIN))
        received: dict = {}
        autumn.wp1.stream_with_trace = _stub_wp1_stream(received)
        events = [e async for e in autumn.stream_with_trace(
            "deploy", input_type=InputType.MISSION)]
    assert received.get("push_count") == 1
    assert "rule X" in received.get("push_context", "")
    assert any(isinstance(e, WorkflowRun) for e in events)


async def test_stream_feeds_push(tmp_path):
    cfg = _cfg(push=True)
    cfg.storage.db_path = str(tmp_path / "mem.db")
    async with Autumn(cfg) as autumn:
        await autumn.mom1.append_history("rule Y", use=Use(mode=UseMode.CONSTRAIN))
        received: dict = {}
        # Autumn.stream() also drives wp1.stream_with_trace under the hood.
        autumn.wp1.stream_with_trace = _stub_wp1_stream(received)
        chunks = [c async for c in autumn.stream("deploy", input_type=InputType.MISSION)]
    assert received.get("push_count") == 1
    assert "rule Y" in received.get("push_context", "")
    assert "chunk" in chunks  # str chunks flow through; the WorkflowRun is filtered out


async def test_stream_off_feeds_no_push(tmp_path):
    cfg = _cfg(push=False)
    cfg.storage.db_path = str(tmp_path / "mem.db")
    async with Autumn(cfg) as autumn:
        await autumn.mom1.append_history("rule Z", use=Use(mode=UseMode.CONSTRAIN))
        received: dict = {}
        autumn.wp1.stream_with_trace = _stub_wp1_stream(received)
        _ = [e async for e in autumn.stream_with_trace(
            "deploy", input_type=InputType.MISSION)]
    assert received.get("push_context") == ""
    assert received.get("push_count") == 0

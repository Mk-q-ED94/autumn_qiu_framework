"""Turn-start Mom1 *pull* injection — the read half of 4D memory.

``Autumn._compute_recall`` reads recent Mom1 cross-turn history (the read-all
zone that every turn is written to but was never read back on the default path)
and renders it into a fragment that ``_compute_turn_context`` threads into the
executor's system prompt, alongside the push fragment. This closes the gap where
Mom1's "reads all" authority was inert and WP2/WP3 ran blind to the conversation.
"""
from autumn import Autumn
from autumn.core.config import AutumnConfig, BehaviorConfig, ModelConfig
from autumn.core.types import InputType, Protocol, WorkflowRun


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
        return [
            m.content
            for msgs in self.prompts
            for m in msgs
            if m.role.value == "system"
        ]


def _cfg(tmp_path, pull: bool = True) -> AutumnConfig:
    m = ModelConfig(api_key="k", base_url="http://x", model="m", protocol=Protocol("openai"))
    cfg = AutumnConfig(a1=m, a2=m, a3=m, behavior=BehaviorConfig(fourd_pull_on_turn=pull))
    cfg.storage.db_path = str(tmp_path / "mem.db")
    return cfg


def _wire(autumn: Autumn) -> tuple[_CapturingAPI, _CapturingAPI, _CapturingAPI]:
    a1, a2, a3 = _CapturingAPI("plan"), _CapturingAPI("done"), _CapturingAPI("answer")
    autumn.wp1.api = a1
    autumn.wp2.api = a2
    autumn.wp3.api = a3
    autumn.wp1.checker = autumn.wp2.checker = autumn.wp3.checker = None
    return a1, a2, a3


# ── Autumn._compute_recall ────────────────────────────────────────────────────

async def test_compute_recall_empty_mom1_returns_empty(tmp_path):
    async with Autumn(_cfg(tmp_path)) as autumn:
        fragment, count, ms = await autumn._compute_recall("anything")
    assert fragment == ""
    assert count == 0


async def test_compute_recall_surfaces_mom1_history(tmp_path):
    async with Autumn(_cfg(tmp_path)) as autumn:
        await autumn.mom1.append_history({"input": "what is the deadline", "output": "Friday"})
        fragment, count, ms = await autumn._compute_recall("remind me of the deadline")
    assert count == 1
    assert "what is the deadline" in fragment
    assert "Friday" in fragment


async def test_compute_recall_disabled_returns_empty(tmp_path):
    async with Autumn(_cfg(tmp_path, pull=False)) as autumn:
        await autumn.mom1.append_history({"input": "q", "output": "a"})
        fragment, count, ms = await autumn._compute_recall("q")
    assert fragment == ""
    assert count == 0


# ── wires into the turn (process_with_trace) ──────────────────────────────────

async def test_recall_feeds_wp1_turn_context(tmp_path):
    """A populated Mom1 reaches WP1 as recall_count + a non-empty push_context."""
    async with Autumn(_cfg(tmp_path)) as autumn:
        await autumn.mom1.append_history({"input": "deploy plan", "output": "ship Friday"})

        received: dict = {}

        async def _capture(*args, **kwargs):
            received.update(kwargs)
            return WorkflowRun(output="ok", input_type=InputType.TASK, route=None, stages=[])

        autumn.wp1.process_with_trace = _capture
        await autumn.process_with_trace("when do we ship?", input_type=InputType.TASK)

    assert received.get("recall_count") == 1
    assert "ship Friday" in received.get("push_context", "")


async def test_recall_reaches_wp2_prompt_and_trace_end_to_end(tmp_path):
    """End-to-end: prior Mom1 turn reaches the WP2 system prompt AND a recall
    stage shows up in the trace of a real turn."""
    cfg = _cfg(tmp_path)
    cfg.behavior.archive_executions = False  # isolate the pull path
    async with Autumn(cfg) as autumn:
        _a1, a2, _a3 = _wire(autumn)
        await autumn.mom1.append_history({"input": "prior question", "output": "prior answer"})
        run = await autumn.process_with_trace("follow-up", input_type=InputType.TASK)

    assert any("prior answer" in t for t in a2.system_texts())
    recall_stages = [s for s in run.stages if s.id == "wp4.recall"]
    assert len(recall_stages) == 1
    assert recall_stages[0].workspace == "WP4"
    assert "1" in recall_stages[0].detail


async def test_recall_and_push_both_fire_on_one_real_turn(tmp_path):
    """The 'effect, not wiring' guarantee for the memory pipeline: a single real
    turn surfaces BOTH halves of 4D memory — prior conversation (pull) and an
    active constraint (push) — into the executor's prompt and the trace."""
    from autumn.core.memory.dimensions import Use, UseMode

    cfg = _cfg(tmp_path)
    cfg.behavior.archive_executions = False
    async with Autumn(cfg) as autumn:
        _a1, a2, _a3 = _wire(autumn)
        await autumn.mom1.append_history({"input": "earlier ask", "output": "earlier result"})
        await autumn.mom1.append_history(
            "never force-push to main", use=Use(mode=UseMode.CONSTRAIN)
        )
        run = await autumn.process_with_trace("next step?", input_type=InputType.TASK)

    stage_ids = {s.id for s in run.stages}
    assert "wp4.recall" in stage_ids  # pull half fired
    assert "wp4.push" in stage_ids    # push half fired
    sys = "\n".join(a2.system_texts())
    assert "earlier result" in sys              # recalled context reached the executor
    assert "never force-push to main" in sys    # active constraint reached the executor

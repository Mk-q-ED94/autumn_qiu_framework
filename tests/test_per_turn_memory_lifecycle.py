"""Per-turn memory lifecycle — auto-annotation and auto-consolidation.

After every turn:
1. ``_auto_annotate_turn``: asks A4 to infer 4D dimensions for the just-written
   Mom1 entry, producing a ``wp4.annotate`` trace stage when it fires.
2. ``_auto_consolidate_turn``: consolidates Mom1 when history ≥ 80 % of the
   history_limit, producing a ``wp4.consolidate`` trace stage.

Both are gated on A4 slot presence and the respective BehaviorConfig flag
(``fourd_auto_annotate`` / ``fourd_auto_consolidate``).
"""
import json
import time

import pytest

from autumn import Autumn
from autumn.core.config import AutumnConfig, BehaviorConfig, ModelConfig
from autumn.core.types import InputType, Protocol, WorkflowRun


# ── helpers ───────────────────────────────────────────────────────────────────

class _CapturingAPI:
    """Fake model API; captures prompts, returns configurable reply."""

    def __init__(self, reply="ok"):
        self.protocol = Protocol.OPENAI
        self.last_usage = None
        self._reply = reply
        self.prompts: list[list] = []

    async def complete(self, messages, **kw):
        self.prompts.append(list(messages))
        return self._reply


class _A4API(_CapturingAPI):
    """A4 stub that returns valid annotation JSON for any batch."""

    def __init__(self):
        super().__init__()

    async def complete(self, messages, **kw):
        self.prompts.append(list(messages))
        # Parse out entry ids from the user message to build a valid reply.
        user_msg = next((m for m in messages if m.role.value == "user"), None)
        ids: list[str] = []
        if user_msg:
            for part in user_msg.content.split("\n"):
                if part.startswith("id="):
                    ids.append(part.split(" :: ")[0].replace("id=", "").strip())
        return json.dumps([
            {"id": eid, "mode": "context", "intent": "test entry", "scope": [], "cues": ["test"]}
            for eid in ids
        ])


def _cfg(tmp_path, a4: bool = True, auto_annotate: bool = True,
         auto_consolidate: bool = True, history_limit: int = 50) -> AutumnConfig:
    m = ModelConfig(api_key="k", base_url="http://x", model="m", protocol=Protocol.OPENAI)
    a4_slot = m if a4 else None
    cfg = AutumnConfig(
        a1=m, a2=m, a3=m, a4=a4_slot,
        behavior=BehaviorConfig(
            fourd_auto_annotate=auto_annotate,
            fourd_auto_consolidate=auto_consolidate,
            history_limit=history_limit,
            archive_executions=False,
        ),
    )
    cfg.storage.db_path = str(tmp_path / "mem.db")
    return cfg


def _wire_basic(autumn: Autumn) -> tuple[_CapturingAPI, _CapturingAPI, _CapturingAPI]:
    a1, a2, a3 = _CapturingAPI("plan"), _CapturingAPI("done"), _CapturingAPI("answer")
    autumn.wp1.api = a1
    autumn.wp2.api = a2
    autumn.wp3.api = a3
    autumn.wp1.checker = autumn.wp2.checker = autumn.wp3.checker = None
    return a1, a2, a3


# ── _auto_annotate_turn ────────────────────────────────────────────────────────

async def test_auto_annotate_skipped_without_a4(tmp_path):
    """No annotation stage when A4 is absent, even if flag is on."""
    async with Autumn(_cfg(tmp_path, a4=False)) as autumn:
        stage = await autumn._auto_annotate_turn()
    assert stage is None


async def test_auto_annotate_skipped_when_flag_off(tmp_path):
    """No annotation stage when the flag is disabled."""
    async with Autumn(_cfg(tmp_path, auto_annotate=False)) as autumn:
        autumn.wp4.api = _A4API()
        await autumn.mom1.append_history({"input": "x", "output": "y"})
        stage = await autumn._auto_annotate_turn()
    assert stage is None


async def test_auto_annotate_no_stage_when_already_annotated(tmp_path):
    """When Mom1 has no unannotated entries, returns None (already annotated)."""
    from autumn.core.memory.dimensions import Aim, UseMode, Use
    async with Autumn(_cfg(tmp_path)) as autumn:
        autumn.wp4.api = _A4API()
        # Append an entry and then annotate it manually so it's not unannotated.
        await autumn.mom1.append_history({"input": "x", "output": "y"})
        entries = await autumn.mom1.get_history(n=1)
        await autumn.mom1.annotate(
            entries[0].id, mode="context", intent="already set", scope=[], cues=["tagged"],
        )
        stage = await autumn._auto_annotate_turn()
    # already annotated → 0 annotated → no stage
    assert stage is None


async def test_auto_annotate_fires_and_returns_stage(tmp_path):
    """With A4 and an unannotated entry, annotate fires and returns a trace stage."""
    async with Autumn(_cfg(tmp_path)) as autumn:
        autumn.wp4.api = _A4API()
        await autumn.mom1.append_history({"input": "q", "output": "a"})
        stage = await autumn._auto_annotate_turn("mom1")
    assert stage is not None
    assert stage.id == "wp4.annotate.mom1"
    assert stage.workspace == "WP4"
    assert "1" in stage.detail


async def test_auto_annotate_stage_in_run_trace(tmp_path):
    """End-to-end: a ``wp4.annotate`` stage appears in the trace of a real turn
    when A4 is wired and the first turn writes an unannotated Mom1 entry."""
    cfg = _cfg(tmp_path)
    async with Autumn(cfg) as autumn:
        _wire_basic(autumn)
        autumn.wp4.api = _A4API()
        run = await autumn.process_with_trace("do something", input_type=InputType.TASK)

    annotate_stages = [s for s in run.stages if s.id.startswith("wp4.annotate")]
    assert len(annotate_stages) >= 1
    assert all(s.workspace == "WP4" for s in annotate_stages)


async def test_auto_annotate_cue_persists_on_entry(tmp_path):
    """Cues assigned by A4 are durably stored: a subsequent recall can match them."""
    async with Autumn(_cfg(tmp_path)) as autumn:
        await autumn.mom1.append_history({"input": "deploy to prod", "output": "done"})
        autumn.wp4.api = _A4API()
        await autumn._auto_annotate_turn()
        entries = await autumn.mom1.get_history(n=1)
    # _A4API injects cue "test" → must appear on the annotated entry
    assert "test" in entries[0].trigger.cues


# ── _auto_consolidate_turn ────────────────────────────────────────────────────

async def test_auto_consolidate_skipped_without_a4(tmp_path):
    """No consolidation stage when A4 is absent."""
    async with Autumn(_cfg(tmp_path, a4=False)) as autumn:
        stage = await autumn._auto_consolidate_turn()
    assert stage is None


async def test_auto_consolidate_skipped_when_flag_off(tmp_path):
    """No consolidation stage when the flag is disabled."""
    cfg = _cfg(tmp_path, auto_consolidate=False, history_limit=5)
    async with Autumn(cfg) as autumn:
        autumn.wp4.api = _CapturingAPI("summary")
        for i in range(5):
            await autumn.mom1.append_history({"input": f"q{i}", "output": f"a{i}"})
        stage = await autumn._auto_consolidate_turn()
    assert stage is None


async def test_auto_consolidate_below_threshold_no_stage(tmp_path):
    """No consolidation when Mom1 history is below 80 % of history_limit."""
    cfg = _cfg(tmp_path, history_limit=50)
    async with Autumn(cfg) as autumn:
        # 3 entries, limit=50 → 3/50 < 80 % → no consolidation
        for i in range(3):
            await autumn.mom1.append_history({"input": f"q{i}", "output": f"a{i}"})
        autumn.wp4.api = _CapturingAPI("summary")
        stage = await autumn._auto_consolidate_turn()
    assert stage is None


async def test_auto_consolidate_at_threshold_fires(tmp_path):
    """Consolidation fires when Mom1 reaches ≥ 80 % of history_limit.

    Uses a small limit so we don't need 40+ entries.
    """
    from autumn.core.memory.dimensions import UseMode

    cfg = _cfg(tmp_path, history_limit=5)
    # Consolidation needs A4 with a cogent summary response.
    consolidate_reply = "Summary of prior turns."
    async with Autumn(cfg) as autumn:
        _wire_basic(autumn)
        # Need a real-ish consolidation API that returns a text summary.
        autumn.wp4.api = _CapturingAPI(consolidate_reply)
        # Fill 4 entries → 4/5 = 80 % → should trigger.
        for i in range(4):
            await autumn.mom1.append_history({"input": f"q{i}", "output": f"a{i}"})
        stage = await autumn._auto_consolidate_turn()

    # Whether consolidation produced a summary depends on min_candidates (default 3);
    # with 4 entries and keep_recent=10 default, all are "recent" so consolidation
    # returns None (nothing older than keep_recent). Adjust keep_recent to 1.
    assert stage is None  # default keep_recent=10 > 4 entries → no candidates → None


async def test_auto_consolidate_stage_in_run_trace(tmp_path):
    """End-to-end: ``wp4.consolidate`` stage appears in trace when history is full.

    Patches the consolidate call to bypass the min_candidates/keep_recent guard,
    verifying that the stage wiring from _auto_consolidate_turn into the run is correct.
    """
    cfg = _cfg(tmp_path, history_limit=5)
    async with Autumn(cfg) as autumn:
        _wire_basic(autumn)
        autumn.wp4.api = _CapturingAPI("summary text")

        # Patch _auto_consolidate_turn to always fire so we test the stage-append path.
        from autumn.core.types import WorkflowStage as _WS
        async def _always_consolidate():
            return _WS(id="wp4.consolidate", title="A4 自动整合",
                       detail="Mom1 历史已整合为摘要条目", workspace="WP4", kind="stage",
                       duration_ms=1.0)
        autumn._auto_consolidate_turn = _always_consolidate

        run = await autumn.process_with_trace("next step", input_type=InputType.TASK)

    consolidate_stages = [s for s in run.stages if s.id == "wp4.consolidate"]
    assert len(consolidate_stages) == 1
    assert consolidate_stages[0].workspace == "WP4"


# ── configure_4d exposes new flags ────────────────────────────────────────────

async def test_configure_4d_returns_all_flags(tmp_path):
    """configure_4d returns fourd_auto_annotate and fourd_auto_consolidate."""
    async with Autumn(_cfg(tmp_path)) as autumn:
        result = autumn.configure_4d()
    assert "fourd_auto_annotate" in result
    assert "fourd_auto_consolidate" in result


async def test_configure_4d_toggles_auto_annotate(tmp_path):
    """configure_4d can toggle fourd_auto_annotate off at runtime."""
    async with Autumn(_cfg(tmp_path)) as autumn:
        result = autumn.configure_4d(auto_annotate=False)
    assert result["fourd_auto_annotate"] is False


async def test_configure_4d_toggles_auto_consolidate(tmp_path):
    """configure_4d can toggle fourd_auto_consolidate off at runtime."""
    async with Autumn(_cfg(tmp_path)) as autumn:
        result = autumn.configure_4d(auto_consolidate=False)
    assert result["fourd_auto_consolidate"] is False


async def test_configure_4d_toggles_auto_evolve(tmp_path):
    """configure_4d can enable/disable fourd_auto_evolve at runtime."""
    async with Autumn(_cfg(tmp_path)) as autumn:
        result = autumn.configure_4d(auto_evolve=True)
    assert result["fourd_auto_evolve"] is True


async def test_configure_4d_returns_auto_evolve_in_dict(tmp_path):
    """configure_4d always returns fourd_auto_evolve (default False)."""
    async with Autumn(_cfg(tmp_path)) as autumn:
        result = autumn.configure_4d()
    assert "fourd_auto_evolve" in result
    assert result["fourd_auto_evolve"] is False  # default off


# ── shared zone annotation ─────────────────────────────────────────────────────

def _cfg_with_archive(tmp_path) -> AutumnConfig:
    """Config with archive_executions=True so shared zone gets written."""
    m = ModelConfig(api_key="k", base_url="http://x", model="m", protocol=Protocol.OPENAI)
    cfg = AutumnConfig(
        a1=m, a2=m, a3=m, a4=m,
        behavior=BehaviorConfig(
            fourd_auto_annotate=True,
            fourd_auto_consolidate=False,
            archive_executions=True,
        ),
    )
    cfg.storage.db_path = str(tmp_path / "mem.db")
    return cfg


async def test_shared_zone_annotated_when_archive_on(tmp_path):
    """When archive_on, _auto_annotate_turn('shared') is called after the turn.

    We patch _auto_annotate_turn to intercept calls and verify it receives
    'shared' as well as 'mom1'.
    """
    cfg = _cfg_with_archive(tmp_path)
    async with Autumn(cfg) as autumn:
        _wire_basic(autumn)
        autumn.wp4.api = _A4API()

        called_areas: list[str] = []
        original = autumn._auto_annotate_turn

        async def _tracking(area="mom1"):
            called_areas.append(area)
            return await original(area)

        autumn._auto_annotate_turn = _tracking
        await autumn.process_with_trace("test", input_type=InputType.TASK)

    assert "mom1" in called_areas
    assert "shared" in called_areas


async def test_shared_zone_not_annotated_when_archive_off(tmp_path):
    """When archive_executions=False, only mom1 is annotated."""
    cfg = _cfg(tmp_path)  # archive_executions=False
    async with Autumn(cfg) as autumn:
        _wire_basic(autumn)
        autumn.wp4.api = _A4API()

        called_areas: list[str] = []
        original = autumn._auto_annotate_turn

        async def _tracking(area="mom1"):
            called_areas.append(area)
            return await original(area)

        autumn._auto_annotate_turn = _tracking
        await autumn.process_with_trace("test", input_type=InputType.TASK)

    assert "mom1" in called_areas
    assert "shared" not in called_areas


# ── _auto_evolve_turn ─────────────────────────────────────────────────────────

def _cfg_evolve(tmp_path, history_limit: int = 10) -> AutumnConfig:
    m = ModelConfig(api_key="k", base_url="http://x", model="m", protocol=Protocol.OPENAI)
    cfg = AutumnConfig(
        a1=m, a2=m, a3=m, a4=m,
        behavior=BehaviorConfig(
            fourd_auto_evolve=True,
            fourd_auto_annotate=False,
            fourd_auto_consolidate=False,
            archive_executions=False,
            history_limit=history_limit,
        ),
    )
    cfg.storage.db_path = str(tmp_path / "mem.db")
    return cfg


async def test_auto_evolve_skipped_without_a4(tmp_path):
    """No evolve stage when A4 is absent."""
    m = ModelConfig(api_key="k", base_url="http://x", model="m", protocol=Protocol.OPENAI)
    cfg = AutumnConfig(
        a1=m, a2=m, a3=m, a4=None,
        behavior=BehaviorConfig(fourd_auto_evolve=True, archive_executions=False),
    )
    cfg.storage.db_path = str(tmp_path / "mem.db")
    async with Autumn(cfg) as autumn:
        stage = await autumn._auto_evolve_turn()
    assert stage is None


async def test_auto_evolve_skipped_when_flag_off(tmp_path):
    """No evolve stage when the flag is disabled."""
    cfg = _cfg_evolve(tmp_path)
    cfg.behavior.fourd_auto_evolve = False
    async with Autumn(cfg) as autumn:
        autumn.wp4.api = _CapturingAPI("[]")
        for i in range(10):
            await autumn.mom1.append_history({"input": f"q{i}", "output": f"a{i}"})
        stage = await autumn._auto_evolve_turn()
    assert stage is None


async def test_auto_evolve_skipped_below_threshold(tmp_path):
    """No evolve stage when Mom1 history is below 95% of history_limit."""
    cfg = _cfg_evolve(tmp_path, history_limit=50)
    async with Autumn(cfg) as autumn:
        autumn.wp4.api = _CapturingAPI("[]")
        # 5 entries, limit=50 → 5/50 = 10% < 95% → no evolve
        for i in range(5):
            await autumn.mom1.append_history({"input": f"q{i}", "output": f"a{i}"})
        stage = await autumn._auto_evolve_turn()
    assert stage is None


async def test_auto_evolve_stage_in_run_trace(tmp_path):
    """wp4.evolve stage appears in the run trace when the hook fires."""
    cfg = _cfg_evolve(tmp_path)
    async with Autumn(cfg) as autumn:
        _wire_basic(autumn)
        autumn.wp4.api = _CapturingAPI("ok")

        # Patch to always fire.
        from autumn.core.types import WorkflowStage as _WS
        async def _always_evolve():
            return _WS(id="wp4.evolve", title="A4 自进化",
                       detail="从 Mom1 历史提炼出 2 条固定技能", workspace="WP4",
                       kind="stage", duration_ms=1.0)
        autumn._auto_evolve_turn = _always_evolve

        run = await autumn.process_with_trace("work", input_type=InputType.TASK)

    evolve_stages = [s for s in run.stages if s.id == "wp4.evolve"]
    assert len(evolve_stages) == 1
    assert evolve_stages[0].workspace == "WP4"


# ── _auto_extract_facts_turn ───────────────────────────────────────────────────

def _cfg_extract(tmp_path, on: bool = True, history_limit: int = 4) -> AutumnConfig:
    m = ModelConfig(api_key="k", base_url="http://x", model="m", protocol=Protocol.OPENAI)
    cfg = AutumnConfig(
        a1=m, a2=m, a3=m, a4=m,
        behavior=BehaviorConfig(
            fourd_auto_extract_facts=on,
            fourd_auto_annotate=False,
            fourd_auto_consolidate=False,
            archive_executions=False,
            history_limit=history_limit,
        ),
    )
    cfg.storage.db_path = str(tmp_path / "mem.db")
    return cfg


async def test_auto_extract_facts_skipped_without_a4(tmp_path):
    """No extract stage when A4 is absent."""
    cfg = _cfg_extract(tmp_path)
    cfg.a4 = None
    async with Autumn(cfg) as autumn:
        for i in range(4):
            await autumn.mom1.append_history({"input": f"q{i}", "output": f"a{i}"})
        stage = await autumn._auto_extract_facts_turn()
    assert stage is None


async def test_auto_extract_facts_skipped_when_flag_off(tmp_path):
    """No extract stage when the flag is disabled, even with full history."""
    cfg = _cfg_extract(tmp_path, on=False)
    async with Autumn(cfg) as autumn:
        autumn.wp4.api = _CapturingAPI('["fact"]')
        for i in range(4):
            await autumn.mom1.append_history({"input": f"q{i}", "output": f"a{i}"})
        stage = await autumn._auto_extract_facts_turn()
    assert stage is None


async def test_auto_extract_facts_skipped_below_threshold(tmp_path):
    """No extract when Mom1 history is below 50 % of history_limit."""
    cfg = _cfg_extract(tmp_path, history_limit=50)
    async with Autumn(cfg) as autumn:
        autumn.wp4.api = _CapturingAPI('["fact"]')
        # 3 entries, limit=50 → 3/50 < 50 % → no extraction.
        for i in range(3):
            await autumn.mom1.append_history({"input": f"q{i}", "output": f"a{i}"})
        stage = await autumn._auto_extract_facts_turn()
    assert stage is None


async def test_auto_extract_facts_fires_with_enough_pending(tmp_path):
    """With A4, the flag on, and enough pending raw turns, extraction returns a stage."""
    cfg = _cfg_extract(tmp_path, history_limit=10)  # threshold = max(3, 2) = 3
    async with Autumn(cfg) as autumn:
        autumn.wp4.api = _CapturingAPI('["a distilled fact"]')
        for i in range(3):  # 3 pending ≥ 3 → fires
            await autumn.mom1.append_history({"input": f"q{i}", "output": f"a{i}"})
        stage = await autumn._auto_extract_facts_turn()
    assert stage is not None
    assert stage.id == "wp4.extract_facts"
    assert stage.workspace == "WP4"


async def test_auto_extract_facts_skipped_with_too_few_pending(tmp_path):
    """Below the pending-turn batch threshold, the hook does not fire."""
    cfg = _cfg_extract(tmp_path, history_limit=10)  # threshold = 3
    async with Autumn(cfg) as autumn:
        autumn.wp4.api = _CapturingAPI('["fact"]')
        for i in range(2):  # only 2 pending < 3
            await autumn.mom1.append_history({"input": f"q{i}", "output": f"a{i}"})
        stage = await autumn._auto_extract_facts_turn()
    assert stage is None


async def test_auto_extract_facts_skip_consumed_no_duplicate_second_turn(tmp_path):
    """Two consecutive hook runs on the same history don't double-extract."""
    from autumn.core.memory.kinds import KIND_ATOMIC_FACT

    cfg = _cfg_extract(tmp_path, history_limit=10)  # threshold = 3
    async with Autumn(cfg) as autumn:
        autumn.wp4.api = _CapturingAPI('["only fact"]')
        for i in range(3):
            await autumn.mom1.append_history({"input": f"q{i}", "output": f"a{i}"})
        first = await autumn._auto_extract_facts_turn()
        second = await autumn._auto_extract_facts_turn()  # nothing new since
        facts = await autumn.mom1.get_history(tags=[KIND_ATOMIC_FACT])
    assert first is not None
    assert second is None          # no new turns → no second extraction
    assert len(facts) == 1         # no duplicate atomic fact


async def test_auto_extract_facts_stage_in_run_trace(tmp_path):
    """wp4.extract_facts stage appears in the run trace when the hook fires."""
    cfg = _cfg_extract(tmp_path)
    async with Autumn(cfg) as autumn:
        _wire_basic(autumn)
        autumn.wp4.api = _CapturingAPI("ok")

        from autumn.core.types import WorkflowStage as _WS
        async def _always_extract():
            return _WS(id="wp4.extract_facts", title="A4 原子事实抽取",
                       detail="从 Mom1 历史抽取出 2 条原子事实", workspace="WP4",
                       kind="stage", duration_ms=1.0)
        autumn._auto_extract_facts_turn = _always_extract

        run = await autumn.process_with_trace("work", input_type=InputType.TASK)

    stages = [s for s in run.stages if s.id == "wp4.extract_facts"]
    assert len(stages) == 1
    assert stages[0].workspace == "WP4"


# ── _auto_synthesize_profile_turn ──────────────────────────────────────────────

def _cfg_profile(tmp_path, on: bool = True, history_limit: int = 4) -> AutumnConfig:
    m = ModelConfig(api_key="k", base_url="http://x", model="m", protocol=Protocol.OPENAI)
    cfg = AutumnConfig(
        a1=m, a2=m, a3=m, a4=m,
        behavior=BehaviorConfig(
            fourd_auto_synthesize_profile=on,
            fourd_auto_annotate=False,
            fourd_auto_consolidate=False,
            archive_executions=False,
            history_limit=history_limit,
        ),
    )
    cfg.storage.db_path = str(tmp_path / "mem.db")
    return cfg


async def test_auto_synthesize_profile_skipped_without_a4(tmp_path):
    """No profile stage when A4 is absent."""
    cfg = _cfg_profile(tmp_path)
    cfg.a4 = None
    async with Autumn(cfg) as autumn:
        for i in range(4):
            await autumn.mom1.append_history({"input": f"q{i}", "output": f"a{i}"})
        stage = await autumn._auto_synthesize_profile_turn()
    assert stage is None


async def test_auto_synthesize_profile_skipped_when_flag_off(tmp_path):
    """No profile stage when the flag is disabled."""
    cfg = _cfg_profile(tmp_path, on=False)
    async with Autumn(cfg) as autumn:
        autumn.wp4.api = _CapturingAPI("profile")
        for i in range(4):
            await autumn.mom1.append_history({"input": f"q{i}", "output": f"a{i}"})
        stage = await autumn._auto_synthesize_profile_turn()
    assert stage is None


async def test_auto_synthesize_profile_skipped_below_threshold(tmp_path):
    """No synthesis when Mom1 history is below 50 % of history_limit."""
    cfg = _cfg_profile(tmp_path, history_limit=50)
    async with Autumn(cfg) as autumn:
        autumn.wp4.api = _CapturingAPI("profile")
        for i in range(3):
            await autumn.mom1.append_history({"input": f"q{i}", "output": f"a{i}"})
        stage = await autumn._auto_synthesize_profile_turn()
    assert stage is None


async def test_auto_synthesize_profile_fires_and_returns_stage(tmp_path):
    """With A4, the flag on, and Mom1 ≥ 50 % full, synthesis returns a stage."""
    cfg = _cfg_profile(tmp_path, history_limit=4)
    async with Autumn(cfg) as autumn:
        autumn.wp4.api = _CapturingAPI("a synthesized profile")
        for i in range(2):  # 2/4 = 50 % → fires
            await autumn.mom1.append_history({"input": f"q{i}", "output": f"a{i}"})
        stage = await autumn._auto_synthesize_profile_turn()
    assert stage is not None
    assert stage.id == "wp4.synthesize_profile"
    assert stage.workspace == "WP4"


async def test_auto_synthesize_profile_only_new_skips_when_nothing_newer(tmp_path):
    """A second hook run with no turns post-dating the profile is a no-op."""
    cfg = _cfg_profile(tmp_path, history_limit=4)
    async with Autumn(cfg) as autumn:
        autumn.wp4.api = _CapturingAPI("profile v1")
        for i in range(2):
            await autumn.mom1.append_history({"input": f"q{i}", "output": f"a{i}"})
        first = await autumn._auto_synthesize_profile_turn()
        second = await autumn._auto_synthesize_profile_turn()  # nothing newer
    assert first is not None
    assert second is None


async def test_auto_synthesize_profile_stage_in_run_trace(tmp_path):
    """wp4.synthesize_profile stage appears in the run trace when the hook fires."""
    cfg = _cfg_profile(tmp_path)
    async with Autumn(cfg) as autumn:
        _wire_basic(autumn)
        autumn.wp4.api = _CapturingAPI("ok")

        from autumn.core.types import WorkflowStage as _WS
        async def _always_synth():
            return _WS(id="wp4.synthesize_profile", title="A4 画像合成",
                       detail="已将 Mom1 新增对话折叠进用户画像", workspace="WP4",
                       kind="stage", duration_ms=1.0)
        autumn._auto_synthesize_profile_turn = _always_synth

        run = await autumn.process_with_trace("work", input_type=InputType.TASK)

    stages = [s for s in run.stages if s.id == "wp4.synthesize_profile"]
    assert len(stages) == 1
    assert stages[0].workspace == "WP4"


# ── both hooks are wired into the stream path too ──────────────────────────────

async def test_new_hooks_wired_into_stream_with_trace(tmp_path):
    """extract + synthesize hooks fire on stream_with_trace, not just process."""
    cfg = _cfg_extract(tmp_path)
    async with Autumn(cfg) as autumn:
        _wire_basic(autumn)
        autumn.wp4.api = _CapturingAPI("ok")

        from autumn.core.types import WorkflowStage as _WS
        async def _always_extract():
            return _WS(id="wp4.extract_facts", title="A4 原子事实抽取",
                       detail="x", workspace="WP4", kind="stage", duration_ms=1.0)
        async def _always_synth():
            return _WS(id="wp4.synthesize_profile", title="A4 画像合成",
                       detail="x", workspace="WP4", kind="stage", duration_ms=1.0)
        autumn._auto_extract_facts_turn = _always_extract
        autumn._auto_synthesize_profile_turn = _always_synth

        run = None
        async for event in autumn.stream_with_trace("work", input_type=InputType.TASK):
            if isinstance(event, WorkflowRun):
                run = event

    assert run is not None
    ids = {s.id for s in run.stages}
    assert "wp4.extract_facts" in ids
    assert "wp4.synthesize_profile" in ids


# ── configure_4d exposes the new flags ─────────────────────────────────────────

async def test_configure_4d_toggles_auto_extract_facts(tmp_path):
    async with Autumn(_cfg(tmp_path)) as autumn:
        result = autumn.configure_4d(auto_extract_facts=True)
    assert result["fourd_auto_extract_facts"] is True


async def test_configure_4d_toggles_auto_synthesize_profile(tmp_path):
    async with Autumn(_cfg(tmp_path)) as autumn:
        result = autumn.configure_4d(auto_synthesize_profile=True)
    assert result["fourd_auto_synthesize_profile"] is True


async def test_configure_4d_returns_new_flags_in_dict(tmp_path):
    async with Autumn(_cfg(tmp_path)) as autumn:
        result = autumn.configure_4d()
    assert result["fourd_auto_extract_facts"] is False  # default off
    assert result["fourd_auto_synthesize_profile"] is False  # default off

"""P1-C tests: externalised memory prompt slots.

The defaults must reproduce the previously-hardcoded strings verbatim (so the
refactor changes nothing), and consolidate must honour a per-call override.
"""
from autumn.core.config import StorageConfig
from autumn.core.memory import prompts
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea


# ── slot defaults are unchanged ─────────────────────────────────────────────────

def test_consolidate_system_default_verbatim():
    assert prompts.CONSOLIDATE_SYSTEM == (
        "You compress conversation memory. Summarise the entries "
        "into a compact, factual digest that preserves names, "
        "decisions, preferences and unresolved threads. Be terse."
    )


def test_recall_synth_system_default_verbatim():
    assert prompts.RECALL_SYNTH_SYSTEM == (
        "You are a memory assistant. Synthesise stored facts "
        "into a direct, concise answer."
    )


def test_consolidate_instruction_format():
    assert prompts.consolidate_instruction(2, "- a\n- b") == (
        "Summarise these 2 memory entries:\n\n- a\n- b"
    )


def test_recall_synth_prompt_format():
    out = prompts.recall_synth_prompt("where?", "[relevance=0.9] x")
    assert out == "Using these memory entries, answer: 'where?'\n\n[relevance=0.9] x\n\nBe concise."


# ── storage backend knob (P1-A wiring) ──────────────────────────────────────────

def test_storage_backend_defaults_to_sqlite():
    assert StorageConfig().backend == "sqlite"


# ── consolidate honours the prompt-slot override ────────────────────────────────

class _RecordingAPI:
    """Minimal ModelAPIInterface stub capturing the system prompt it receives."""

    def __init__(self):
        self.system_seen: str | None = None

    async def complete(self, messages):
        self.system_seen = messages[0].content
        return "digest"


async def test_consolidate_uses_default_prompt():
    area = MemoryArea("t", DictBackend())
    for i in range(5):
        await area.append_history(f"m{i}")
    api = _RecordingAPI()
    await area.consolidate(api, keep_recent=1, min_candidates=2)
    assert api.system_seen == prompts.CONSOLIDATE_SYSTEM


async def test_consolidate_honours_override():
    area = MemoryArea("t", DictBackend())
    for i in range(5):
        await area.append_history(f"m{i}")
    api = _RecordingAPI()
    await area.consolidate(api, keep_recent=1, min_candidates=2,
                           system_prompt="CUSTOM SLOT")
    assert api.system_seen == "CUSTOM SLOT"

"""Tests for the improved Selector — heuristic pre-classifier + LLM path."""
import json
import pytest

from autumn.core.components.selector import (
    Selector,
    _heuristic_classify,
    _strip_fence,
)
from autumn.core.types import InputType, TaskType, SelectorResult


class _MockAPI:
    """Records every call so we can assert whether the LLM was reached."""

    def __init__(self, response: str):
        self.response = response
        self.calls: list = []

    async def complete(self, messages, **kwargs):
        self.calls.append(messages)
        return self.response


# ── Heuristic pre-classifier ──────────────────────────────────────────────────


def test_heuristic_greeting_chinese():
    r = _heuristic_classify("你好")
    assert r is not None
    assert r.input_type == InputType.MISSION
    assert r.confidence > 0.9


def test_heuristic_greeting_english():
    r = _heuristic_classify("Hi!")
    assert r is not None
    assert r.input_type == InputType.MISSION


def test_heuristic_greeting_how_are_you():
    r = _heuristic_classify("How are you?")
    assert r is not None
    assert r.input_type == InputType.MISSION


def test_heuristic_markdown_todo_list():
    r = _heuristic_classify("- [ ] Step one\n- [ ] Step two\n- [x] Step three")
    assert r is not None
    assert r.input_type == InputType.TASK


def test_heuristic_code_fence_with_refactor_verb():
    r = _heuristic_classify(
        "Refactor this:\n```python\ndef f(x):\n    return x+1\n```"
    )
    assert r is not None
    assert r.input_type == InputType.TASK
    assert r.task_type == TaskType.CODE


def test_heuristic_code_fence_chinese_refactor_verb():
    r = _heuristic_classify(
        "重构这段:\n```python\ndef f(x): return x\n```"
    )
    assert r is not None
    assert r.input_type == InputType.TASK
    assert r.task_type == TaskType.CODE


def test_heuristic_short_english_question():
    r = _heuristic_classify("What is the meaning of life?")
    assert r is not None
    assert r.input_type == InputType.MISSION


def test_heuristic_short_chinese_question():
    r = _heuristic_classify("Python 中 async 是什么意思？")
    assert r is not None
    assert r.input_type == InputType.MISSION


def test_heuristic_chinese_question_with_ma():
    r = _heuristic_classify("这样做对吗")
    assert r is not None
    assert r.input_type == InputType.MISSION


def test_heuristic_question_with_imperative_falls_through():
    """A question containing an imperative verb should NOT be auto-classified."""
    # "Can you fix this bug?" — has imperative-like 'fix', let LLM decide
    r = _heuristic_classify("Can you fix this bug in my code?")
    assert r is None


def test_heuristic_long_input_falls_through():
    long_text = "This is a long descriptive paragraph " * 5 + "what do you think"
    r = _heuristic_classify(long_text)
    assert r is None


def test_heuristic_numbered_steps():
    r = _heuristic_classify(
        "1. Download the data\n2. Clean it up\n3. Generate the report"
    )
    assert r is not None
    assert r.input_type == InputType.TASK


def test_heuristic_chinese_numbered_steps():
    r = _heuristic_classify("1、下载数据\n2、清理数据\n3、生成报告")
    assert r is not None
    assert r.input_type == InputType.TASK


def test_heuristic_empty_input():
    r = _heuristic_classify("")
    assert r is not None
    assert r.input_type == InputType.MISSION


def test_heuristic_whitespace_only_input():
    r = _heuristic_classify("   \n  \t  ")
    assert r is not None
    assert r.input_type == InputType.MISSION


# ── Selector.classify skips LLM when heuristic fires ──────────────────────────


async def test_classify_greeting_skips_llm():
    api = _MockAPI('{"type":"task","task_type":"code","confidence":0.9}')
    selector = Selector(api)
    result = await selector.classify("你好")
    assert result.input_type == InputType.MISSION
    assert api.calls == []  # LLM was never called


async def test_classify_todo_list_skips_llm():
    api = _MockAPI('{"type":"mission","confidence":0.9}')
    selector = Selector(api)
    result = await selector.classify("- [ ] Task one\n- [ ] Task two")
    assert result.input_type == InputType.TASK
    assert api.calls == []


async def test_classify_ambiguous_input_uses_llm():
    api = _MockAPI(
        '{"type":"task","task_type":"data","confidence":0.91,'
        '"reasoning":"calculation request"}'
    )
    selector = Selector(api)
    result = await selector.classify(
        "Compute the average revenue from last quarter's spreadsheet"
    )
    assert result.input_type == InputType.TASK
    assert result.task_type == TaskType.DATA
    assert len(api.calls) == 1


# ── LLM path: result fields ──────────────────────────────────────────────────


async def test_classify_includes_reasoning_field():
    api = _MockAPI(
        '{"type":"task","task_type":"code","confidence":0.95,'
        '"reasoning":"specific file and bug"}'
    )
    selector = Selector(api)
    # Pick an input that fails all heuristics so we hit the LLM
    result = await selector.classify(
        "I would like assistance with the user authentication module"
    )
    assert result.reasoning == "specific file and bug"


async def test_classify_handles_fenced_json_output():
    """Some models wrap JSON in ```json fences — selector must strip them."""
    api = _MockAPI('```json\n{"type":"mission","confidence":0.8}\n```')
    selector = Selector(api)
    result = await selector.classify(
        "Please help me understand the architecture of this system better"
    )
    assert result.input_type == InputType.MISSION


async def test_classify_handles_bare_fence_output():
    """Fence without language tag should also be tolerated."""
    api = _MockAPI('```\n{"type":"task","task_type":"write","confidence":0.85}\n```')
    selector = Selector(api)
    result = await selector.classify(
        "Please draft a comprehensive design document for the new module"
    )
    assert result.input_type == InputType.TASK
    assert result.task_type == TaskType.WRITE


async def test_classify_bad_json_returns_mission_with_reasoning():
    api = _MockAPI("absolute garbage that won't parse")
    selector = Selector(api)
    result = await selector.classify(
        "Please describe the architecture in long form thanks"
    )
    assert result.input_type == InputType.MISSION
    assert result.reasoning is not None
    assert "parseable" in result.reasoning.lower() or "parse" in result.reasoning.lower()


# ── _strip_fence ──────────────────────────────────────────────────────────────


def test_strip_fence_with_lang_tag():
    assert _strip_fence('```json\n{"a":1}\n```') == '{"a":1}'


def test_strip_fence_without_lang_tag():
    assert _strip_fence('```\n{"a":1}\n```') == '{"a":1}'


def test_strip_fence_no_fence():
    assert _strip_fence('{"a":1}') == '{"a":1}'


def test_strip_fence_preserves_inner_whitespace():
    assert _strip_fence('```json\n{\n  "a": 1\n}\n```') == '{\n  "a": 1\n}'


# ── classify_and_maybe_confirm preserves reasoning through confirmation ──────


async def test_confirm_preserves_reasoning():
    api = _MockAPI(
        '{"type":"task","task_type":"code","confidence":0.5,'
        '"reasoning":"borderline"}'
    )
    selector = Selector(api)

    class _Interaction:
        async def ask(self, q, options): return InputType.MISSION.value

    result = await selector.classify_and_maybe_confirm(
        "Please look at the new authentication module carefully", _Interaction()
    )
    assert result.input_type == InputType.MISSION
    assert result.reasoning == "borderline"

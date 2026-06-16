import json
import re
from collections.abc import Callable

from ..types import InputType, Message, Role, SelectorResult, TaskType

_DEFAULT_SYSTEM = """\
You are the input classifier for the Autumn framework. Decide whether the user's \
input is a TASK or a MISSION. The two routes go to different specialist models, \
so the split is about WHO should handle the work, not just its shape.

- TASK → A2, the heavy-duty code executor. A2 runs a multi-step tool loop \
(reads/writes files, runs code, debugs, tests). Reserve TASK for substantial, \
directly-executable CODE work.
- MISSION → A3, the general executor. A3 handles everything else — questions, \
writing, data analysis, summarisation, docs — and can itself escalate a heavier \
mission into a structured task when execution is actually needed.

# TASK — long-running, heavy code work
Choose TASK only when the input is concrete, code-centric work to execute now:
- Implement / build / add a feature in code.
- Fix / debug a specific bug in source files.
- Refactor / rewrite / optimize existing code.
- Write or run tests; multi-file or multi-step code changes.
The hallmark is "do this coding work", not "talk about it" or "write me prose".

task_type is almost always "code" under this definition. The legacy values \
"search" / "write" / "data" / "general" still exist, but prefer MISSION for \
those — see below.

# MISSION — everything else (general work)
Choose MISSION for ALL non-code-execution work, even when it is structured and \
concrete:
- Questions, explanations, opinions, recommendations, discussion, chit-chat.
- Writing prose: emails, reports, blog posts, documentation, marketing copy, \
fiction.
- Data analysis, calculations, chart prep, summarisation, Q&A over documents.
- Explaining code or producing a short snippet that needs no execution.
- Anything vague, exploratory, or needing interpretation before work can begin.
A3 answers simple missions directly and converts heavier ones into a task.

# Examples (study these — they cover the edge cases)

Input: "Fix the off-by-one bug in user_service.py line 42"
Output: {"type": "task", "task_type": "code", "confidence": 0.97, \
"reasoning": "specific file and bug — code work to execute"}

Input: "帮我修复 user_service.py 第 42 行的越界 bug"
Output: {"type": "task", "task_type": "code", "confidence": 0.97, \
"reasoning": "明确文件位置与 bug 描述，需执行代码修改"}

Input: "Implement a REST endpoint for user login with unit tests"
Output: {"type": "task", "task_type": "code", "confidence": 0.95, \
"reasoning": "multi-step code build with tests"}

Input: "What's the difference between async and threading in Python?"
Output: {"type": "mission", "confidence": 0.94, \
"reasoning": "conceptual question, expects explanation"}

Input: "Python 中 async 和 threading 有什么区别?"
Output: {"type": "mission", "confidence": 0.94, \
"reasoning": "概念问题，期望解释"}

Input: "Refactor this:\\n```python\\ndef f(x): return x+1\\n```"
Output: {"type": "task", "task_type": "code", "confidence": 0.98, \
"reasoning": "explicit code given, refactor verb"}

Input: "Summarise the attached Q3 financial report into 5 bullets"
Output: {"type": "mission", "confidence": 0.9, \
"reasoning": "summarisation — general work, not code execution"}

Input: "把这份 Q3 财报概括成 5 个要点"
Output: {"type": "mission", "confidence": 0.9, \
"reasoning": "摘要属于通用任务，非代码执行"}

Input: "Write a 300-word welcome email for new SaaS customers"
Output: {"type": "mission", "confidence": 0.92, \
"reasoning": "prose writing — handled directly by the general model"}

Input: "写一封 300 字的 SaaS 新用户欢迎邮件"
Output: {"type": "mission", "confidence": 0.92, \
"reasoning": "写作任务，由通用模型直接处理"}

Input: "Compute the YoY growth rate from the attached CSV"
Output: {"type": "mission", "confidence": 0.88, \
"reasoning": "data analysis — general work, may convert if needed"}

Input: "Hi! How are you?"
Output: {"type": "mission", "confidence": 0.99, \
"reasoning": "greeting / small talk"}

Input: "I'm thinking about adding a notification system. What do you think?"
Output: {"type": "mission", "confidence": 0.9, \
"reasoning": "exploratory discussion, no executable request yet"}

Input: "Can you help me?"
Output: {"type": "mission", "confidence": 0.85, \
"reasoning": "vague — no concrete deliverable yet"}

# Output format

Respond with ONLY valid JSON, no markdown fence, no prose. Fields:
- type: "task" or "mission"
- task_type: one of "code", "search", "write", "data", "general" — REQUIRED \
when type == "task" (use "code" unless clearly otherwise), OMIT when \
type == "mission"
- confidence: float 0.0–1.0
- reasoning: ≤ 15 words explaining your choice (used for UI transparency)"""

_CONFIRM_THRESHOLD = 0.75

# ── Heuristic pre-classifier ──────────────────────────────────────────────────

_CODE_FENCE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_TODO_LIST = re.compile(r"^\s*[-*]\s*\[[ xX]\]", re.MULTILINE)
_NUMBERED_STEPS = re.compile(
    r"^\s*\d+[.)、]\s*\S+.*?\n\s*\d+[.)、]\s*\S+",
    re.MULTILINE | re.DOTALL,
)
_QUESTION_PATTERNS = re.compile(
    r"(?:^|\s)(?:what|why|how|when|where|which|who|whose|whom|can|could|would|should|"
    r"is|are|do|does|did|will|may|might)\b.*\?\s*$",
    re.IGNORECASE,
)
_CHINESE_QUESTION = re.compile(r"[吗呢吧么？\?]$")
_GREETING = re.compile(
    r"^\s*(?:hi|hello|hey|你好|您好|嗨|早上好|晚上好|早安|晚安|"
    r"good\s+(?:morning|afternoon|evening|night)|how\s+are\s+you|"
    r"在吗|在不在|有空吗)[\s!.?,，。！？]*$",
    re.IGNORECASE,
)


def _heuristic_classify(user_input: str) -> SelectorResult | None:
    """Cheap rule-based pre-classifier.

    Returns a high-confidence result for inputs that are syntactically
    unambiguous (code fences, todo lists, greetings, simple questions);
    None when the input needs the LLM to decide.

    Heuristics fire BEFORE the LLM to:
    1. cut latency on common patterns,
    2. avoid LLM cost for trivial classifications,
    3. give consistent results for structured input.
    """
    text = user_input.strip()
    if not text:
        return SelectorResult(InputType.MISSION, 1.0, reasoning="empty input")

    # Greeting / small-talk → MISSION
    if _GREETING.match(text):
        return SelectorResult(
            InputType.MISSION, 0.98, reasoning="greeting / small talk",
        )

    # Markdown task list → TASK (with code-fence presence boosting toward CODE)
    if _TODO_LIST.search(text):
        task_type = TaskType.CODE if _CODE_FENCE.search(text) else TaskType.GENERAL
        return SelectorResult(
            InputType.TASK, 0.92, task_type, reasoning="markdown todo list",
        )

    # Fenced code block + imperative verb → TASK/CODE
    if _CODE_FENCE.search(text):
        # CJK has no word boundaries; use a separate pattern for them.
        english_verbs = re.search(
            r"\b(?:fix|refactor|rewrite|debug|optimi[sz]e|review)\b",
            text,
            re.IGNORECASE,
        )
        cjk_verbs = re.search(r"修复|重构|改写|优化|审查|调试", text)
        if english_verbs or cjk_verbs:
            return SelectorResult(
                InputType.TASK, 0.94, TaskType.CODE,
                reasoning="code block + edit verb",
            )

    # Multi-step numbered list → TASK
    if _NUMBERED_STEPS.search(text):
        return SelectorResult(
            InputType.TASK, 0.88, TaskType.GENERAL,
            reasoning="multi-step numbered list",
        )

    # Short pure question with no imperative → MISSION
    is_short = len(text) <= 120
    is_question = (
        bool(_QUESTION_PATTERNS.search(text))
        or bool(_CHINESE_QUESTION.search(text))
        or text.endswith("?")
        or text.endswith("？")
    )
    has_imperative = bool(
        re.search(
            r"\b(?:write|create|build|implement|generate|make|draft|fix|"
            r"refactor|debug|add|remove|update|delete)\b",
            text,
            re.IGNORECASE,
        )
        or re.search(
            r"写|创建|构建|实现|生成|起草|修复|重构|调试|添加|删除|更新",
            text,
        ),
    )
    if is_short and is_question and not has_imperative:
        return SelectorResult(
            InputType.MISSION, 0.88, reasoning="short open question",
        )

    # Otherwise let the LLM decide
    return None


class Selector:
    """WP1-exclusive input classifier.

    Pipeline:
    1. Heuristic pre-classifier handles syntactically obvious inputs (code
       fences, todo lists, greetings, short questions) without an LLM call.
    2. LLM classifier with few-shot examples handles everything else.
    3. ``classify_and_maybe_confirm`` asks the user when confidence is low.
    """

    def __init__(
        self,
        api_interface,
        system_prompt: str | None = None,
        confirm_threshold: float = _CONFIRM_THRESHOLD,
        capability_provider: Callable[[], str] | None = None,
    ):
        self.api = api_interface
        self._system = system_prompt or _DEFAULT_SYSTEM
        self._confirm_threshold = confirm_threshold
        # Optional callable returning a digest of loaded capability domains, injected
        # into the LLM classification prompt so A1 routes with capability awareness.
        self._capability_provider = capability_provider

    def _system_with_capabilities(self) -> str:
        """Append the live capability digest (if any) to the base system prompt."""
        if self._capability_provider is None:
            return self._system
        try:
            digest = self._capability_provider()
        except Exception:
            digest = ""
        if not digest:
            return self._system
        return (
            f"{self._system}\n\n# Available capabilities\n{digest}\n"
            "Consider these when deciding: a request the loaded domains can execute "
            "leans TASK; one that is pure conversation stays MISSION."
        )

    async def classify(self, user_input: str) -> SelectorResult:
        # Fast path: heuristic pre-classifier
        quick = _heuristic_classify(user_input)
        if quick is not None:
            return quick

        # Slow path: LLM classifier with examples
        messages = [
            Message(role=Role.SYSTEM, content=self._system_with_capabilities()),
            Message(role=Role.USER, content=user_input),
        ]
        response = await self.api.complete(messages, max_tokens=128)
        try:
            data = json.loads(_strip_fence(response.strip()))
            input_type = InputType(data["type"])
            task_type: TaskType | None = None
            if input_type == InputType.TASK:
                raw = data.get("task_type", "general")
                try:
                    task_type = TaskType(raw)
                except ValueError:
                    task_type = TaskType.GENERAL
            return SelectorResult(
                input_type=input_type,
                confidence=float(data.get("confidence", 0.5)),
                task_type=task_type,
                reasoning=data.get("reasoning"),
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            return SelectorResult(
                InputType.MISSION, 0.5,
                reasoning="classifier output was not parseable JSON",
            )

    async def classify_and_maybe_confirm(self, user_input: str, interaction) -> SelectorResult:
        """Classify; ask user to confirm only if confidence < threshold."""
        result = await self.classify(user_input)
        if interaction and result.confidence < self._confirm_threshold:
            confirmed = await interaction.ask(
                f"Input classified as [{result.input_type.value.upper()}] "
                f"(confidence {result.confidence:.0%}). Confirm or correct?",
                [t.value for t in InputType],
            )
            confirmed_type = InputType(confirmed)
            task_type = result.task_type if confirmed_type == InputType.TASK else None
            return SelectorResult(
                confirmed_type, result.confidence, task_type,
                reasoning=result.reasoning,
            )
        return result


def _strip_fence(text: str) -> str:
    """Tolerate models that wrap JSON in a ```json fenced block."""
    text = text.strip()
    if text.startswith("```"):
        # Drop opening fence (with or without language tag) and closing fence.
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()

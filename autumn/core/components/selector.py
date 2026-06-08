import json
import re
from ..types import InputType, TaskType, Message, Role, SelectorResult

_DEFAULT_SYSTEM = """\
You are the input classifier for the Autumn framework. Your job: decide whether \
the user's input is a TASK (structured, directly executable work) or a MISSION \
(general conversation, exploration, or interpretation needed).

# Classification rules

## TASK
A directly-executable unit of work with a clear deliverable. Choose TASK when:
- The input lists concrete steps, todo items, or acceptance criteria.
- It asks you to write/edit/refactor specific code, files, or documents.
- It defines exact data, calculations, or transformations to perform.
- The intent is "do X" rather than "let's talk about X".

Then choose a task_type:
- "code": writing, debugging, reviewing, refactoring, or testing source code.
- "search": fact lookup, retrieval, summarisation over documents, Q&A grounded \
in stored data.
- "write": drafting prose — emails, reports, blogs, fiction, marketing copy.
- "data": numeric analysis, calculations, chart prep, SQL, spreadsheets, ETL.
- "general": structured task that does not clearly fit the above.

## MISSION
Open-ended conversation, exploration, or anything that needs interpretation.
Choose MISSION when:
- The input is a question seeking an explanation, opinion, or recommendation.
- It's casual conversation, greetings, or chit-chat.
- The request is vague and needs follow-up before any work can begin.
- It mixes discussion and action without clear executable scope.

# Examples (study these — they cover the edge cases)

Input: "Fix the off-by-one bug in user_service.py line 42"
Output: {"type": "task", "task_type": "code", "confidence": 0.97, \
"reasoning": "specific file and bug pointed out — directly executable"}

Input: "帮我修复 user_service.py 第 42 行的越界 bug"
Output: {"type": "task", "task_type": "code", "confidence": 0.97, \
"reasoning": "明确文件位置与 bug 描述，可直接执行"}

Input: "What's the difference between async and threading in Python?"
Output: {"type": "mission", "confidence": 0.94, \
"reasoning": "conceptual question, expects explanation"}

Input: "Python 中 async 和 threading 有什么区别?"
Output: {"type": "mission", "confidence": 0.94, \
"reasoning": "概念问题，期望解释"}

Input: "- [ ] Read login.py\\n- [ ] Add CSRF check\\n- [ ] Add unit test"
Output: {"type": "task", "task_type": "code", "confidence": 0.96, \
"reasoning": "explicit todo list of code changes"}

Input: "Summarise the attached Q3 financial report into 5 bullets"
Output: {"type": "task", "task_type": "search", "confidence": 0.93, \
"reasoning": "summarisation over a specific document"}

Input: "把这份 Q3 财报概括成 5 个要点"
Output: {"type": "task", "task_type": "search", "confidence": 0.93, \
"reasoning": "针对特定文档的摘要任务"}

Input: "Write a 300-word welcome email for new SaaS customers"
Output: {"type": "task", "task_type": "write", "confidence": 0.95, \
"reasoning": "specific deliverable with audience and length"}

Input: "写一封 300 字的 SaaS 新用户欢迎邮件"
Output: {"type": "task", "task_type": "write", "confidence": 0.95, \
"reasoning": "明确受众与字数的写作任务"}

Input: "Compute the YoY growth rate from the attached CSV"
Output: {"type": "task", "task_type": "data", "confidence": 0.96, \
"reasoning": "concrete numeric calculation"}

Input: "Hi! How are you?"
Output: {"type": "mission", "confidence": 0.99, \
"reasoning": "greeting / small talk"}

Input: "I'm thinking about adding a notification system. What do you think?"
Output: {"type": "mission", "confidence": 0.90, \
"reasoning": "exploratory discussion, no executable request yet"}

Input: "Refactor this:\\n```python\\ndef f(x): return x+1\\n```"
Output: {"type": "task", "task_type": "code", "confidence": 0.98, \
"reasoning": "explicit code given, refactor verb"}

Input: "Can you help me?"
Output: {"type": "mission", "confidence": 0.85, \
"reasoning": "vague — no concrete deliverable yet"}

# Output format

Respond with ONLY valid JSON, no markdown fence, no prose. Fields:
- type: "task" or "mission"
- task_type: one of "code", "search", "write", "data", "general" — REQUIRED \
when type == "task", OMIT when type == "mission"
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
            InputType.MISSION, 0.98, reasoning="greeting / small talk"
        )

    # Markdown task list → TASK (with code-fence presence boosting toward CODE)
    if _TODO_LIST.search(text):
        task_type = TaskType.CODE if _CODE_FENCE.search(text) else TaskType.GENERAL
        return SelectorResult(
            InputType.TASK, 0.92, task_type, reasoning="markdown todo list"
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
        or _CHINESE_QUESTION.search(text) is not None
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
        )
    )
    if is_short and is_question and not has_imperative:
        return SelectorResult(
            InputType.MISSION, 0.88, reasoning="short open question"
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
    ):
        self.api = api_interface
        self._system = system_prompt or _DEFAULT_SYSTEM
        self._confirm_threshold = confirm_threshold

    async def classify(self, user_input: str) -> SelectorResult:
        # Fast path: heuristic pre-classifier
        quick = _heuristic_classify(user_input)
        if quick is not None:
            return quick

        # Slow path: LLM classifier with examples
        messages = [
            Message(role=Role.SYSTEM, content=self._system),
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
                confidence=float(data.get("confidence", 1.0)),
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

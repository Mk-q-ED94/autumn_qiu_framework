import json

from ..memory.base import MemoryArea
from ..types import Message, Role

_MAX_RETRIES = 3

_DEFAULT_EVAL_SYSTEM = """\
You are a quality checker in the Autumn framework.
Given an output and optional context from memory, decide if the output is acceptable.
Respond with ONLY valid JSON: {"ok": true} or {"ok": false, "issues": "brief description"}"""

_CORRECT_SYSTEM = """\
You are a quality improver in the Autumn framework.
Rewrite the output to fix the reported issues. Return ONLY the improved output, no explanation."""


class Checker:
    """Output validator per workspace.

    Validation pipeline (per attempt, up to _MAX_RETRIES):
      1. Rule check: non-empty, minimum length.
      2. Model check: call the workspace's API with memory context.
    On all retries exhausted: return output annotated with [CHECK_FAILED: reason].
    """

    def __init__(
        self,
        workspace_id: str,
        api_interface,
        eval_prompt: str | None = None,
        retries: int = _MAX_RETRIES,
    ):
        self.workspace_id = workspace_id
        self.api = api_interface
        self._eval_system = eval_prompt or _DEFAULT_EVAL_SYSTEM
        # At least one attempt; higher values add validate→correct rounds.
        self._retries = max(1, retries)

    async def validate(self, output: str, memory: MemoryArea) -> tuple[bool, str]:
        last_issues = ""
        for attempt in range(self._retries):
            # Rule check (fast, free)
            rule_issues = _rule_check(output)
            if rule_issues:
                if attempt < self._retries - 1:
                    output = await self._correct(output, rule_issues)
                    continue
                last_issues = rule_issues
                break

            # Model check (uses memory context)
            ok, model_issues = await self._model_check(output, memory)
            if ok:
                return True, output
            last_issues = model_issues
            if attempt < self._retries - 1:
                output = await self._correct(output, model_issues)

        return False, f"[CHECK_FAILED({self.workspace_id}): {last_issues}]\n\n{output}"

    async def inspect(self, output: str, memory: MemoryArea) -> tuple[bool, str]:
        """Observation-only check: returns (ok, issues) without auto-correction.

        Used by the streaming path, which has already emitted tokens to the user
        — we can no longer rewrite the output, only surface issues as an advisory.
        """
        rule_issues = _rule_check(output)
        if rule_issues:
            return False, rule_issues
        return await self._model_check(output, memory)

    async def _model_check(self, output: str, memory: MemoryArea) -> tuple[bool, str]:
        context = await _load_context(memory, output)
        user_content = f"Output to evaluate:\n{output}"
        if context:
            user_content = f"Memory context:\n{context}\n\n{user_content}"
        messages = [
            Message(role=Role.SYSTEM, content=self._eval_system),
            Message(role=Role.USER, content=user_content),
        ]
        resp = await self.api.complete(messages, max_tokens=128)
        # A non-string / empty response means we can't judge — pass through rather
        # than loop forever. (We handle this explicitly instead of catching
        # AttributeError, so a genuinely broken API object still surfaces.)
        text = resp.strip() if isinstance(resp, str) else ""
        if not text:
            return True, ""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return True, ""  # unparseable response → pass through
        if not isinstance(data, dict):
            return True, ""
        if data.get("ok"):
            return True, ""
        return False, data.get("issues", "quality check failed")

    async def _correct(self, output: str, issues: str) -> str:
        messages = [
            Message(role=Role.SYSTEM, content=_CORRECT_SYSTEM),
            Message(role=Role.USER, content=f"Issues: {issues}\n\nOutput to fix:\n{output}"),
        ]
        return await self.api.complete(messages)


# ── helpers ───────────────────────────────────────────────────────────────────

def _rule_check(output: str) -> str:
    output = output.strip()
    if not output:
        return "output is empty"
    if len(output) < 10:
        return "output is too short"
    return ""


async def _load_context(memory: MemoryArea, query: str = "") -> str:
    """Pull requirements and history from memory. Uses semantic search when vector is enabled."""
    parts = []
    for key in ["requirements", "history", "context"]:
        value = await memory.get(key)
        if value:
            parts.append(f"{key}: {value}")

    if query and memory.has_vector:
        try:
            results = await memory.search(query, k=3)
            if results:
                snippets = "\n".join(
                    f"- [{r.score:.2f}] {r.text[:300]}" for r in results
                )
                parts.append(f"semantic_context:\n{snippets}")
        except Exception:
            pass  # vector search is supplementary; never block validation

    return "\n".join(parts)

"""
HermesAPIInterface — adapter for Nous-Hermes-style models.

Hermes models (Hermes 2 / 3, llama-3-based variants, etc.) use a ChatML
prompting style and encode tool use as XML tags in message content rather
than OpenAI's native ``tools`` parameter.

Wire format for tool calls
--------------------------
Model output (assistant turn):
    <tool_call>
    {"name": "my_tool", "arguments": {"key": "value"}}
    </tool_call>

Tool result (next user turn):
    <tool_response>
    {"name": "my_tool", "content": "result text"}
    </tool_response>

Hermes 3 also emits optional ``<thinking>…</thinking>`` reasoning blocks;
these are stripped from the text returned to callers so they always see
clean final answers. The raw reasoning is accessible via ``last_thinking``
on the interface instance after each call.

Compatibility
-------------
Works with any OpenAI-compatible server that hosts a Hermes model:
  - Ollama  (http://localhost:11434)
  - vLLM    (http://localhost:8000)
  - llama.cpp server

Configuration example (`.env`):
    A2_API_KEY=ollama
    A2_BASE_URL=http://localhost:11434
    A2_MODEL=hermes3:8b
    A2_PROTOCOL=hermes
"""

import json
import re
import uuid

from ..types import Protocol, ToolCall
from .base import ModelAPIInterface

# ── regex patterns ─────────────────────────────────────────────────────────────

_TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_THINKING_RE = re.compile(r"<thinking>\s*.*?\s*</thinking>", re.DOTALL)

# ── system prompt injected when tools are available ────────────────────────────

_TOOL_SYSTEM = """\
You are a function-calling assistant. Available tools:

<tools>
{tools_json}
</tools>

When you need a tool, output EXACTLY (nothing else on the same line):
<tool_call>
{{"name": "<tool-name>", "arguments": {{...}}}}
</tool_call>

After the tool result arrives in a <tool_response> block, continue reasoning
or give a final plain-text answer. Call one tool at a time. Never fabricate
tool results."""


class HermesAPIInterface(ModelAPIInterface):
    """Adapter for Nous-Hermes-style models via any OpenAI-compatible endpoint.

    Overrides the four tool-use methods of :class:`ModelAPIInterface` to speak
    Hermes XML instead of OpenAI's JSON ``tool_calls`` wire format. Plain
    completions, streaming, and retry logic are inherited unchanged.

    Attributes
    ----------
    last_thinking : str
        The raw content of the most recent ``<thinking>`` block emitted by the
        model (empty string when none). Useful for debugging/logging.

    """

    def __init__(self, api_key: str, base_url: str, model: str):
        # Hermes servers expose an OpenAI-compatible /v1/chat/completions endpoint;
        # we reuse all HTTP machinery from the base class.
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            protocol=Protocol.OPENAI,
        )
        self.last_thinking: str = ""

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _schemas_to_hermes_json(tools: list[dict]) -> str:
        """Normalise OpenAI or Anthropic schema dicts → compact Hermes JSON."""
        simplified: list[dict] = []
        for t in tools:
            fn = t.get("function", t)          # unwrap OpenAI {"type":"function","function":{}}
            simplified.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters") or fn.get("input_schema") or {},
            })
        return json.dumps(simplified, ensure_ascii=False, indent=2)

    def _extract_thinking(self, text: str) -> tuple[str, str]:
        """Return (clean_text, thinking_text). Strips all <thinking> blocks."""
        thinking_parts: list[str] = [m.group(0) for m in _THINKING_RE.finditer(text)]
        thinking = "\n".join(thinking_parts)
        clean = _THINKING_RE.sub("", text).strip()
        return clean, thinking

    def _extract_tool_calls(self, text: str) -> tuple[str, list[ToolCall]]:
        """Parse <tool_call> blocks and return (remaining_text, calls)."""
        calls: list[ToolCall] = []
        for match in _TOOL_CALL_RE.finditer(text):
            try:
                data = json.loads(match.group(1))
                calls.append(ToolCall(
                    id=f"call_{uuid.uuid4().hex[:8]}",
                    name=data["name"],
                    arguments=data.get("arguments", {}),
                ))
            except (json.JSONDecodeError, KeyError):
                pass
        clean = _TOOL_CALL_RE.sub("", text).strip()
        return clean, calls

    def _inject_tools(self, messages: list[dict], tools: list[dict]) -> list[dict]:
        """Prepend tool definitions into the system message (create one if absent)."""
        preamble = _TOOL_SYSTEM.format(tools_json=self._schemas_to_hermes_json(tools))
        patched: list[dict] = []
        inserted = False
        for msg in messages:
            if msg.get("role") == "system" and not inserted:
                patched.append({**msg, "content": preamble + "\n\n" + msg["content"]})
                inserted = True
            else:
                patched.append(msg)
        if not inserted:
            patched = [{"role": "system", "content": preamble}, *patched]
        return patched

    # ── ModelAPIInterface overrides ────────────────────────────────────────────

    async def complete(self, messages, **kwargs) -> str:
        """Strip <thinking> blocks so memory ops and plain calls get clean output."""
        text = await super().complete(messages, **kwargs)
        clean, thinking = self._extract_thinking(text)
        self.last_thinking = thinking
        return clean

    async def complete_with_tools_raw(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str | None = None,
        **kwargs,
    ) -> tuple[str, list[ToolCall]]:
        self.last_usage = None
        full: list[dict] = []
        if system:
            full.append({"role": "system", "content": system})
        full.extend(messages)
        full = self._inject_tools(full, tools)

        payload = {"model": self.model, "messages": full, **kwargs}
        data = await self._post_with_retry(self._completion_endpoint, payload)
        self._record_usage(data)
        # Degrade gracefully on an empty/malformed body (some OpenAI-compatible
        # servers return {} or {"choices": []} under load) — mirror the base
        # class guard rather than letting choices[0] raise into the ReAct loop.
        choices = data.get("choices") or []
        raw = ((choices[0].get("message") or {}).get("content") if choices else "") or ""

        # Strip <thinking> first, then look for tool calls in the remainder.
        after_think, thinking = self._extract_thinking(raw)
        self.last_thinking = thinking
        text, calls = self._extract_tool_calls(after_think)
        return text, calls

    def build_assistant_tool_message(self, text: str, tool_calls: list[ToolCall]) -> dict:
        parts: list[str] = []
        if text:
            parts.append(text)
        for tc in tool_calls:
            blob = json.dumps(
                {"name": tc.name, "arguments": tc.arguments},
                ensure_ascii=False,
            )
            parts.append(f"<tool_call>\n{blob}\n</tool_call>")
        return {"role": "assistant", "content": "\n".join(parts)}

    def build_tool_result_messages(
        self,
        tool_calls: list[ToolCall],
        results: list[str],
    ) -> list[dict]:
        parts: list[str] = []
        for tc, result in zip(tool_calls, results, strict=True):
            blob = json.dumps({"name": tc.name, "content": result}, ensure_ascii=False)
            parts.append(f"<tool_response>\n{blob}\n</tool_response>")
        return [{"role": "user", "content": "\n".join(parts)}]

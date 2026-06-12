import asyncio
import time
import warnings

from ..api.base import ModelAPIInterface
from ..types import AgentStep, Protocol
from .skill import Skill
from .terr import Terr
from .tool import Tool

_DEFAULT_MAX_STEPS = 10
_MAX_HISTORY_CONTEXT = 5

_REACT_SYSTEM = """\
You are {name}, an autonomous agent in the Autumn framework.
You have access to callable functions — some are atomic tools (single primitive \
operations like reading a file or calling an API), others are higher-level \
skills (workflows that may chain several steps internally). Prefer a skill \
when one matches the user's request directly; reach for tools when you need \
precise control.
Reason step by step. When you have the final answer, respond in plain text \
without calling any function."""


def _format_memory_context(history: list) -> str:
    """Render recent memory history into a compact context block for the system prompt.

    Accepts both MemoryEntry objects (new) and raw dicts (legacy).
    Pulls the task/input and output of the most recent turns so the agent can
    reason with continuity. Best-effort: unknown entry shapes are skipped.
    """
    from ..memory.base import MemoryEntry
    lines: list[str] = []
    for entry in history[-_MAX_HISTORY_CONTEXT:]:
        raw: dict | None = None
        if isinstance(entry, MemoryEntry):
            raw = entry.content if isinstance(entry.content, dict) else None
        elif isinstance(entry, dict):
            raw = entry
        if not raw:
            continue
        task = raw.get("task") or raw.get("input") or ""
        output = raw.get("output") or ""
        if not (task or output):
            continue
        snippet = output if len(output) <= 200 else output[:200] + "…"
        lines.append(f"- {task}\n  → {snippet}")
    if not lines:
        return ""
    return "Recent context from your memory (oldest first):\n" + "\n".join(lines)


class Agent:
    """Autonomous agent with a ReAct (Reason + Act) loop.

    Maintains conversation state in the model's native provider format so that
    each round correctly carries the assistant's tool_calls and the tool results
    back to the model.

    Parameters
    ----------
    name : str
        Agent identity, woven into the ReAct system prompt.
    api : ModelAPIInterface
        Backing model. Any protocol works — OpenAI, Anthropic, or Hermes — since
        tool wire-format details are encapsulated by the interface.
    tools, skills : list
        Callable capabilities. Both are advertised to the model as function
        schemas; ``tools`` are atomic operations, ``skills`` are higher-level
        workflows. A name collision between a tool and a skill is an error —
        the function-calling API would expose two schemas with the same name —
        so ``__init__`` raises ``ValueError`` instead of letting one silently
        shadow the other.
    instructions : str | None
        Extra system guidance appended after the ReAct base prompt. WP2 uses this
        to keep its task-executor persona while gaining tool access.
    max_steps : int
        Maximum ReAct iterations before giving up. Long agentic tasks (search
        + synthesize, multi-file refactor) may need a higher ceiling.

    """

    def __init__(
        self,
        name: str,
        api: ModelAPIInterface,
        tools: list[Tool] | None = None,
        skills: list[Skill] | None = None,
        terrs: "list[Terr] | None" = None,
        instructions: str | None = None,
        max_steps: int = _DEFAULT_MAX_STEPS,
    ):
        self.name = name
        self.api = api

        # Expand terrs into flat lists; explicit tools/skills take precedence
        # (they're registered last, so the dict overwrites any same-name terr entry).
        # Warn when the same name appears in two different terrs under the same type —
        # that is usually an accidental naming conflict across domains.
        all_tools: list[Tool] = []
        all_skills: list[Skill] = []
        _seen_tool_src: dict[str, str] = {}   # name → terr name that introduced it
        _seen_skill_src: dict[str, str] = {}

        for terr in (terrs or []):
            for tool in terr.tools:
                if tool.name in _seen_tool_src:
                    warnings.warn(
                        f"Agent {name!r}: tool {tool.name!r} defined in both "
                        f"terr {_seen_tool_src[tool.name]!r} and terr {terr.name!r}; "
                        "the later definition wins.",
                        UserWarning,
                        stacklevel=2,
                    )
                _seen_tool_src[tool.name] = terr.name
                all_tools.append(tool)

            for skill in terr.skills:
                if skill.name in _seen_skill_src:
                    warnings.warn(
                        f"Agent {name!r}: skill {skill.name!r} defined in both "
                        f"terr {_seen_skill_src[skill.name]!r} and terr {terr.name!r}; "
                        "the later definition wins.",
                        UserWarning,
                        stacklevel=2,
                    )
                _seen_skill_src[skill.name] = terr.name
                all_skills.append(skill)

        all_tools.extend(tools or [])
        all_skills.extend(skills or [])

        self.tools: dict[str, Tool] = {t.name: t for t in all_tools}
        self.skills: dict[str, Skill] = {s.name: s for s in all_skills}

        clash = set(self.tools) & set(self.skills)
        if clash:
            raise ValueError(
                f"Agent {name!r}: tool/skill name collision {sorted(clash)!r}. "
                "Function-calling exposes both as schemas under the same name, "
                "which would silently shadow one. Rename one before constructing.",
            )

        # Domain descriptions are surfaced in the system prompt so the model
        # can reason about which area of expertise to call on.
        self._terr_descriptions: dict[str, str] = {
            t.name: t.description for t in (terrs or []) if t.description
        }
        for callable_obj in [*self.tools.values(), *self.skills.values()]:
            source = getattr(callable_obj, "source_terr", None)
            description = getattr(callable_obj, "source_terr_description", None)
            if source and description:
                self._terr_descriptions.setdefault(source, description)

        self.instructions = instructions
        self.max_steps = max_steps

    async def _build_system(self, memory) -> str:
        system = _REACT_SYSTEM.format(name=self.name)
        if self._terr_descriptions:
            lines = "\n".join(f"- {n}: {d}" for n, d in self._terr_descriptions.items())
            system = f"{system}\n\nLoaded capability domains:\n{lines}"
        if self.instructions:
            system = f"{system}\n\n{self.instructions}"
        if memory is not None and hasattr(memory, "get_history"):
            try:
                history = await memory.get_history()
            except Exception:  # noqa: BLE001 — memory context is best-effort
                history = []
            ctx = _format_memory_context(history)
            if ctx:
                system = f"{system}\n\n{ctx}"
        return system

    async def _invoke_call(self, tc) -> tuple[str, float, "Tool | Skill | None"]:
        """Dispatch one tool/skill call, returning (result, duration_ms, callable).

        Never raises: tool exceptions and unknown names are turned into a string
        result that gets fed back to the model for ReAct recovery. Each call
        times itself, so concurrent dispatch still records accurate per-step
        durations.
        """
        started = time.perf_counter()
        callable_obj: Tool | Skill | None = None
        try:
            if tc.name in self.tools:
                callable_obj = self.tools[tc.name]
                result = await callable_obj.call(**tc.arguments)
            elif tc.name in self.skills:
                callable_obj = self.skills[tc.name]
                result = await callable_obj.execute(**tc.arguments)
            else:
                result = f"[error: unknown tool '{tc.name}']"
        except Exception as e:  # noqa: BLE001 — feed error back to model for ReAct recovery
            result = f"[tool error: {e}]"
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        return str(result), duration_ms, callable_obj

    async def run(self, task: str, memory=None, steps: list[AgentStep] | None = None) -> str:
        """Run the ReAct loop and return the final answer.

        If ``steps`` is provided, each tool/skill invocation is appended to it
        as an :class:`AgentStep` — letting callers surface the agent's actions
        in a workflow trace without changing the string return value.

        After ``run`` returns, ``self.total_prompt_tokens`` and
        ``self.total_completion_tokens`` hold the summed token usage across all
        LLM calls in the loop, so workspaces can surface aggregate cost without
        a second pass.
        """
        system = await self._build_system(memory)
        is_openai = self.api.protocol == Protocol.OPENAI

        # Provider-native message accumulator
        if is_openai:
            msgs: list[dict] = [
                {"role": "system", "content": system},
                {"role": "user", "content": task},
            ]
            api_system = None
        else:
            msgs = [{"role": "user", "content": task}]
            api_system = system

        # Both tools and skills are exposed to the model as callable functions.
        # On a name clash, the tool wins at execution time (checked first below).
        callables = [*self.tools.values(), *self.skills.values()]
        tool_schemas = [
            c.to_openai_schema() if is_openai else c.to_anthropic_schema()
            for c in callables
        ]

        # Token accumulators are reset on every run() so back-to-back invocations
        # of the same Agent don't keep growing.
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0

        for _ in range(self.max_steps):
            text, tool_calls = await self.api.complete_with_tools_raw(
                msgs, tool_schemas, system=api_system,
            )

            # Capture LLM usage from this turn; attribute it to any tool-call steps
            # produced by it so the trace can show per-tool token cost.
            # Tolerates mock APIs that don't expose ``last_usage``.
            turn_usage = getattr(self.api, "last_usage", None) or {}
            turn_prompt = turn_usage.get("prompt_tokens")
            turn_completion = turn_usage.get("completion_tokens")
            if turn_prompt is not None:
                self.total_prompt_tokens += turn_prompt
            if turn_completion is not None:
                self.total_completion_tokens += turn_completion

            if not tool_calls:
                return text

            # Execute every requested tool. A single LLM turn that emits several
            # tool calls has no data dependency between them — the model already
            # committed to all of them before seeing any result — so they run
            # concurrently and the turn waits only on the slowest, not the sum.
            # Order is preserved for the result messages (the provider zips them
            # back to tool_call ids), and the (single) token cost is attributed
            # to the first step only so the workflow total doesn't multiply.
            invoked = await asyncio.gather(*(self._invoke_call(tc) for tc in tool_calls))
            results = [result for result, _, _ in invoked]

            if steps is not None:
                for i, (tc, (result, duration_ms, callable_obj)) in enumerate(
                    zip(tool_calls, invoked, strict=True),
                ):
                    source_terr = (
                        getattr(callable_obj, "source_terr", None)
                        if callable_obj is not None else None
                    )
                    steps.append(AgentStep(
                        name=tc.name,
                        arguments=dict(tc.arguments),
                        result=result,
                        duration_ms=duration_ms,
                        prompt_tokens=turn_prompt if i == 0 else None,
                        completion_tokens=turn_completion if i == 0 else None,
                        source_terr=source_terr,
                    ))

            msgs.append(self.api.build_assistant_tool_message(text, tool_calls))
            msgs.extend(self.api.build_tool_result_messages(tool_calls, results))

        return "[agent: max steps reached without a final answer]"

from .tool import Tool
from .skill import Skill
from .terr import Terr
from ..api.base import ModelAPIInterface
from ..types import Protocol, AgentStep

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


def _format_memory_context(history: list[dict]) -> str:
    """Render recent memory history into a compact context block for the system prompt.

    Pulls the task/input and output of the most recent turns so the agent can
    reason with continuity. Best-effort: unknown entry shapes are skipped.
    """
    lines: list[str] = []
    for entry in history[-_MAX_HISTORY_CONTEXT:]:
        if not isinstance(entry, dict):
            continue
        task = entry.get("task") or entry.get("input") or ""
        output = entry.get("output") or ""
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
        all_tools: list[Tool] = []
        all_skills: list[Skill] = []
        for terr in (terrs or []):
            all_tools.extend(terr.tools)
            all_skills.extend(terr.skills)
        all_tools.extend(tools or [])
        all_skills.extend(skills or [])

        self.tools: dict[str, Tool] = {t.name: t for t in all_tools}
        self.skills: dict[str, Skill] = {s.name: s for s in all_skills}

        clash = set(self.tools) & set(self.skills)
        if clash:
            raise ValueError(
                f"Agent {name!r}: tool/skill name collision {sorted(clash)!r}. "
                "Function-calling exposes both as schemas under the same name, "
                "which would silently shadow one. Rename one before constructing."
            )

        # Domain descriptions are surfaced in the system prompt so the model
        # can reason about which area of expertise to call on.
        self._terr_descriptions: dict[str, str] = {
            t.name: t.description for t in (terrs or []) if t.description
        }

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

    async def run(self, task: str, memory=None, steps: list[AgentStep] | None = None) -> str:
        """Run the ReAct loop and return the final answer.

        If ``steps`` is provided, each tool/skill invocation is appended to it
        as an :class:`AgentStep` — letting callers surface the agent's actions
        in a workflow trace without changing the string return value.
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

        for _ in range(self.max_steps):
            text, tool_calls = await self.api.complete_with_tools_raw(
                msgs, tool_schemas, system=api_system
            )

            if not tool_calls:
                return text

            # Execute every requested tool
            results: list[str] = []
            for tc in tool_calls:
                try:
                    if tc.name in self.tools:
                        result = await self.tools[tc.name].call(**tc.arguments)
                    elif tc.name in self.skills:
                        result = await self.skills[tc.name].execute(**tc.arguments)
                    else:
                        result = f"[error: unknown tool '{tc.name}']"
                except Exception as e:  # noqa: BLE001 — feed error back to model for ReAct recovery
                    result = f"[tool error: {e}]"
                results.append(str(result))
                if steps is not None:
                    steps.append(AgentStep(
                        name=tc.name,
                        arguments=dict(tc.arguments),
                        result=str(result),
                    ))

            msgs.append(self.api.build_assistant_tool_message(text, tool_calls))
            msgs.extend(self.api.build_tool_result_messages(tool_calls, results))

        return "[agent: max steps reached without a final answer]"

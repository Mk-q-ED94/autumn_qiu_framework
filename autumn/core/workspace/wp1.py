import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Literal

from ..components.selector import Selector
from ..interaction import UserInteraction
from ..types import (
    InputType,
    Message,
    MissionRoute,
    Role,
    SelectorResult,
    TaskType,
    WorkflowRun,
    WorkflowStage,
)
from .base import WorkspaceBase
from .wp2 import WP2Tas
from .wp3 import WP3Mis

if TYPE_CHECKING:
    from ..memory.access import Mom1AccessBroker
    from ..memory.project import ProjectMemory
    from .wp4 import WP4Mem

_ADVISORY_PREFIX = "\n\n---\n[质量提示] "


def _strip_check_marker(checked: str) -> str:
    """Extract the clean output from a [CHECK_FAILED(...): ...]\n\n<output> string."""
    idx = checked.find("]\n\n")
    return checked[idx + 3:] if idx != -1 else checked


def _check_detail(ok: bool, checked: str, passed_label: str, failed_label: str) -> tuple[str, str]:
    """Return (clean_output, stage_detail) from a checker.validate result."""
    if ok:
        return checked, passed_label
    clean = _strip_check_marker(checked)
    # Extract the issues text from between ": " and "]"
    start = checked.find(": ")
    end = checked.find("]")
    issues = checked[start + 2:end] if start != -1 and end != -1 and end > start else "未通过"
    return clean, f"{failed_label}: {issues}"

_PLAN_TASK_SYSTEM = """\
You are A1, the orchestrating coordinator in the Autumn framework.
A2 (the code executor) is about to work on the task below. Before it starts,
briefly outline the approach — 3 to 6 numbered steps — so A2 has a clear direction.

Write only the numbered steps. One step per line. Each step: one short action sentence.
No introduction, no markdown headers, no commentary after the steps."""

_SUPERVISE_SYSTEM = """\
You are A1, supervising A2 (the executor) as it works through a task step by step.
You are shown the original task and A2's latest action plus its result.

If A2 is on track, reply with exactly: CONTINUE
If A2 is off course, drifting, repeating itself, or mishandling an error, reply
with ONE short corrective instruction (a single sentence) telling it what to do
next. Do not restate the whole plan. Do not praise. Output only CONTINUE or the
single instruction."""

_AUTO_ROUTE_SYSTEM = """\
You are a routing agent in the Autumn framework.
Decide how the following mission should be handled:
- "direct": answer conversationally (questions, discussions, simple responses, creative requests)
- "convert": convert into a structured task for step-by-step execution \
(multi-step work, concrete actions, anything that benefits from a todo list)

Respond with ONLY valid JSON: {"route": "direct"} or {"route": "convert"}"""


def _duration_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def _capture_usage(api) -> tuple[int | None, int | None]:
    """Read and clear ``api.last_usage`` — returns ``(prompt_tokens, completion_tokens)``.

    Called immediately after a model invocation that the workflow wants to attribute
    to a specific WorkflowStage. Clearing prevents stale usage from leaking into a
    downstream stage whose call didn't return ``usage``. Tolerates mock APIs that
    don't expose ``last_usage`` (returns ``(None, None)``).
    """
    if api is None:
        return None, None
    usage = getattr(api, "last_usage", None) or {}
    try:
        api.last_usage = None
    except AttributeError:
        pass
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    if prompt is None and completion is None:
        return None, None
    return prompt, completion


def _classify_detail(input_type: InputType, task_type: TaskType | None) -> str:
    if input_type == InputType.TASK and task_type and task_type != TaskType.GENERAL:
        return f"输入被识别为 task · {task_type.value}"
    return f"输入被识别为 {input_type.value}"


def _make_stage(
    stage_id: str,
    title: str,
    detail: str,
    workspace: str,
    started: float,
    api=None,
) -> WorkflowStage:
    """Build a WorkflowStage, capturing and clearing token usage from ``api``."""
    prompt, completion = _capture_usage(api)
    return WorkflowStage(
        id=stage_id,
        title=title,
        detail=detail,
        workspace=workspace,
        duration_ms=_duration_ms(started),
        prompt_tokens=prompt,
        completion_tokens=completion,
    )


class WP1Tot(WorkspaceBase):
    """Total workspace. Orchestrates the full processing pipeline.

    Task path:          WP2(A2) → WP2.checker → WP1.checker → user
    Mission/direct:     WP3(A3) → WP1.checker → user
    Mission/convert:    WP3(A3 converts) → WP3.checker → WP1.checker
                        → WP2(A2) → WP2.checker → WP1.checker → user
    """

    def __init__(
        self,
        api,
        memory,
        wp2: WP2Tas,
        wp3: WP3Mis,
        wp4: "WP4Mem | None" = None,
        projects: "ProjectMemory | None" = None,
        mom1_access: "Mom1AccessBroker | None" = None,
        interaction: UserInteraction | None = None,
        selector_prompt: str | None = None,
        headless_mission_route: MissionRoute | Literal["auto"] = "auto",
        validate_before_stream: bool = True,
        confirm_threshold: float = 0.75,
        task_planning: bool = False,
        supervision: bool = False,
        archive: bool = False,
        capability_provider: Callable[[], str] | None = None,
    ):
        super().__init__(api, memory)
        self.wp2 = wp2
        self.wp3 = wp3
        # 0.3.0 cooperative-workflow wiring: A1 (组长) holds handles to the
        # memory-management workspace, project memory, and the Mom1 access broker
        # so it can supervise execution, query memory state, and lead project
        # parameter discussions instead of appearing only at route + final check.
        self.wp4 = wp4
        self.projects = projects
        self.mom1_access = mom1_access
        self.selector = Selector(
            api, system_prompt=selector_prompt, confirm_threshold=confirm_threshold,
            capability_provider=capability_provider,
        )
        self.interaction = interaction
        self._headless_route = headless_mission_route
        self._validate_before_stream = validate_before_stream
        self._task_planning = task_planning
        self._supervision = supervision
        self._archive = archive

    async def process(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
        input_type: InputType | None = None,
        task_type: TaskType | None = None,
    ) -> str:
        run = await self.process_with_trace(
            user_input,
            mission_route=mission_route,
            input_type=input_type,
            task_type=task_type,
        )
        return run.output

    async def process_with_trace(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
        input_type: InputType | None = None,
        task_type: TaskType | None = None,
        push_context: str = "",
        push_count: int = 0,
        push_ms: float | None = None,
    ) -> WorkflowRun:
        stages: list[WorkflowStage] = []

        if push_context:
            stages.append(WorkflowStage(
                id="wp4.push",
                title="4D 记忆推入",
                detail=f"推入 {push_count} 条激活记忆",
                workspace="WP4",
                kind="push",
                duration_ms=push_ms,
            ))

        t = time.perf_counter()
        sel = await self._select_intent(user_input, input_type=input_type, task_type=task_type)
        input_type = sel.input_type
        task_type = sel.task_type
        stages.append(_make_stage(
            "wp1.select", "A1 分类", _classify_detail(input_type, task_type), "WP1", t, self.api,
        ))

        if input_type == InputType.TASK:
            t = time.perf_counter()
            plan_hint = await self._plan_task(user_input, task_type)
            if plan_hint:
                stages.append(_make_stage(
                    "wp1.plan", "A1 制定计划", f"已生成执行计划（{len(plan_hint.splitlines())} 步）",
                    "WP1", t, self.api,
                ))
            interventions: list[dict] = []
            supervisor = self._build_supervisor(user_input, interventions)
            sup_started = time.perf_counter()
            t = time.perf_counter()
            result, tool_stages, wp2_prompt, wp2_completion = (
                await self.wp2.process_with_trace(
                    user_input, task_type=task_type, turn_context=push_context,
                    plan_hint=plan_hint, supervisor=supervisor,
                )
            )
            stages.extend(tool_stages)
            stages.extend(self._supervision_stages(interventions, sup_started))
            stages.append(WorkflowStage(
                id="wp2.task", title="A2 执行任务", detail="WP2 已完成结构化任务执行",
                workspace="WP2", duration_ms=_duration_ms(t),
                prompt_tokens=wp2_prompt, completion_tokens=wp2_completion,
            ))
            t = time.perf_counter()
            final, check_detail = await self._wp1_check(result)
            stages.append(_make_stage(
                "wp1.final_check", "A1 最终检查", check_detail, "WP1", t, self.api,
            ))
            chosen_route = None
        else:
            task_type = None  # task_type is not applicable for missions
            final, chosen_route = await self._route_mission_with_trace(
                user_input, stages, mission_route=mission_route, push_context=push_context,
            )

        await self.memory.append_history({
            "ts": time.time(),
            "input": user_input,
            "type": input_type.value,
            "route": chosen_route.value if chosen_route else None,
            "output": final,
        })
        # Archive the outcome to A4's curated shared memory (0.3.0 hand-off).
        await self._archive_execution(
            "wp2" if input_type == InputType.TASK else "wp3", user_input, final,
        )
        return WorkflowRun(
            output=final,
            input_type=input_type,
            route=chosen_route,
            stages=stages,
            task_type=task_type,
        )

    async def _route_mission_with_trace(
        self,
        mission_input: str,
        stages: list[WorkflowStage],
        mission_route: MissionRoute | Literal["auto"] | None = None,
        push_context: str = "",
    ) -> tuple[str, MissionRoute]:
        t = time.perf_counter()
        if self.interaction:
            chosen = await self.interaction.ask(
                "How should I handle this mission?",
                [r.value for r in MissionRoute],
            )
            route = MissionRoute(chosen)
        else:
            route = await self._resolve_headless_route(mission_input, mission_route)

        # auto_decide_route calls A3; headless/static paths don't. Capture either way.
        stages.append(_make_stage(
            "wp3.route", "A3 路由", f"Mission 路由为 {route.value}", "WP3", t, self.wp3.api,
        ))

        if route == MissionRoute.DIRECT:
            t = time.perf_counter()
            result, wp3_tool_stages, *_ = await self.wp3.answer_directly_with_trace(
                mission_input, turn_context=push_context,
            )
            stages.extend(wp3_tool_stages)
            stages.append(_make_stage(
                "wp3.direct", "A3 直接回答", "WP3 已生成 mission 回答", "WP3", t, self.wp3.api,
            ))
            t = time.perf_counter()
            final, check_detail = await self._wp1_check(result)
            stages.append(_make_stage(
                "wp1.final_check", "A1 最终检查", check_detail, "WP1", t, self.api,
            ))
            return final, route

        t = time.perf_counter()
        task_form = await self.wp3.convert_to_task(mission_input, turn_context=push_context)
        stages.append(_make_stage(
            "wp3.convert", "A3 转换任务", "WP3 已将 mission 转为可执行任务", "WP3", t, self.wp3.api,
        ))
        if self.wp3.checker:
            t = time.perf_counter()
            wp3_ok, wp3_checked = await self.wp3.checker.validate(task_form, self.wp3.memory)
            task_form, wp3_detail = _check_detail(
                wp3_ok, wp3_checked, "WP3 转换检查通过", "WP3 转换检查发现问题（已尽力修正）",
            )
            stages.append(_make_stage(
                "wp3.check", "WP3 检查", wp3_detail, "WP3", t, self.wp3.api,
            ))
        if self.checker:
            t = time.perf_counter()
            a1_ok, a1_checked = await self.checker.validate(task_form, self.memory)
            task_form, a1_detail = _check_detail(
                a1_ok, a1_checked, "A1 交接检查通过", "A1 交接检查发现问题（已尽力修正）",
            )
            stages.append(_make_stage(
                "wp1.handoff_check", "A1 交接检查", a1_detail, "WP1", t, self.api,
            ))

        t = time.perf_counter()
        result, tool_stages, wp2_prompt, wp2_completion = await self.wp2.process_with_trace(
            task_form, turn_context=push_context,
        )
        stages.extend(tool_stages)
        stages.append(WorkflowStage(
            id="wp2.task", title="A2 执行任务", detail="WP2 已完成转换任务执行",
            workspace="WP2", duration_ms=_duration_ms(t),
            prompt_tokens=wp2_prompt, completion_tokens=wp2_completion,
        ))
        t = time.perf_counter()
        final, check_detail = await self._wp1_check(result)
        stages.append(_make_stage(
            "wp1.final_check", "A1 最终检查", check_detail, "WP1", t, self.api,
        ))
        return final, route

    async def classify_intent(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
        input_type: InputType | None = None,
        task_type: TaskType | None = None,
    ) -> tuple[SelectorResult, MissionRoute | None]:
        sel = await self._select_intent(user_input, input_type=input_type, task_type=task_type)
        route: MissionRoute | None = None
        if sel.input_type == InputType.MISSION and mission_route not in (None, "auto"):
            route = mission_route
        return sel, route

    async def _select_intent(
        self,
        user_input: str,
        input_type: InputType | None = None,
        task_type: TaskType | None = None,
    ) -> SelectorResult:
        if input_type is not None:
            selected_task_type = (
                task_type or TaskType.GENERAL if input_type == InputType.TASK else None
            )
            return SelectorResult(input_type, 1.0, selected_task_type)

        sel = await self.selector.classify_and_maybe_confirm(user_input, self.interaction)
        if sel.input_type == InputType.TASK and task_type is not None:
            sel.task_type = task_type
        return sel

    async def _resolve_headless_route(
        self,
        mission_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
    ) -> MissionRoute:
        route = mission_route if mission_route is not None else self._headless_route
        if route != "auto":
            return route
        return await self._auto_decide_route(mission_input)

    async def _auto_decide_route(self, mission_input: str) -> MissionRoute:
        messages = [
            Message(role=Role.SYSTEM, content=_AUTO_ROUTE_SYSTEM),
            Message(role=Role.USER, content=mission_input),
        ]
        try:
            response = await self.wp3.api.complete(messages, max_tokens=32)
            data = json.loads(response.strip())
            return MissionRoute(data["route"])
        except (json.JSONDecodeError, KeyError, ValueError):
            return MissionRoute.DIRECT

    async def _plan_task(self, user_input: str, task_type: TaskType | None) -> str | None:
        """Ask A1 to generate a step-by-step execution plan before dispatching to WP2.

        Returns the plan text (to inject as WP2's plan_hint) or None when planning
        is disabled, the model call fails, or the output is empty.
        """
        if not self._task_planning:
            return None
        messages = [
            Message(role=Role.SYSTEM, content=_PLAN_TASK_SYSTEM),
            Message(role=Role.USER, content=user_input),
        ]
        try:
            plan = await self.api.complete(messages, max_tokens=256)
            return plan.strip() or None
        except Exception:
            return None

    def _build_supervisor(self, user_input: str, interventions: list[dict]):
        """Build an A1 supervisor callback for the WP2 agent loop, or None.

        Returns None unless supervision is enabled and A1 has an api. The callback
        reviews A2's latest step and returns a short corrective instruction (or
        nothing when on track). Each intervention is recorded in ``interventions``
        so the caller can surface it as a trace stage.
        """
        if not self._supervision or self.api is None:
            return None

        async def supervise(iteration: int, steps: list) -> str | None:
            if not steps:
                return None
            last = steps[-1]
            args = ", ".join(f"{k}={v}" for k, v in getattr(last, "arguments", {}).items())
            result = getattr(last, "result", "")
            if len(result) > 400:
                result = result[:400] + "…"
            review = (
                f"Original task:\n{user_input}\n\n"
                f"A2's latest action (step {iteration + 1}): {getattr(last, 'name', '?')}({args})\n"
                f"Result: {result}"
            )
            messages = [
                Message(role=Role.SYSTEM, content=_SUPERVISE_SYSTEM),
                Message(role=Role.USER, content=review),
            ]
            try:
                reply = (await self.api.complete(messages, max_tokens=80)).strip()
            except Exception:
                return None
            if not reply or reply.upper().startswith("CONTINUE"):
                return None
            interventions.append({"iteration": iteration, "guidance": reply})
            return reply

        return supervise

    def _supervision_stages(self, interventions: list[dict], started: float) -> list[WorkflowStage]:
        """Render recorded A1 supervision interventions as trace stages."""
        stages: list[WorkflowStage] = []
        for i, item in enumerate(interventions):
            stages.append(WorkflowStage(
                id=f"wp1.supervise.{i}",
                title="A1 监督介入",
                detail=f"步骤 {item['iteration'] + 1}：{item['guidance']}",
                workspace="WP1",
                kind="stage",
                duration_ms=_duration_ms(started),
            ))
        return stages

    async def _archive_execution(self, source: str, user_input: str, output: str) -> None:
        """Hand a completed turn's outcome to A4 for a shared-zone summary.

        Best-effort and gated by the archive flag + a wired WP4; never raises.
        """
        if not self._archive or self.wp4 is None:
            return
        try:
            await self.wp4.record_execution_summary(source, user_input, output)
        except Exception:
            pass

    async def _wp1_check(self, output: str) -> tuple[str, str]:
        if not self.checker:
            return output, "WP1 已完成最终质量检查"
        ok, checked = await self.checker.validate(output, self.memory)
        return _check_detail(ok, checked, "WP1 质量检查通过", "WP1 质量检查发现问题（已尽力修正）")

    # ── streaming ─────────────────────────────────────────────────────────────

    async def stream(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
        input_type: InputType | None = None,
        task_type: TaskType | None = None,
        chunk_size: int = 48,
    ) -> AsyncIterator[str]:
        async for event in self.stream_with_trace(
            user_input,
            mission_route=mission_route,
            input_type=input_type,
            task_type=task_type,
            chunk_size=chunk_size,
        ):
            if isinstance(event, str):
                yield event

    async def stream_with_trace(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
        input_type: InputType | None = None,
        task_type: TaskType | None = None,
        chunk_size: int = 48,
        push_context: str = "",
        push_count: int = 0,
        push_ms: float | None = None,
    ) -> AsyncIterator[str | WorkflowRun]:
        """Stream chunks and finish with the ``WorkflowRun`` for the same turn.

        Two modes, controlled by ``AutumnConfig.validate_before_stream``:

        * ``True`` (default): run the full validated pipeline first, then chunk
          the validated output and finally yield the trace.
        * ``False``: classify once, forward live tokens from the chosen
          workspace, then run the checker as an advisory and yield the trace.
        """
        if self._validate_before_stream:
            run = await self.process_with_trace(
                user_input,
                mission_route=mission_route,
                input_type=input_type,
                task_type=task_type,
                push_context=push_context,
                push_count=push_count,
                push_ms=push_ms,
            )
            for i in range(0, len(run.output), chunk_size):
                yield run.output[i:i + chunk_size]
                await asyncio.sleep(0)
            yield run
            return

        stages: list[WorkflowStage] = []
        tool_stages: list[WorkflowStage] = []

        if push_context:
            stages.append(WorkflowStage(
                id="wp4.push",
                title="4D 记忆推入",
                detail=f"推入 {push_count} 条激活记忆",
                workspace="WP4",
                kind="push",
                duration_ms=push_ms,
            ))

        t = time.perf_counter()
        sel = await self._select_intent(user_input, input_type=input_type, task_type=task_type)
        input_type = sel.input_type
        task_type = sel.task_type
        stages.append(_make_stage(
            "wp1.select", "A1 分类", _classify_detail(input_type, task_type), "WP1", t, self.api,
        ))

        interventions: list[dict] = []
        sup_started = time.perf_counter()
        if input_type == InputType.TASK:
            t = time.perf_counter()
            plan_hint = await self._plan_task(user_input, task_type)
            if plan_hint:
                stages.append(_make_stage(
                    "wp1.plan", "A1 制定计划", f"已生成执行计划（{len(plan_hint.splitlines())} 步）",
                    "WP1", t, self.api,
                ))
            supervisor = self._build_supervisor(user_input, interventions)
            task_started = time.perf_counter()
            gen = self.wp2.stream_with_trace(
                user_input, task_type=task_type, chunk_size=chunk_size, turn_context=push_context,
                plan_hint=plan_hint, supervisor=supervisor,
            )
            chosen_route: MissionRoute | None = None
        else:
            task_type = None  # task_type is not applicable for missions
            t = time.perf_counter()
            route = await self._resolve_headless_route(user_input, mission_route)
            chosen_route = route
            stages.append(_make_stage(
                "wp3.route", "A3 路由", f"Mission 路由为 {route.value}", "WP3", t, self.wp3.api,
            ))
            if route == MissionRoute.DIRECT:
                direct_started = time.perf_counter()
                gen = self.wp3.stream_direct(user_input, turn_context=push_context)
            else:
                t = time.perf_counter()
                task_form = await self.wp3.convert_to_task(user_input, turn_context=push_context)
                stages.append(_make_stage(
                    "wp3.convert", "A3 转换任务",
                    "WP3 已将 mission 转为可执行任务", "WP3", t, self.wp3.api,
                ))
                if self.wp3.checker:
                    t = time.perf_counter()
                    wp3_ok, wp3_checked = await self.wp3.checker.validate(task_form, self.wp3.memory)
                    task_form, wp3_detail = _check_detail(
                        wp3_ok, wp3_checked, "WP3 转换检查通过", "WP3 转换检查发现问题（已尽力修正）",
                    )
                    stages.append(_make_stage(
                        "wp3.check", "WP3 检查", wp3_detail, "WP3", t, self.wp3.api,
                    ))
                if self.checker:
                    t = time.perf_counter()
                    a1_ok, a1_checked = await self.checker.validate(task_form, self.memory)
                    task_form, a1_detail = _check_detail(
                        a1_ok, a1_checked, "A1 交接检查通过", "A1 交接检查发现问题（已尽力修正）",
                    )
                    stages.append(_make_stage(
                        "wp1.handoff_check", "A1 交接检查", a1_detail, "WP1", t, self.api,
                    ))
                task_started = time.perf_counter()
                gen = self.wp2.stream_with_trace(
                    task_form, chunk_size=chunk_size, turn_context=push_context,
                )

        buf: list[str] = []
        async for event in gen:
            if isinstance(event, str):
                buf.append(event)
                yield event
            else:
                tool_stages.extend(event)

        if input_type == InputType.TASK:
            stages.extend(tool_stages)
            stages.extend(self._supervision_stages(interventions, sup_started))
            stages.append(WorkflowStage(
                id="wp2.task", title="A2 执行任务",
                detail="WP2 已完成结构化任务执行",
                workspace="WP2", duration_ms=_duration_ms(task_started),
            ))
        elif chosen_route == MissionRoute.DIRECT:
            stages.extend(tool_stages)
            stages.append(WorkflowStage(
                id="wp3.direct", title="A3 直接回答",
                detail="WP3 已生成 mission 回答",
                workspace="WP3", duration_ms=_duration_ms(direct_started),
            ))
        else:
            stages.extend(tool_stages)
            stages.append(WorkflowStage(
                id="wp2.task", title="A2 执行任务",
                detail="WP2 已完成转换任务执行",
                workspace="WP2", duration_ms=_duration_ms(task_started),
            ))

        full = "".join(buf)

        # Post-hoc advisory: rule check + model check, no auto-correction.
        t = time.perf_counter()
        if self.checker:
            ok, issues = await self.checker.inspect(full, self.memory)
            if not ok and issues:
                advisory = f"{_ADVISORY_PREFIX}{issues}"
                buf.append(advisory)
                yield advisory
        stages.append(_make_stage(
            "wp1.final_check", "A1 最终检查", "WP1 已完成流式输出观察检查", "WP1", t, self.api,
        ))

        # Mom1 carries the full conversation log; mirror process_with_trace().
        final_output = "".join(buf)
        await self.memory.append_history({
            "ts": time.time(),
            "input": user_input,
            "type": input_type.value,
            "route": chosen_route.value if chosen_route else None,
            "output": final_output,
        })
        await self._archive_execution(
            "wp2" if input_type == InputType.TASK else "wp3", user_input, final_output,
        )
        yield WorkflowRun(
            output=final_output,
            input_type=input_type,
            route=chosen_route,
            stages=stages,
            task_type=task_type if input_type == InputType.TASK else None,
        )

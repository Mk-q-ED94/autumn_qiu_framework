import asyncio
import json
import time
from typing import AsyncIterator, Literal
from .base import WorkspaceBase
from .wp2 import WP2Tas
from .wp3 import WP3Mis
from ..types import (
    InputType,
    TaskType,
    MissionRoute,
    Message,
    Role,
    SelectorResult,
    WorkflowRun,
    WorkflowStage,
)
from ..components.selector import Selector
from ..interaction import UserInteraction

_ADVISORY_PREFIX = "\n\n---\n[质量提示] "

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
        interaction: UserInteraction | None = None,
        selector_prompt: str | None = None,
        headless_mission_route: MissionRoute | Literal["auto"] = "auto",
        validate_before_stream: bool = True,
    ):
        super().__init__(api, memory)
        self.wp2 = wp2
        self.wp3 = wp3
        self.selector = Selector(api, system_prompt=selector_prompt)
        self.interaction = interaction
        self._headless_route = headless_mission_route
        self._validate_before_stream = validate_before_stream

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
    ) -> WorkflowRun:
        stages: list[WorkflowStage] = []
        select_started = time.perf_counter()
        sel = await self._select_intent(user_input, input_type=input_type, task_type=task_type)
        input_type = sel.input_type
        task_type = sel.task_type
        select_prompt, select_completion = _capture_usage(self.api)
        stages.append(WorkflowStage(
            id="wp1.select",
            title="A1 分类",
            detail=_classify_detail(input_type, task_type),
            workspace="WP1",
            duration_ms=_duration_ms(select_started),
            prompt_tokens=select_prompt,
            completion_tokens=select_completion,
        ))

        if input_type == InputType.TASK:
            task_started = time.perf_counter()
            result, tool_stages, wp2_prompt, wp2_completion = (
                await self.wp2.process_with_trace(user_input, task_type=task_type)
            )
            stages.extend(tool_stages)
            stages.append(WorkflowStage(
                id="wp2.task",
                title="A2 执行任务",
                detail="WP2 已完成结构化任务执行",
                workspace="WP2",
                duration_ms=_duration_ms(task_started),
                prompt_tokens=wp2_prompt,
                completion_tokens=wp2_completion,
            ))
            check_started = time.perf_counter()
            final = await self._wp1_check(result)
            check_prompt, check_completion = _capture_usage(self.api)
            stages.append(WorkflowStage(
                id="wp1.final_check",
                title="A1 最终检查",
                detail="WP1 已完成最终质量检查",
                workspace="WP1",
                duration_ms=_duration_ms(check_started),
                prompt_tokens=check_prompt,
                completion_tokens=check_completion,
            ))
            chosen_route = None
        else:
            task_type = None  # task_type is not applicable for missions
            final, chosen_route = await self._route_mission_with_trace(
                user_input,
                stages,
                mission_route=mission_route,
            )

        await self.memory.append_history({
            "ts": time.time(),
            "input": user_input,
            "type": input_type.value,
            "route": chosen_route.value if chosen_route else None,
            "output": final,
        })
        return WorkflowRun(
            output=final,
            input_type=input_type,
            route=chosen_route,
            stages=stages,
            task_type=task_type,
        )

    async def _route_task(self, task_input: str) -> str:
        result = await self.wp2.process(task_input)
        return await self._wp1_check(result)

    async def _route_mission_returning_route(
        self,
        mission_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
    ) -> tuple[str, MissionRoute]:
        if self.interaction:
            chosen = await self.interaction.ask(
                "How should I handle this mission?",
                [r.value for r in MissionRoute],
            )
            route = MissionRoute(chosen)
        else:
            route = await self._resolve_headless_route(mission_input, mission_route)

        if route == MissionRoute.DIRECT:
            result = await self.wp3.answer_directly(mission_input)
            return await self._wp1_check(result), route

        # Convert path
        task_form = await self.wp3.convert_to_task(mission_input)
        if self.wp3.checker:
            _, task_form = await self.wp3.checker.validate(task_form, self.wp3.memory)
        if self.checker:
            _, task_form = await self.checker.validate(task_form, self.memory)
        return await self._route_task(task_form), route

    async def _route_mission_with_trace(
        self,
        mission_input: str,
        stages: list[WorkflowStage],
        mission_route: MissionRoute | Literal["auto"] | None = None,
    ) -> tuple[str, MissionRoute]:
        route_started = time.perf_counter()
        if self.interaction:
            chosen = await self.interaction.ask(
                "How should I handle this mission?",
                [r.value for r in MissionRoute],
            )
            route = MissionRoute(chosen)
        else:
            route = await self._resolve_headless_route(mission_input, mission_route)

        # auto_decide_route calls A3; headless/static paths don't. Capture either way.
        route_prompt, route_completion = _capture_usage(self.wp3.api)
        stages.append(WorkflowStage(
            id="wp3.route",
            title="A3 路由",
            detail=f"Mission 路由为 {route.value}",
            workspace="WP3",
            duration_ms=_duration_ms(route_started),
            prompt_tokens=route_prompt,
            completion_tokens=route_completion,
        ))

        if route == MissionRoute.DIRECT:
            direct_started = time.perf_counter()
            result = await self.wp3.answer_directly(mission_input)
            direct_prompt, direct_completion = _capture_usage(self.wp3.api)
            stages.append(WorkflowStage(
                id="wp3.direct",
                title="A3 直接回答",
                detail="WP3 已生成 mission 回答",
                workspace="WP3",
                duration_ms=_duration_ms(direct_started),
                prompt_tokens=direct_prompt,
                completion_tokens=direct_completion,
            ))
            check_started = time.perf_counter()
            final = await self._wp1_check(result)
            check_prompt, check_completion = _capture_usage(self.api)
            stages.append(WorkflowStage(
                id="wp1.final_check",
                title="A1 最终检查",
                detail="WP1 已完成最终质量检查",
                workspace="WP1",
                duration_ms=_duration_ms(check_started),
                prompt_tokens=check_prompt,
                completion_tokens=check_completion,
            ))
            return final, route

        convert_started = time.perf_counter()
        task_form = await self.wp3.convert_to_task(mission_input)
        convert_prompt, convert_completion = _capture_usage(self.wp3.api)
        stages.append(WorkflowStage(
            id="wp3.convert",
            title="A3 转换任务",
            detail="WP3 已将 mission 转为可执行任务",
            workspace="WP3",
            duration_ms=_duration_ms(convert_started),
            prompt_tokens=convert_prompt,
            completion_tokens=convert_completion,
        ))
        if self.wp3.checker:
            check_started = time.perf_counter()
            _, task_form = await self.wp3.checker.validate(task_form, self.wp3.memory)
            wp3check_prompt, wp3check_completion = _capture_usage(self.wp3.api)
            stages.append(WorkflowStage(
                id="wp3.check",
                title="WP3 检查",
                detail="转换后的任务已通过 WP3 检查",
                workspace="WP3",
                duration_ms=_duration_ms(check_started),
                prompt_tokens=wp3check_prompt,
                completion_tokens=wp3check_completion,
            ))
        if self.checker:
            handoff_started = time.perf_counter()
            _, task_form = await self.checker.validate(task_form, self.memory)
            handoff_prompt, handoff_completion = _capture_usage(self.api)
            stages.append(WorkflowStage(
                id="wp1.handoff_check",
                title="A1 交接检查",
                detail="A1 已检查 mission 到 task 的交接内容",
                workspace="WP1",
                duration_ms=_duration_ms(handoff_started),
                prompt_tokens=handoff_prompt,
                completion_tokens=handoff_completion,
            ))

        task_started = time.perf_counter()
        result, tool_stages, wp2_prompt, wp2_completion = await self.wp2.process_with_trace(task_form)
        stages.extend(tool_stages)
        stages.append(WorkflowStage(
            id="wp2.task",
            title="A2 执行任务",
            detail="WP2 已完成转换任务执行",
            workspace="WP2",
            duration_ms=_duration_ms(task_started),
            prompt_tokens=wp2_prompt,
            completion_tokens=wp2_completion,
        ))
        check_started = time.perf_counter()
        final = await self._wp1_check(result)
        check_prompt, check_completion = _capture_usage(self.api)
        stages.append(WorkflowStage(
            id="wp1.final_check",
            title="A1 最终检查",
            detail="WP1 已完成最终质量检查",
            workspace="WP1",
            duration_ms=_duration_ms(check_started),
            prompt_tokens=check_prompt,
            completion_tokens=check_completion,
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
            selected_task_type = task_type if input_type == InputType.TASK else None
            if input_type == InputType.TASK and selected_task_type is None:
                selected_task_type = TaskType.GENERAL
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

    async def _wp1_check(self, output: str) -> str:
        if self.checker:
            _, output = await self.checker.validate(output, self.memory)
        return output

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
            )
            for i in range(0, len(run.output), chunk_size):
                yield run.output[i:i + chunk_size]
                await asyncio.sleep(0)
            yield run
            return

        stages: list[WorkflowStage] = []
        tool_stages: list[WorkflowStage] = []

        select_started = time.perf_counter()
        sel = await self._select_intent(user_input, input_type=input_type, task_type=task_type)
        input_type = sel.input_type
        task_type = sel.task_type
        select_prompt, select_completion = _capture_usage(self.api)
        stages.append(WorkflowStage(
            id="wp1.select",
            title="A1 分类",
            detail=_classify_detail(input_type, task_type),
            workspace="WP1",
            duration_ms=_duration_ms(select_started),
            prompt_tokens=select_prompt,
            completion_tokens=select_completion,
        ))

        if input_type == InputType.TASK:
            task_started = time.perf_counter()
            gen = self.wp2.stream_with_trace(
                user_input,
                task_type=task_type,
                chunk_size=chunk_size,
            )
            chosen_route: MissionRoute | None = None
        else:
            task_type = None  # task_type is not applicable for missions
            route_started = time.perf_counter()
            route = await self._resolve_headless_route(user_input, mission_route)
            chosen_route = route
            route_prompt, route_completion = _capture_usage(self.wp3.api)
            stages.append(WorkflowStage(
                id="wp3.route",
                title="A3 路由",
                detail=f"Mission 路由为 {route.value}",
                workspace="WP3",
                duration_ms=_duration_ms(route_started),
                prompt_tokens=route_prompt,
                completion_tokens=route_completion,
            ))
            if route == MissionRoute.DIRECT:
                direct_started = time.perf_counter()
                gen = self.wp3.stream_direct(user_input)
            else:
                convert_started = time.perf_counter()
                task_form = await self.wp3.convert_to_task(user_input)
                convert_prompt, convert_completion = _capture_usage(self.wp3.api)
                stages.append(WorkflowStage(
                    id="wp3.convert",
                    title="A3 转换任务",
                    detail="WP3 已将 mission 转为可执行任务",
                    workspace="WP3",
                    duration_ms=_duration_ms(convert_started),
                    prompt_tokens=convert_prompt,
                    completion_tokens=convert_completion,
                ))
                if self.wp3.checker:
                    check_started = time.perf_counter()
                    _, task_form = await self.wp3.checker.validate(task_form, self.wp3.memory)
                    wp3check_prompt, wp3check_completion = _capture_usage(self.wp3.api)
                    stages.append(WorkflowStage(
                        id="wp3.check",
                        title="WP3 检查",
                        detail="转换后的任务已通过 WP3 检查",
                        workspace="WP3",
                        duration_ms=_duration_ms(check_started),
                        prompt_tokens=wp3check_prompt,
                        completion_tokens=wp3check_completion,
                    ))
                if self.checker:
                    handoff_started = time.perf_counter()
                    _, task_form = await self.checker.validate(task_form, self.memory)
                    handoff_prompt, handoff_completion = _capture_usage(self.api)
                    stages.append(WorkflowStage(
                        id="wp1.handoff_check",
                        title="A1 交接检查",
                        detail="A1 已检查 mission 到 task 的交接内容",
                        workspace="WP1",
                        duration_ms=_duration_ms(handoff_started),
                        prompt_tokens=handoff_prompt,
                        completion_tokens=handoff_completion,
                    ))
                task_started = time.perf_counter()
                gen = self.wp2.stream_with_trace(task_form, chunk_size=chunk_size)

        buf: list[str] = []
        async for event in gen:
            if isinstance(event, str):
                buf.append(event)
                yield event
            else:
                tool_stages.extend(event)

        if input_type == InputType.TASK:
            stages.extend(tool_stages)
            stages.append(WorkflowStage(
                id="wp2.task",
                title="A2 执行任务",
                detail="WP2 已完成结构化任务执行",
                workspace="WP2",
                duration_ms=_duration_ms(task_started),
            ))
        elif chosen_route == MissionRoute.DIRECT:
            stages.append(WorkflowStage(
                id="wp3.direct",
                title="A3 直接回答",
                detail="WP3 已生成 mission 回答",
                workspace="WP3",
                duration_ms=_duration_ms(direct_started),
            ))
        else:
            stages.extend(tool_stages)
            stages.append(WorkflowStage(
                id="wp2.task",
                title="A2 执行任务",
                detail="WP2 已完成转换任务执行",
                workspace="WP2",
                duration_ms=_duration_ms(task_started),
            ))

        full = "".join(buf)

        # Post-hoc advisory: rule check + model check, no auto-correction.
        check_started = time.perf_counter()
        if self.checker:
            ok, issues = await self.checker.inspect(full, self.memory)
            check_prompt, check_completion = _capture_usage(self.api)
            if not ok and issues:
                advisory = f"{_ADVISORY_PREFIX}{issues}"
                buf.append(advisory)
                yield advisory
        else:
            check_prompt, check_completion = None, None
        stages.append(WorkflowStage(
            id="wp1.final_check",
            title="A1 最终检查",
            detail="WP1 已完成流式输出观察检查",
            workspace="WP1",
            duration_ms=_duration_ms(check_started),
            prompt_tokens=check_prompt,
            completion_tokens=check_completion,
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
        yield WorkflowRun(
            output=final_output,
            input_type=input_type,
            route=chosen_route,
            stages=stages,
            task_type=task_type if input_type == InputType.TASK else None,
        )

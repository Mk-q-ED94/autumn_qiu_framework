import json
import time
from typing import Literal
from .base import WorkspaceBase
from .wp2 import WP2Tas
from .wp3 import WP3Mis
from ..types import InputType, TaskType, MissionRoute, Message, Role, WorkflowRun, WorkflowStage
from ..components.selector import Selector
from ..interaction import UserInteraction

_AUTO_ROUTE_SYSTEM = """\
You are a routing agent in the Autumn framework.
Decide how the following mission should be handled:
- "direct": answer conversationally (questions, discussions, simple responses, creative requests)
- "convert": convert into a structured task for step-by-step execution \
(multi-step work, concrete actions, anything that benefits from a todo list)

Respond with ONLY valid JSON: {"route": "direct"} or {"route": "convert"}"""


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
    ):
        super().__init__(api, memory)
        self.wp2 = wp2
        self.wp3 = wp3
        self.selector = Selector(api, system_prompt=selector_prompt)
        self.interaction = interaction
        self._headless_route = headless_mission_route

    async def process(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
    ) -> str:
        run = await self.process_with_trace(user_input, mission_route=mission_route)
        return run.output

    async def process_with_trace(
        self,
        user_input: str,
        mission_route: MissionRoute | Literal["auto"] | None = None,
    ) -> WorkflowRun:
        stages: list[WorkflowStage] = []
        sel = await self.selector.classify_and_maybe_confirm(user_input, self.interaction)
        input_type = sel.input_type
        task_type = sel.task_type
        stages.append(WorkflowStage(
            id="wp1.select",
            title="A1 分类",
            detail=_classify_detail(input_type, task_type),
            workspace="WP1",
        ))

        if input_type == InputType.TASK:
            result, tool_stages = await self.wp2.process_with_trace(user_input, task_type=task_type)
            stages.extend(tool_stages)
            stages.append(WorkflowStage(
                id="wp2.task",
                title="A2 执行任务",
                detail="WP2 已完成结构化任务执行",
                workspace="WP2",
            ))
            final = await self._wp1_check(result)
            stages.append(WorkflowStage(
                id="wp1.final_check",
                title="A1 最终检查",
                detail="WP1 已完成最终质量检查",
                workspace="WP1",
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
        if self.interaction:
            chosen = await self.interaction.ask(
                "How should I handle this mission?",
                [r.value for r in MissionRoute],
            )
            route = MissionRoute(chosen)
        else:
            route = await self._resolve_headless_route(mission_input, mission_route)

        stages.append(WorkflowStage(
            id="wp3.route",
            title="A3 路由",
            detail=f"Mission 路由为 {route.value}",
            workspace="WP3",
        ))

        if route == MissionRoute.DIRECT:
            result = await self.wp3.answer_directly(mission_input)
            stages.append(WorkflowStage(
                id="wp3.direct",
                title="A3 直接回答",
                detail="WP3 已生成 mission 回答",
                workspace="WP3",
            ))
            final = await self._wp1_check(result)
            stages.append(WorkflowStage(
                id="wp1.final_check",
                title="A1 最终检查",
                detail="WP1 已完成最终质量检查",
                workspace="WP1",
            ))
            return final, route

        task_form = await self.wp3.convert_to_task(mission_input)
        stages.append(WorkflowStage(
            id="wp3.convert",
            title="A3 转换任务",
            detail="WP3 已将 mission 转为可执行任务",
            workspace="WP3",
        ))
        if self.wp3.checker:
            _, task_form = await self.wp3.checker.validate(task_form, self.wp3.memory)
            stages.append(WorkflowStage(
                id="wp3.check",
                title="WP3 检查",
                detail="转换后的任务已通过 WP3 检查",
                workspace="WP3",
            ))
        if self.checker:
            _, task_form = await self.checker.validate(task_form, self.memory)
            stages.append(WorkflowStage(
                id="wp1.handoff_check",
                title="A1 交接检查",
                detail="A1 已检查 mission 到 task 的交接内容",
                workspace="WP1",
            ))

        result, tool_stages = await self.wp2.process_with_trace(task_form)
        stages.extend(tool_stages)
        stages.append(WorkflowStage(
            id="wp2.task",
            title="A2 执行任务",
            detail="WP2 已完成转换任务执行",
            workspace="WP2",
        ))
        final = await self._wp1_check(result)
        stages.append(WorkflowStage(
            id="wp1.final_check",
            title="A1 最终检查",
            detail="WP1 已完成最终质量检查",
            workspace="WP1",
        ))
        return final, route

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

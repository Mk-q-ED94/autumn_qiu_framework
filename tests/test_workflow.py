import pytest
from autumn.core.interaction import UserInteraction, CLIInteraction
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.mom1 import Mom1
from autumn.core.memory.mom2 import Mom2
from autumn.core.memory.mom3 import Mom3
from autumn.core.memory.shared import SharedZone
from autumn.core.types import MissionRoute
from autumn.core.workspace.wp1 import WP1Tot
from autumn.core.workspace.wp2 import WP2Tas
from autumn.core.workspace.wp3 import WP3Mis


class MockAPI:
    async def complete(self, messages, **kwargs):
        system = messages[0].content
        if "input classifier" in system:
            return '{"type": "mission", "confidence": 0.99}'
        if "Convert the following mission" in system:
            return "Converted task with enough detail."
        if "precise task executor" in system:
            return "Executed converted task."
        if "routing agent" in system:
            return '{"route": "direct"}'
        return "Direct mission answer."


class MockInteraction(UserInteraction):
    """Scripted interaction for testing: pops responses in order."""

    def __init__(self, responses: list[str]):
        self._queue = list(responses)

    async def ask(self, question: str, options: list[str]) -> str:
        assert self._queue, f"MockInteraction ran out of responses. Question: {question!r}"
        response = self._queue.pop(0)
        assert response in options, f"{response!r} not in options {options}"
        return response


def test_mock_interaction_returns_in_order():
    mock = MockInteraction(["task", "direct"])
    import asyncio

    async def run():
        r1 = await mock.ask("q1", ["task", "mission"])
        r2 = await mock.ask("q2", ["direct", "convert"])
        return r1, r2

    r1, r2 = asyncio.run(run())
    assert r1 == "task"
    assert r2 == "direct"


def test_mock_interaction_validates_options():
    mock = MockInteraction(["invalid"])
    import asyncio

    async def run():
        await mock.ask("q", ["task", "mission"])

    with pytest.raises(AssertionError):
        asyncio.run(run())


def test_cli_interaction_is_user_interaction():
    assert issubclass(CLIInteraction, UserInteraction)


async def test_wp1_process_accepts_per_request_route_override():
    shared = SharedZone(DictBackend())
    mom2 = Mom2(DictBackend(), shared)
    mom3 = Mom3(DictBackend(), shared)
    mom1 = Mom1(DictBackend(), mom2, mom3)
    api = MockAPI()

    wp2 = WP2Tas(api, mom2)
    wp3 = WP3Mis(api, mom3)
    wp1 = WP1Tot(api, mom1, wp2, wp3, headless_mission_route="auto")

    result = await wp1.process("Turn this into an execution plan.", mission_route=MissionRoute.CONVERT)

    assert result == "Executed converted task."
    history = await mom1.get_history()
    assert history[-1]["route"] == "convert"

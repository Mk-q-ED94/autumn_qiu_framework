import pytest
from autumn.core.interaction import UserInteraction, CLIInteraction
from autumn.core.types import InputType, MissionRoute


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

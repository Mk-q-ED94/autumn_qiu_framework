"""Tests for ``WP1Tot._auto_decide_route``: the JSON-from-A3 routing path.

The model is asked to emit ``{"route": "direct"}`` or ``{"route": "convert"}``.
A broken response must NOT crash the turn — it falls back to DIRECT so the
user still gets an answer. These tests pin that defensive contract.
"""
import pytest

from autumn.core.memory.backends import DictBackend
from autumn.core.memory.mom1 import Mom1
from autumn.core.memory.mom2 import Mom2
from autumn.core.memory.mom3 import Mom3
from autumn.core.memory.shared import SharedZone
from autumn.core.types import MissionRoute
from autumn.core.workspace.wp1 import WP1Tot
from autumn.core.workspace.wp2 import WP2Tas
from autumn.core.workspace.wp3 import WP3Mis


class _ScriptedAPI:
    """Tiny stand-in for a ModelAPIInterface: returns a fixed completion."""

    def __init__(self, response: str):
        self._response = response
        self.calls: list[list] = []

    async def complete(self, messages, **kwargs):
        self.calls.append(list(messages))
        return self._response


def _make_wp1(a3_response: str) -> tuple[WP1Tot, _ScriptedAPI]:
    """Build a WP1Tot whose WP3.api returns ``a3_response`` from complete()."""
    a1_api = _ScriptedAPI("unused")
    a3_api = _ScriptedAPI(a3_response)

    shared = SharedZone(DictBackend())
    mom2 = Mom2(DictBackend(), shared)
    mom3 = Mom3(DictBackend(), shared)
    mom1 = Mom1(DictBackend(), mom2, mom3)

    wp2 = WP2Tas(a1_api, mom2)
    wp3 = WP3Mis(a3_api, mom3)
    wp1 = WP1Tot(a1_api, mom1, wp2, wp3)
    return wp1, a3_api


async def test_auto_decide_route_picks_direct_from_valid_json():
    wp1, a3 = _make_wp1('{"route": "direct"}')
    route = await wp1._auto_decide_route("how are you?")
    assert route == MissionRoute.DIRECT
    assert len(a3.calls) == 1  # A3 was consulted


async def test_auto_decide_route_picks_convert_from_valid_json():
    wp1, _ = _make_wp1('{"route": "convert"}')
    route = await wp1._auto_decide_route("build me a plan")
    assert route == MissionRoute.CONVERT


async def test_auto_decide_route_invalid_json_defaults_to_direct():
    """A model that emits malformed JSON must NOT crash the whole turn."""
    wp1, _ = _make_wp1("not even close to JSON")
    route = await wp1._auto_decide_route("hello")
    assert route == MissionRoute.DIRECT


async def test_auto_decide_route_missing_key_defaults_to_direct():
    wp1, _ = _make_wp1('{"verdict": "direct"}')  # right shape, wrong key
    route = await wp1._auto_decide_route("hello")
    assert route == MissionRoute.DIRECT


async def test_auto_decide_route_unknown_route_value_defaults_to_direct():
    """An unknown enum value (typo / hallucination) falls back to DIRECT instead
    of bubbling a ValueError up through the streaming generator."""
    wp1, _ = _make_wp1('{"route": "convertify"}')
    route = await wp1._auto_decide_route("hello")
    assert route == MissionRoute.DIRECT

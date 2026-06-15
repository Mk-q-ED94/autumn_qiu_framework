"""P3-B tests: user profile track (rewrite semantics, scoped) + A4 synthesis."""
from autumn.core.memory.backends import DictBackend
from autumn.core.memory.base import MemoryArea
from autumn.core.memory.kinds import KIND_PROFILE


class _ProfileAPI:
    def __init__(self, reply: str):
        self.reply = reply
        self.seen_user: str | None = None

    async def complete(self, messages):
        self.seen_user = messages[1].content
        return self.reply


# ── set / get with rewrite semantics ────────────────────────────────────────────

async def test_set_and_get_profile():
    area = MemoryArea("mom1", DictBackend())
    await area.set_profile("Likes dark mode.", scope="jin")
    assert await area.get_profile(scope="jin") == "Likes dark mode."


async def test_get_profile_default_none():
    area = MemoryArea("mom1", DictBackend())
    assert await area.get_profile(scope="nobody") is None


async def test_set_profile_rewrites_not_appends():
    area = MemoryArea("mom1", DictBackend())
    await area.set_profile("v1", scope="jin")
    await area.set_profile("v2", scope="jin")
    assert await area.get_profile(scope="jin") == "v2"
    entries = await area.get_history(tags=[KIND_PROFILE, "scope:jin"])
    assert len(entries) == 1  # one living profile per scope


async def test_profiles_are_scope_isolated():
    area = MemoryArea("mom1", DictBackend())
    await area.set_profile("jin profile", scope="jin")
    await area.set_profile("amy profile", scope="amy")
    assert await area.get_profile(scope="jin") == "jin profile"
    assert await area.get_profile(scope="amy") == "amy profile"


async def test_profile_is_pinned():
    area = MemoryArea("mom1", DictBackend())
    entry = await area.set_profile("resident preferences", scope="jin")
    assert entry.is_pinned


async def test_profile_survives_eviction_pressure():
    area = MemoryArea("mom1", DictBackend(), history_limit=3)
    await area.set_profile("keep me", scope="jin")
    for i in range(10):
        await area.append_history(f"chatter {i}")
    assert await area.get_profile(scope="jin") == "keep me"  # pinned, never evicted


# ── A4 synthesis ────────────────────────────────────────────────────────────────

async def test_synthesize_profile_folds_history():
    area = MemoryArea("mom1", DictBackend())
    await area.set_profile("Likes dark mode.", scope="jin")
    await area.append_history("user said they prefer terse answers")
    api = _ProfileAPI("Likes dark mode. Prefers terse answers.")

    updated = await area.synthesize_profile(api, scope="jin")
    assert updated == "Likes dark mode. Prefers terse answers."
    assert await area.get_profile(scope="jin") == updated
    # the current profile was provided to the model for merging
    assert "Likes dark mode." in api.seen_user
    # the existing profile entry is not itself fed back as a source
    assert "Prefers terse answers" not in api.seen_user


async def test_synthesize_profile_no_sources_is_none():
    area = MemoryArea("mom1", DictBackend())
    assert await area.synthesize_profile(_ProfileAPI("x"), scope="jin") is None

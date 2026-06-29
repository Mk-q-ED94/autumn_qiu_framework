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


# ── only_new: incremental synthesis (per-turn auto path) ────────────────────────

async def test_synthesize_profile_only_new_first_pass_folds_all():
    """With no existing profile, only_new still folds everything (bootstrap)."""
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("user prefers terse answers")
    updated = await area.synthesize_profile(
        _ProfileAPI("Prefers terse answers."), scope="jin", only_new=True,
    )
    assert updated == "Prefers terse answers."


async def test_synthesize_profile_only_new_skips_when_nothing_newer():
    """A second only_new pass with no turns post-dating the profile is a no-op."""
    area = MemoryArea("mom1", DictBackend())
    await area.append_history("a preference")
    first = await area.synthesize_profile(
        _ProfileAPI("Profile v1"), scope="jin", only_new=True,
    )
    assert first == "Profile v1"

    api2 = _ProfileAPI("Profile v2")
    second = await area.synthesize_profile(api2, scope="jin", only_new=True)
    assert second is None              # nothing newer than the profile just written
    assert api2.seen_user is None      # the model was never called
    assert await area.get_profile(scope="jin") == "Profile v1"  # left intact


async def test_synthesize_profile_only_new_folds_just_the_delta():
    """only_new folds turns newer than the profile and excludes older ones."""
    from autumn.core.memory.base import MemoryEntry

    area = MemoryArea("mom1", DictBackend())
    prof = await area.set_profile("Likes dark mode.", scope="jin")
    # One turn before the profile, one after — explicit timestamps for determinism.
    await area.append_history(
        MemoryEntry(id="old", content="legacy note about themes",
                    timestamp=prof.timestamp - 100),
    )
    await area.append_history(
        MemoryEntry(id="new", content="now prefers terse answers",
                    timestamp=prof.timestamp + 100),
    )
    api = _ProfileAPI("Likes dark mode. Prefers terse answers.")
    updated = await area.synthesize_profile(api, scope="jin", only_new=True)
    assert updated == "Likes dark mode. Prefers terse answers."
    assert "now prefers terse answers" in api.seen_user      # post-profile turn folded
    assert "legacy note about themes" not in api.seen_user   # pre-profile turn excluded


async def test_synthesize_profile_default_folds_all_history():
    """Default (only_new=False) still folds the full non-derived history."""
    from autumn.core.memory.base import MemoryEntry

    area = MemoryArea("mom1", DictBackend())
    prof = await area.set_profile("base", scope="jin")
    await area.append_history(
        MemoryEntry(id="old", content="older turn", timestamp=prof.timestamp - 100),
    )
    api = _ProfileAPI("merged")
    updated = await area.synthesize_profile(api, scope="jin")  # only_new defaults False
    assert updated == "merged"
    assert "older turn" in api.seen_user  # whole history folded regardless of age

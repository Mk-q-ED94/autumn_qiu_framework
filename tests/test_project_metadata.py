"""Tests for project metadata — type, description, goals, files, environment.

Covers both the data layer (ProjectMeta dataclasses and ProjectZone methods)
and the A1-led WP1 coordination methods (draft_description, draft_goals,
infer_environment), plus the server endpoints that expose them.
"""
import json
import os

import pytest

os.environ.setdefault("AUTUMN_SKIP_INIT", "1")

from autumn.core.memory.backends import DictBackend
from autumn.core.memory.project import (
    ProjectEnvironment,
    ProjectGoals,
    ProjectMeta,
    ProjectMemory,
    ProjectZone,
)
from autumn.core.workspace.wp1 import WP1Tot


# ── doubles ───────────────────────────────────────────────────────────────────

class _StubAPI:
    def __init__(self, reply: str = "{}"):
        self.reply = reply
        self.calls: list = []

    async def complete(self, messages, **kwargs):
        self.calls.append(messages)
        return self.reply


def _wp1(api=None, projects=None) -> WP1Tot:
    if projects is None:
        projects = ProjectMemory(DictBackend())
    return WP1Tot(api, None, None, None, projects=projects)


# ── ProjectGoals ──────────────────────────────────────────────────────────────

def test_goals_roundtrip():
    g = ProjectGoals(master="ship v2", long_term=["a", "b"], short_term=["x"])
    assert ProjectGoals.from_dict(g.to_dict()) == g


def test_goals_defaults():
    g = ProjectGoals()
    assert g.master == ""
    assert g.long_term == []
    assert g.short_term == []


def test_goals_from_dict_missing_keys():
    g = ProjectGoals.from_dict({})
    assert g.master == ""
    assert g.long_term == []


# ── ProjectEnvironment ────────────────────────────────────────────────────────

def test_environment_roundtrip():
    e = ProjectEnvironment(
        terrs=["code"], skills=["testing"], tools=["git"],
        mcp=["github"], agent_channel="dev"
    )
    assert ProjectEnvironment.from_dict(e.to_dict()) == e


def test_environment_defaults():
    e = ProjectEnvironment()
    assert e.terrs == [] and e.agent_channel is None


# ── ProjectMeta ───────────────────────────────────────────────────────────────

def test_meta_roundtrip():
    m = ProjectMeta(
        project_type="code",
        description="A web API",
        goals=ProjectGoals(master="launch", long_term=["scale"], short_term=["auth"]),
        files=["main.py", "tests/test_api.py"],
        environment=ProjectEnvironment(terrs=["code"], agent_channel="dev"),
    )
    assert ProjectMeta.from_dict(m.to_dict()) == m


def test_meta_defaults():
    m = ProjectMeta()
    assert m.project_type is None
    assert m.description == ""
    assert m.goals.master == ""
    assert m.files == []
    assert m.environment.terrs == []


def test_meta_from_dict_handles_none_sublists():
    m = ProjectMeta.from_dict({"goals": None, "environment": None, "files": None})
    assert m.goals.master == ""
    assert m.files == []


# ── ProjectZone metadata methods ──────────────────────────────────────────────

async def test_get_meta_returns_defaults_when_unset():
    zone = ProjectZone("p", DictBackend())
    meta = await zone.get_meta()
    assert isinstance(meta, ProjectMeta)
    assert meta.project_type is None
    assert meta.description == ""


async def test_set_and_get_meta_roundtrip():
    zone = ProjectZone("p", DictBackend())
    meta = ProjectMeta(project_type="research", description="Study AI safety")
    await zone.set_meta(meta)
    loaded = await zone.get_meta()
    assert loaded.project_type == "research"
    assert loaded.description == "Study AI safety"


async def test_update_meta_merges_partial():
    zone = ProjectZone("p", DictBackend())
    await zone.set_meta(ProjectMeta(description="original", project_type="code"))
    updated = await zone.update_meta(description="updated")
    assert updated.description == "updated"
    assert updated.project_type == "code"  # unchanged


async def test_update_meta_merges_goals_shallowly():
    zone = ProjectZone("p", DictBackend())
    g = ProjectGoals(master="v1", long_term=["scale"], short_term=["auth"])
    await zone.set_meta(ProjectMeta(goals=g))
    updated = await zone.update_meta(goals={"master": "v2"})
    assert updated.goals.master == "v2"
    assert updated.goals.long_term == ["scale"]  # unchanged


async def test_update_meta_merges_environment_shallowly():
    zone = ProjectZone("p", DictBackend())
    env = ProjectEnvironment(terrs=["code"], skills=["testing"])
    await zone.set_meta(ProjectMeta(environment=env))
    updated = await zone.update_meta(environment={"agent_channel": "dev"})
    assert updated.environment.agent_channel == "dev"
    assert updated.environment.terrs == ["code"]  # unchanged


async def test_add_file_appends_and_is_idempotent():
    zone = ProjectZone("p", DictBackend())
    await zone.add_file("main.py")
    await zone.add_file("main.py")  # second call is no-op
    await zone.add_file("tests/test_main.py")
    meta = await zone.get_meta()
    assert meta.files == ["main.py", "tests/test_main.py"]


async def test_remove_file_removes_and_noop_on_absent():
    zone = ProjectZone("p", DictBackend())
    await zone.add_file("a.py")
    await zone.add_file("b.py")
    await zone.remove_file("a.py")
    await zone.remove_file("ghost.py")  # should not raise
    meta = await zone.get_meta()
    assert meta.files == ["b.py"]


# ── ProjectMemory metadata helpers ────────────────────────────────────────────

async def test_project_memory_get_metadata_delegates():
    pm = ProjectMemory(DictBackend())
    await pm.zone("x").set_meta(ProjectMeta(description="hello"))
    meta = await pm.get_metadata("x")
    assert meta.description == "hello"


async def test_project_memory_update_metadata_delegates():
    pm = ProjectMemory(DictBackend())
    meta = await pm.update_metadata("x", description="first", project_type="code")
    assert meta.description == "first"
    assert meta.project_type == "code"
    meta2 = await pm.update_metadata("x", description="second")
    assert meta2.description == "second"
    assert meta2.project_type == "code"


# ── WP1 project coordination ──────────────────────────────────────────────────

async def test_draft_description_calls_api_and_returns_stripped():
    api = _StubAPI("  A framework for building AI agents.  ")
    pm = ProjectMemory(DictBackend())
    wp1 = _wp1(api=api, projects=pm)
    result = await wp1.draft_description("it helps build agents quickly", "proj")
    assert result == "A framework for building AI agents."
    assert api.calls
    assert "You are A1" in api.calls[0][0].content


async def test_draft_description_requires_model():
    pm = ProjectMemory(DictBackend())
    with pytest.raises(RuntimeError, match="A1 model slot"):
        await _wp1(api=None, projects=pm).draft_description("text", "proj")


async def test_draft_description_requires_projects():
    api = _StubAPI("desc")
    wp1 = _wp1(api=api, projects=None)
    wp1.projects = None
    with pytest.raises(ValueError, match="Project memory is not configured"):
        await wp1.draft_description("text", "proj")


async def test_draft_goals_parses_json_response():
    api = _StubAPI(
        '{"master": "ship v2", "long_term": ["scale", "i18n"], "short_term": ["auth"]}'
    )
    pm = ProjectMemory(DictBackend())
    wp1 = _wp1(api=api, projects=pm)
    goals = await wp1.draft_goals("we want to scale and add i18n", "proj")
    assert goals.master == "ship v2"
    assert goals.long_term == ["scale", "i18n"]
    assert goals.short_term == ["auth"]


async def test_draft_goals_includes_description_in_prompt():
    api = _StubAPI('{"master": "x", "long_term": [], "short_term": []}')
    pm = ProjectMemory(DictBackend())
    await pm.zone("proj").set_meta(ProjectMeta(description="An AI-powered editor"))
    wp1 = _wp1(api=api, projects=pm)
    await wp1.draft_goals("be fast", "proj")
    # The description should appear in the user message
    user_msg_content = api.calls[0][1].content
    assert "AI-powered editor" in user_msg_content


async def test_draft_goals_falls_back_on_bad_json():
    api = _StubAPI("just some text that is not json")
    pm = ProjectMemory(DictBackend())
    wp1 = _wp1(api=api, projects=pm)
    goals = await wp1.draft_goals("goals description", "proj")
    assert isinstance(goals, ProjectGoals)
    assert "just some text" in goals.master


async def test_draft_goals_requires_model():
    pm = ProjectMemory(DictBackend())
    with pytest.raises(RuntimeError, match="A1 model slot"):
        await _wp1(api=None, projects=pm).draft_goals("text", "proj")


async def test_infer_environment_parses_and_persists():
    api = _StubAPI(
        '{"terrs": ["code", "search"], "skills": ["testing"], '
        '"tools": ["git"], "mcp": ["github"], "agent_channel": "dev"}'
    )
    pm = ProjectMemory(DictBackend())
    await pm.zone("proj").set_meta(ProjectMeta(
        project_type="code",
        description="A web API",
        goals=ProjectGoals(master="ship v1"),
    ))
    wp1 = _wp1(api=api, projects=pm)
    meta = await wp1.infer_environment("proj")
    assert meta.environment.terrs == ["code", "search"]
    assert meta.environment.agent_channel == "dev"
    # persisted
    loaded = await pm.zone("proj").get_meta()
    assert loaded.environment.terrs == ["code", "search"]


async def test_infer_environment_includes_project_context_in_prompt():
    api = _StubAPI('{"terrs": [], "skills": [], "tools": [], "mcp": [], "agent_channel": null}')
    pm = ProjectMemory(DictBackend())
    await pm.zone("proj").set_meta(ProjectMeta(
        project_type="research",
        description="Studying LLM alignment",
        goals=ProjectGoals(master="publish paper"),
    ))
    wp1 = _wp1(api=api, projects=pm)
    await wp1.infer_environment("proj")
    user_msg = api.calls[0][1].content
    assert "research" in user_msg
    assert "Studying LLM alignment" in user_msg
    assert "publish paper" in user_msg


async def test_infer_environment_survives_bad_json():
    api = _StubAPI("I cannot determine the environment.")
    pm = ProjectMemory(DictBackend())
    await pm.zone("proj").set_meta(ProjectMeta(
        environment=ProjectEnvironment(terrs=["original"])
    ))
    wp1 = _wp1(api=api, projects=pm)
    meta = await wp1.infer_environment("proj")
    # Environment unchanged since parsing failed
    assert meta.environment.terrs == ["original"]


async def test_infer_environment_extracts_json_from_markdown():
    api = _StubAPI(
        "Sure!\n```json\n"
        '{"terrs": ["code"], "skills": [], "tools": [], "mcp": [], "agent_channel": null}'
        "\n```"
    )
    pm = ProjectMemory(DictBackend())
    wp1 = _wp1(api=api, projects=pm)
    meta = await wp1.infer_environment("proj")
    assert meta.environment.terrs == ["code"]


async def test_infer_environment_requires_model():
    pm = ProjectMemory(DictBackend())
    with pytest.raises(RuntimeError, match="A1 model slot"):
        await _wp1(api=None, projects=pm).infer_environment("proj")


async def test_infer_environment_requires_projects():
    wp1 = _wp1(api=_StubAPI())
    wp1.projects = None
    with pytest.raises(ValueError, match="Project memory is not configured"):
        await wp1.infer_environment("proj")


# ── server endpoints ──────────────────────────────────────────────────────────

from contextlib import contextmanager  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from autumn.server.app import create_app  # noqa: E402


@contextmanager
def _make_client(api=None):
    app = create_app()
    with TestClient(app) as client:
        from autumn.core.memory.backends import DictBackend as DB
        pm = ProjectMemory(DB())
        wp1 = _wp1(api=api, projects=pm)

        class _FakeAutumn:
            def __init__(self):
                self.projects = pm
                self.wp1 = wp1

            def describe_terrs(self):
                return []

            async def end_session(self): pass
            async def close(self): pass

        app.state.autumn = _FakeAutumn()
        yield client, pm


def test_get_metadata_returns_defaults():
    with _make_client() as (client, _):
        r = client.get("/projects/myproj/metadata")
        assert r.status_code == 200
        d = r.json()
        assert d["project_type"] is None
        assert d["description"] == ""
        assert d["files"] == []


def test_patch_metadata_updates_fields():
    with _make_client() as (client, _):
        r = client.patch(
            "/projects/myproj/metadata",
            json={"project_type": "code", "description": "A web API"},
        )
        assert r.status_code == 200
        d = r.json()
        assert d["project_type"] == "code"
        assert d["description"] == "A web API"


def test_patch_metadata_partial_update():
    with _make_client() as (client, _):
        # establish initial state via the API
        client.patch(
            "/projects/p2/metadata",
            json={"project_type": "research", "description": "original"},
        )
        r = client.patch("/projects/p2/metadata", json={"description": "updated"})
        assert r.status_code == 200
        assert r.json()["project_type"] == "research"
        assert r.json()["description"] == "updated"


def test_add_and_remove_file():
    with _make_client() as (client, _):
        r = client.post("/projects/p/files", json={"path": "src/main.py"})
        assert r.status_code == 200
        assert "src/main.py" in r.json()["files"]

        r = client.post("/projects/p/files", json={"path": "tests/test_main.py"})
        assert r.status_code == 200
        assert len(r.json()["files"]) == 2

        r = client.delete("/projects/p/files/src/main.py")
        assert r.status_code == 200
        assert r.json()["files"] == ["tests/test_main.py"]


def test_add_file_idempotent():
    with _make_client() as (client, _):
        client.post("/projects/p/files", json={"path": "main.py"})
        client.post("/projects/p/files", json={"path": "main.py"})
        r = client.get("/projects/p/metadata")
        assert r.json()["files"].count("main.py") == 1


def test_draft_description_returns_text():
    api = _StubAPI("A clean API framework.")
    with _make_client(api=api) as (client, _):
        r = client.post(
            "/projects/p/describe",
            json={"input": "I want to build a REST API server"},
        )
        assert r.status_code == 200
        assert r.json()["description"] == "A clean API framework."


def test_draft_description_requires_a1():
    with _make_client(api=None) as (client, _):
        r = client.post("/projects/p/describe", json={"input": "idea"})
        assert r.status_code == 400
        assert "A1" in r.json()["detail"]


def test_draft_goals_returns_structured():
    api = _StubAPI(
        '{"master": "launch v1", "long_term": ["scale"], "short_term": ["auth"]}'
    )
    with _make_client(api=api) as (client, _):
        r = client.post("/projects/p/goals", json={"input": "launch and scale"})
        assert r.status_code == 200
        d = r.json()
        assert d["master"] == "launch v1"
        assert "scale" in d["long_term"]


def test_draft_goals_requires_a1():
    with _make_client(api=None) as (client, _):
        r = client.post("/projects/p/goals", json={"input": "text"})
        assert r.status_code == 400
        assert "A1" in r.json()["detail"]


def test_infer_environment_endpoint():
    api = _StubAPI(
        '{"terrs": ["code"], "skills": ["review"], '
        '"tools": ["git"], "mcp": [], "agent_channel": "dev"}'
    )
    with _make_client(api=api) as (client, _):
        r = client.post("/projects/p/infer-environment")
        assert r.status_code == 200
        d = r.json()
        assert d["environment"]["terrs"] == ["code"]
        assert d["environment"]["agent_channel"] == "dev"


def test_infer_environment_requires_a1():
    with _make_client(api=None) as (client, _):
        r = client.post("/projects/p/infer-environment")
        assert r.status_code == 400
        assert "A1" in r.json()["detail"]

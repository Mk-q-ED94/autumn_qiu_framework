"""Shared mechanics for A1-led project metadata discussions."""

import json

from .memory.project import ProjectEnvironment, ProjectGoals, ProjectMemory, ProjectMeta
from .types import Message, Role


def _extract_json(text: str) -> str:
    """Strip markdown fences so ``json.loads`` can parse a model response."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts[1::2]:
            code = part.strip()
            if code.lower().startswith("json"):
                code = code[4:].strip()
            if code.startswith(("{", "[")):
                return code
    return text


async def draft_description(api, user_input: str) -> str:
    messages = [
        Message(
            role=Role.SYSTEM,
            content=(
                "You are A1, the project coordinator in the Autumn framework. "
                "The user will describe their project idea. Synthesise a clear, "
                "concise project description (2-4 sentences). Return only the "
                "description text, with no preamble or commentary."
            ),
        ),
        Message(role=Role.USER, content=user_input),
    ]
    return (await api.complete(messages)).strip()


async def draft_goals(
    api, projects: ProjectMemory, user_input: str, project_id: str,
) -> ProjectGoals:
    meta = await projects.zone(project_id).get_meta()
    description = f"Project description: {meta.description}\n\n" if meta.description else ""
    messages = [
        Message(
            role=Role.SYSTEM,
            content=(
                "You are A1, the project coordinator in the Autumn framework. "
                "Structure the user's goals into one master goal, a list of long-term "
                "goals, and a list of short-term goals. Respond ONLY with valid JSON: "
                '{"master": "...", "long_term": ["..."], "short_term": ["..."]}'
            ),
        ),
        Message(role=Role.USER, content=f"{description}Goals description: {user_input}"),
    ]
    response = await api.complete(messages)
    try:
        return ProjectGoals.from_dict(json.loads(_extract_json(response)))
    except (json.JSONDecodeError, ValueError, AttributeError):
        return ProjectGoals(master=response.strip()[:300])


async def infer_environment(
    api, projects: ProjectMemory, project_id: str,
) -> ProjectMeta:
    zone = projects.zone(project_id)
    meta = await zone.get_meta()
    messages = [
        Message(
            role=Role.SYSTEM,
            content=(
                "You are A1, the project coordinator in the Autumn framework. "
                "Based on the project information, suggest an appropriate runtime "
                "environment configuration. Respond ONLY with valid JSON in exactly "
                "this shape:\n"
                '{"terrs": [...], "skills": [...], "tools": [...], '
                '"mcp": [...], "agent_channel": "name_or_null"}\n'
                "Use short lowercase identifiers. Keep each list concise (2-5 items). "
                'Set "agent_channel" to null if none is needed.'
            ),
        ),
        Message(
            role=Role.USER,
            content=(
                f"Project type: {meta.project_type or 'unspecified'}\n"
                f"Description: {meta.description or '(none)'}\n"
                f"Master goal: {meta.goals.master or '(none)'}"
            ),
        ),
    ]
    response = await api.complete(messages)
    try:
        meta.environment = ProjectEnvironment.from_dict(json.loads(_extract_json(response)))
    except (json.JSONDecodeError, ValueError, AttributeError):
        pass
    await zone.set_meta(meta)
    return meta

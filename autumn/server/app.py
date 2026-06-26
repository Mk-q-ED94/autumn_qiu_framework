"""HTTP/SSE bridge that exposes Autumn to the SwiftUI desktop client."""
import asyncio
import hmac
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..core.config import AutumnConfig, BehaviorConfig, ModelConfig
from ..core.framework import Autumn
from ..core.memory.project import project_context, reset_current_project, set_current_project
from ..core.security import (
    FetchError,
    MAX_REQUEST_BYTES,
    assert_url_allowed,
    redact_secrets,
)
from ..core.types import InputType, MissionRoute, Protocol, TaskType, WorkflowRun
from . import integrations as integrations_mod

logger = logging.getLogger("autumn.server")


@dataclass
class _Metrics:
    """Lightweight in-process counters — one instance lives on app.state."""
    runs: int = 0
    errors: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    started_at: float = field(default_factory=time.time)


def _record_run(app_state, run: WorkflowRun) -> None:
    """Accumulate per-turn token counts and emit a structured log line."""
    m: _Metrics = app_state.metrics
    m.runs += 1
    prompt = sum(s.prompt_tokens or 0 for s in run.stages)
    completion = sum(s.completion_tokens or 0 for s in run.stages)
    m.prompt_tokens += prompt
    m.completion_tokens += completion
    logger.info(
        "turn complete  route=%s input_type=%s prompt=%d completion=%d cost_usd=%s",
        run.route, run.input_type, prompt, completion, run.total_cost_usd,
    )


# How long an SSE stream can sit idle before we emit an `: ping` comment.
# Most corporate proxies kill idle SSE connections at 30–60s; 15s is safe.
_SSE_HEARTBEAT_SECONDS = 15.0

# Default page size for the memory history endpoint; capped to keep responses
# bounded regardless of how many turns a session has accumulated.
_HISTORY_PAGE_DEFAULT = 200
_HISTORY_PAGE_MAX = 2000

# Curated small chat models well-suited to the A4 memory role (recall synthesis):
# fast, low-RAM, strong multilingual (esp. Chinese). Sizes are approximate
# default-quant pull sizes.
_OLLAMA_RECOMMENDED = [
    {"name": "qwen2.5:0.5b", "label": "Qwen2.5 0.5B", "size": "~0.4 GB",
     "note": "极速 · 中英双语 · 记忆合成够用", "recommended": False},
    {"name": "qwen2.5:1.5b", "label": "Qwen2.5 1.5B", "size": "~1.0 GB",
     "note": "速度/质量平衡 · A4 推荐", "recommended": True},
    {"name": "qwen2.5:3b", "label": "Qwen2.5 3B", "size": "~2.0 GB",
     "note": "更强理解 · 仍然轻量", "recommended": False},
    {"name": "llama3.2:1b", "label": "Llama 3.2 1B", "size": "~1.3 GB",
     "note": "Meta 轻量模型", "recommended": False},
    {"name": "llama3.2:3b", "label": "Llama 3.2 3B", "size": "~2.0 GB",
     "note": "Meta 通用小模型", "recommended": False},
    {"name": "gemma2:2b", "label": "Gemma 2 2B", "size": "~1.6 GB",
     "note": "Google 高效小模型", "recommended": False},
]

MemoryArea = Literal["mom1", "mom2", "mom3", "shared"]


RequestRoute = MissionRoute | Literal["auto"] | None


class ProcessRequest(BaseModel):
    input: str
    route: RequestRoute = None
    input_type: InputType | None = None
    task_type: TaskType | None = None
    project_instructions: str | None = None
    project_id: str | None = None


class ProcessResponse(BaseModel):
    output: str


def _apply_project_context(user_input: str, project_instructions: str | None) -> str:
    """Wrap ``user_input`` with a project-instructions preamble when set.

    The instructions are inserted as a clearly-tagged block so the
    workflow sees them as part of the user turn but A1 can distinguish
    them in its trace.  Returns the original input unchanged when no
    instructions are present.
    """
    instructions = (project_instructions or "").strip()
    if not instructions:
        return user_input
    return (
        "[项目指令 / Project Instructions]\n"
        f"{instructions}\n\n"
        "[用户输入 / User Input]\n"
        f"{user_input}"
    )


class TraceStageResponse(BaseModel):
    id: str
    title: str
    detail: str
    workspace: str
    items: list[str] | None = None
    status: str
    kind: str = "stage"
    duration_ms: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    source_terr: str | None = None
    cost_usd: float | None = None


class TraceResponse(BaseModel):
    output: str
    input_type: InputType
    route: MissionRoute | None = None
    task_type: TaskType | None = None
    stages: list[TraceStageResponse]
    total_prompt_tokens: int | None = None
    total_completion_tokens: int | None = None
    total_cost_usd: float | None = None


class IntentRequest(BaseModel):
    input: str
    route: RequestRoute = None
    input_type: InputType | None = None
    task_type: TaskType | None = None
    project_instructions: str | None = None
    project_id: str | None = None


class IntentResponse(BaseModel):
    input_type: InputType
    task_type: TaskType | None = None
    route: MissionRoute | None = None
    confidence: float
    reasoning: str | None = None


class TerrParameterResponse(BaseModel):
    name: str
    type: str
    description: str
    required: bool = True
    extra: dict = Field(default_factory=dict)


class TerrCallableResponse(BaseModel):
    name: str
    description: str
    parameters: list[TerrParameterResponse] = []


class TerrResponse(BaseModel):
    name: str
    description: str
    enabled: bool = True
    tools: list[TerrCallableResponse] = []
    skills: list[TerrCallableResponse] = []
    mcps: list[dict] = []


class TerrToggleRequest(BaseModel):
    enabled: bool


class McpField(BaseModel):
    """One input in an MCP's connect form."""
    key: str
    label: str
    secret: bool = False
    optional: bool = False
    placeholder: str = ""


class McpSetup(BaseModel):
    """A short, human setup tutorial for an MCP."""
    summary: str = ""
    steps: list[str] = []
    doc_url: str | None = None


class KnownMCPResponse(BaseModel):
    """A browsable entry from the built-in MCP catalog (autumn.builtin.KNOWN_MCPS).

    Carries everything a client needs to introduce the MCP and configure it
    inline: a category, the connect form fields, and a setup tutorial.
    """
    id: str
    name: str
    description: str
    factory: str
    category: str = "keyless"
    needs_credentials: bool = False
    required_args: list[str] = []
    fields: list[McpField] = []
    setup: McpSetup | None = None


class ProviderConfigRequest(BaseModel):
    api_key: str
    base_url: str
    model: str | None = None
    protocol: Protocol
    # Optional USD price per 1M tokens; enables per-turn cost in the trace.
    input_price_per_1m: float = 0.0
    output_price_per_1m: float = 0.0


class CooperativeBehaviorRequest(BaseModel):
    """Optional cooperative-workflow toggles applied on /config/apply.

    These are the interactive A1/A4 behaviours that previously had NO runtime
    path — they could only be set via env var at boot, so no client could turn
    A1 supervision or task planning on. Each field is optional; an omitted field
    keeps the framework default. (The 4D memory flags have their own live
    endpoint at /memory/4d/config and are not duplicated here.)
    """

    cooperative_workflow: bool | None = None
    a1_task_planning: bool | None = None
    a1_supervision: bool | None = None
    archive_executions: bool | None = None
    a4_delegate_to_a1: bool | None = None
    a4_knowledge_terr: bool | None = None


class ApplyConfigRequest(BaseModel):
    a1: ProviderConfigRequest
    a2: ProviderConfigRequest
    a3: ProviderConfigRequest
    a4: ProviderConfigRequest | None = None
    behavior: CooperativeBehaviorRequest | None = None


class ApplyConfigResponse(BaseModel):
    status: str
    configured: bool


class ModelsRequest(BaseModel):
    api_key: str
    base_url: str
    protocol: Protocol


class ModelsResponse(BaseModel):
    models: list[str]


class ConsolidateRequest(BaseModel):
    """Tuning for a memory consolidation pass (all optional)."""

    keep_recent: int = 10
    min_candidates: int = 3


class ExtractFactsRequest(BaseModel):
    """Tuning for an atomic-fact extraction pass (all optional)."""

    keep_recent: int = 0
    max_facts: int = 20


class EvolveRequest(BaseModel):
    """Tuning for a self-evolution pass (all optional)."""

    min_count: int = 2
    min_cluster: int = 2
    max_skills: int = 10


class ProfileRequest(BaseModel):
    """Scope selector for profile synthesis (optional)."""

    scope: str = "default"


class ProjectMetaUpdateRequest(BaseModel):
    """Partial update for project metadata. Omitted fields are unchanged."""

    project_type: str | None = None
    description: str | None = None
    goals: dict | None = None
    files: list[str] | None = None
    environment: dict | None = None


class ProjectDescribeRequest(BaseModel):
    """Free-text input for AI-guided description generation."""

    input: str


class ProjectGoalsRequest(BaseModel):
    """Free-text input for AI-guided goals structuring."""

    input: str


class AddFileRequest(BaseModel):
    """A file path to append to the project's file list."""

    path: str


class AnnotateRequest(BaseModel):
    """Set/merge 4D dimensions on one history entry. Omitted fields are left as-is."""

    entry_id: str
    mode: str | None = None          # constrain | remind | summarize | context
    intent: str | None = None
    goal_ref: str | None = None
    scope: list[str] | None = None
    cues: list[str] | None = None
    half_life: float | None = None


class AnnotateResponse(BaseModel):
    status: str
    entry_id: str
    found: bool


class AutoAnnotateRequest(BaseModel):
    """Tuning for an A4-inferred annotation pass."""

    n: int = 10
    only_unannotated: bool = True


class AutoAnnotateResponse(BaseModel):
    status: str
    annotated: int
    scanned: int


class FourDStatusResponse(BaseModel):
    """Whether the 4D activation engine is actually wired into live turns."""

    fourd_memory_enabled: bool
    fourd_push_on_turn: bool
    fourd_pull_on_turn: bool = True
    fourd_auto_annotate: bool = True
    fourd_auto_consolidate: bool = True
    fourd_auto_evolve: bool = False
    mom1_access_enabled: bool


class FourDConfigRequest(BaseModel):
    """Runtime override for the 4D switches. Omitted fields are left unchanged."""

    fourd_memory_enabled: bool | None = None
    fourd_push_on_turn: bool | None = None
    fourd_pull_on_turn: bool | None = None
    fourd_auto_annotate: bool | None = None
    fourd_auto_consolidate: bool | None = None
    fourd_auto_evolve: bool | None = None
    mom1_access_enabled: bool | None = None


class CodebaseMemoryStatusResponse(BaseModel):
    """State of the codebase-memory token-saving layer (codebase-memory-mcp)."""

    enabled: bool          # behaviour flag — intent; the layer auto-starts when on
    connected: bool        # whether the code-graph MCP server is live right now
    indexed: bool = False  # whether the repo has been indexed into the graph yet
    repo: str = ""         # repo scoped for indexing ("" = server working directory)
    tool_count: int = 0
    error: str | None = None


class CodebaseMemoryConfigRequest(BaseModel):
    """Toggle the codebase-memory layer; ``repo`` overrides the scoped path."""

    enabled: bool
    repo: str | None = None


class PushPreviewRequest(BaseModel):
    """Dry-run the turn-start push engine against a hypothetical context."""

    area: MemoryArea = "mom1"
    query: str = ""
    cues: list[str] | None = None
    k: int = 5


class PushPreviewEntry(BaseModel):
    id: str
    text: str
    mode: str
    intent: str = ""
    cues: list[str] = []
    score: float


class PushPreviewResponse(BaseModel):
    fired: list[PushPreviewEntry]
    fragment: str
    enabled: bool       # whether push is actually active on live turns


class AccessLogEntry(BaseModel):
    id: str
    timestamp: float
    action: str
    requester: str
    query: str
    reason: str
    decision_reason: str = ""
    redact: bool = False
    entry_ids: list[str] = []
    mediated_by: str | None = None


class AccessLogResponse(BaseModel):
    entries: list[AccessLogEntry]
    total: int


class IntegrationField(BaseModel):
    key: str
    label: str
    secret: bool = False
    optional: bool = False


class IntegrationCatalogEntry(BaseModel):
    id: str
    name: str
    description: str
    fields: list[IntegrationField]


class IntegrationStatusEntry(BaseModel):
    id: str
    name: str
    connected: bool
    tool_count: int = 0
    # Read-only by default. write_enabled reflects whether mutating tools
    # (create/edit/delete/post) are exposed to the agent; blocked_tool_count is
    # how many mutating tools are being withheld while in read-only mode.
    write_enabled: bool = False
    blocked_tool_count: int = 0
    error: str | None = None


class IntegrationConnectRequest(BaseModel):
    id: str
    args: dict[str, str] = Field(default_factory=dict)
    # Opt-in grant: when false (default) the agent only gets the platform's read
    # surface; mutating tools are withheld until the user deliberately enables
    # writes and reconnects.
    write_enabled: bool = False


class OllamaTarget(BaseModel):
    base_url: str = "http://127.0.0.1:11434"


class OllamaDeleteRequest(OllamaTarget):
    name: str


def _register_builtin_terrs(autumn: Autumn) -> None:
    """Register built-in capability domains based on ``AUTUMN_BUILTIN_TERRS``.

    Unset/empty (default): WP2 stays tool-less, preserving the minimal pipeline
    and existing behaviour. Opt in to surface the shipped domains in ``/terrs``
    and give WP2's agent real capabilities:

    - ``safe`` / ``1`` / ``true``: the always-safe domains — time, math, text,
      data, encoding, collection (no network, no filesystem).
    - ``all``: the above plus ``web`` (outbound HTTP) and ``knowledge``
      (DuckDuckGo search + document fetch, no API key required).

    Filesystem access (``fs``) is never auto-registered because it requires an
    explicit sandbox root. Set ``AUTUMN_FS_ROOT`` to a directory path to add the
    ``fs`` domain in any non-empty mode.
    """
    mode = os.environ.get("AUTUMN_BUILTIN_TERRS", "").strip().lower()
    if mode in ("", "0", "false", "off", "none"):
        return
    from ..builtin import fs_terr, knowledge_terr, register_safe_builtins, web_terr
    register_safe_builtins(autumn)
    if mode == "all":
        autumn.register_terr(web_terr())
        autumn.register_terr(knowledge_terr())
    fs_root = os.environ.get("AUTUMN_FS_ROOT", "").strip()
    if fs_root:
        try:
            autumn.register_terr(fs_terr(fs_root))
        except (ValueError, OSError) as exc:
            logger.warning("AUTUMN_FS_ROOT %r is invalid: %s", fs_root, exc)


def _register_core_skills(autumn: Autumn) -> None:
    """Expose the core memory tools on the default deployment.

    Without this the agent has no way to read/write durable memory or reach Mom1
    on a normal turn: recall synthesis and the governed Mom1 access broker were
    fully built but unreachable because nothing registered their skills. Binding
    recall/remember to the shared zone and the ``request_mom1_access`` channel to
    the task executor (Mom2) makes both live on the default turn.

    Registering skills means WP2 takes its tool-calling ReAct path, which needs an
    A2 endpoint that accepts a ``tools`` request field. That is true for OpenAI /
    Anthropic / modern Ollama, but a base-completion or tool-less OpenAI-compatible
    endpoint would reject the call. Deployments on such an endpoint can opt out
    with ``AUTUMN_CORE_MEMORY_SKILLS=0`` — the passive turn-start Mom1 recall
    injection still gives conversation continuity without any tool support.
    Best-effort: a build that somehow lacks WP4/the broker must not fail to boot.
    """
    mode = os.environ.get("AUTUMN_CORE_MEMORY_SKILLS", "").strip().lower()
    if mode in ("0", "false", "off", "none", "no"):
        return
    try:
        autumn.add_memory_skills(area="shared")
        autumn.add_mom1_access_skill(area="mom2")
    except Exception as exc:  # pragma: no cover - defensive; both are always wired
        logger.warning("core memory skills not registered: %s", exc)


def _behavior_from_request(req_behavior) -> BehaviorConfig:
    """Build a BehaviorConfig from env defaults with cooperative overrides applied.

    The boot path (_try_build_from_env) reads behaviour from env; /config/apply
    used to ignore it entirely, building bare BehaviorConfig() defaults — so the
    interactive cooperative flags (a1_supervision/a1_task_planning/...) had no
    runtime path at all. Here env is the baseline and any flag the client sends
    overrides it, so a client can finally turn A1 supervision on without a reboot.
    """
    behavior = BehaviorConfig.from_env()
    if req_behavior is None:
        return behavior
    for field_name in (
        "cooperative_workflow", "a1_task_planning", "a1_supervision",
        "archive_executions", "a4_delegate_to_a1", "a4_knowledge_terr",
    ):
        val = getattr(req_behavior, field_name, None)
        if val is not None:
            setattr(behavior, field_name, val)
    return behavior


def _try_build_from_env() -> Autumn | None:
    if os.environ.get("AUTUMN_SKIP_INIT") == "1":
        return None
    env_file = os.environ.get("AUTUMN_ENV_FILE", ".env")
    try:
        config = AutumnConfig.from_env(env_file=env_file)
    except (KeyError, ValueError) as exc:
        logger.warning("startup config missing (%s); endpoints will return 503.", exc)
        return None
    autumn = Autumn(config)
    _register_builtin_terrs(autumn)
    _register_core_skills(autumn)
    logger.info("autumn server initialized from environment config")
    return autumn


def _model_endpoint(base_url: str) -> str:
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        return f"{root}/models"
    return f"{root}/v1/models"


def _ollama_base(base_url: str) -> str:
    """Normalise an Ollama base URL for the native /api/* endpoints.

    Drops a trailing slash and a trailing ``/v1`` (the OpenAI-compat suffix the
    A4 chat client appends), so the same URL the user configures for A4 chat can
    be reused here for model management.
    """
    root = (base_url or "").strip().rstrip("/")
    if not root:
        root = "http://127.0.0.1:11434"
    if "://" not in root:
        root = f"http://{root}"

    parsed = urlsplit(root)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3].rstrip("/")
    elif path.endswith("/api"):
        path = path[:-4].rstrip("/")

    host = parsed.hostname or "127.0.0.1"
    if host in {"localhost", "::1"}:
        host = "127.0.0.1"
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{host}{port}"
    return urlunsplit((parsed.scheme or "http", netloc, path, "", ""))


def _ollama_unavailable_detail(base: str, exc: Exception) -> str:
    return (
        f"Ollama 未响应（{base}）。请确认 Ollama 已启动，且 Autumn 服务器能访问该地址；"
        "如果服务器运行在云端或容器里，localhost 指的是服务器环境而不是你的 Mac。"
        f"原始错误: {exc}"
    )


def _headers_for(protocol: Protocol, api_key: str) -> dict[str, str]:
    if protocol == Protocol.OPENAI:
        return {"Authorization": f"Bearer {api_key}"}
    return {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }


def _parse_models(payload: dict) -> list[str]:
    raw_items = payload.get("data") or payload.get("models") or []
    names: list[str] = []
    for item in raw_items:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            value = item.get("id") or item.get("name") or item.get("model")
            if isinstance(value, str):
                names.append(value)
    return sorted(dict.fromkeys(names))


def _require_model_config(slot: str, req: ProviderConfigRequest) -> ModelConfig:
    if not req.api_key.strip():
        raise HTTPException(status_code=400, detail=f"{slot} API key is required.")
    if not req.base_url.strip():
        raise HTTPException(status_code=400, detail=f"{slot} base URL is required.")
    if not (req.model or "").strip():
        raise HTTPException(status_code=400, detail=f"{slot} model is required.")
    return ModelConfig(
        api_key=req.api_key.strip(),
        base_url=req.base_url.strip(),
        model=(req.model or "").strip(),
        protocol=req.protocol,
        input_price_per_1m=max(0.0, req.input_price_per_1m),
        output_price_per_1m=max(0.0, req.output_price_per_1m),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.autumn = _try_build_from_env()
    app.state.metrics = _Metrics()
    # apply_lock serialises swap-out of state.autumn so two concurrent
    # /config/apply calls can't leak an Autumn instance whose close() never runs.
    app.state.apply_lock = asyncio.Lock()
    app.state.last_error = None
    # Platform integrations: desired credentials, live runtime handles, and the
    # last connect error per id. integration_lock serialises connect/disconnect.
    app.state.integrations = {}            # id -> args dict (the saved credential)
    app.state.integration_write = {}       # id -> bool (writes granted to the agent?)
    app.state.integration_runtime = {}     # id -> integrations_mod.IntegrationRuntime
    app.state.integration_errors = {}      # id -> str
    app.state.integration_lock = asyncio.Lock()
    # Codebase-memory token-saving layer: last start error (for the status endpoint)
    # and auto-start when enabled in config.
    app.state.codebase_memory_error = None
    if app.state.autumn is not None:
        await _autostart_codebase_memory(app, app.state.autumn)
    try:
        yield
    finally:
        if app.state.autumn is not None:
            await app.state.autumn.close()


async def _reapply_integrations(app: FastAPI, autumn: Autumn) -> None:
    """Reconnect every saved integration onto a freshly built Autumn instance.

    Called after /config/apply swaps the framework out: the old instance's
    close() disconnects the previous MCP clients, so we rebuild the runtime map
    from the persisted credentials. Best-effort — a platform that fails to start
    records its error instead of breaking the whole config apply.
    """
    runtime: dict = {}
    errors: dict = {}
    write_map: dict = app.state.integration_write
    for integration_id, args in list(app.state.integrations.items()):
        try:
            runtime[integration_id] = await integrations_mod.connect(
                autumn, integration_id, args,
                write_enabled=write_map.get(integration_id, False),
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the client as status
            errors[integration_id] = str(exc)
    app.state.integration_runtime = runtime
    app.state.integration_errors = errors


def _codebase_memory_status(app: FastAPI, autumn: Autumn) -> CodebaseMemoryStatusResponse:
    """Snapshot the framework-owned codebase-memory layer for the client."""
    b = getattr(getattr(autumn, "config", None), "behavior", None)
    cb = getattr(autumn, "codebase", None)
    repo = (
        cb.repo if cb is not None
        else (getattr(b, "codebase_memory_repo", "") or "")
    )
    return CodebaseMemoryStatusResponse(
        enabled=bool(getattr(b, "codebase_memory_enabled", False)),
        connected=cb is not None,
        indexed=bool(getattr(cb, "indexed", False)) if cb is not None else False,
        repo=repo,
        tool_count=len(getattr(autumn, "_codebase_terr_names", []) or []),
        error=getattr(app.state, "codebase_memory_error", None),
    )


async def _autostart_codebase_memory(app: FastAPI, autumn: Autumn) -> None:
    """On startup, bring the codebase-memory layer online when enabled in config.

    Best-effort: a missing ``uvx``/``npx`` records an error on app.state for the
    status endpoint instead of breaking startup."""
    b = getattr(getattr(autumn, "config", None), "behavior", None)
    starter = getattr(autumn, "start_codebase_memory", None)
    if starter is None or not getattr(b, "codebase_memory_enabled", False):
        return
    async with app.state.integration_lock:
        try:
            await starter()
            app.state.codebase_memory_error = None
        except Exception as exc:  # noqa: BLE001 - connect spawns a subprocess
            app.state.codebase_memory_error = str(exc)


def _status_entry(app: FastAPI, rid: str, name: str) -> IntegrationStatusEntry:
    runtime: dict = app.state.integration_runtime
    errors: dict = app.state.integration_errors
    handle = runtime.get(rid)
    return IntegrationStatusEntry(
        id=rid,
        name=name,
        connected=handle is not None,
        tool_count=handle.tool_count if handle is not None else 0,
        write_enabled=handle.write_enabled if handle is not None else False,
        blocked_tool_count=handle.blocked_count if handle is not None else 0,
        error=errors.get(rid),
    )


def _integration_status_list(app: FastAPI) -> list[IntegrationStatusEntry]:
    """Status for the platform subset — the Settings → 集成 surface."""
    return [_status_entry(app, e["id"], e["name"]) for e in integrations_mod.INTEGRATIONS]


def _mcp_status_list(app: FastAPI) -> list[IntegrationStatusEntry]:
    """Status for every catalog MCP — the Terr-page surface. Shares the same
    runtime as integrations, so a platform connected from Settings reads as
    connected here too, and vice versa."""
    from ..builtin import KNOWN_MCPS
    return [_status_entry(app, e["id"], e["name"]) for e in KNOWN_MCPS]


async def _connect_mcp(
    request: Request,
    req: "IntegrationConnectRequest",
    *,
    validator,
    label: str,
) -> IntegrationStatusEntry:
    """Shared connect path for both /integrations/connect and /mcps/connect.

    Reconnecting an already-connected MCP tears the old session down first, so
    rotating a token / changing a path just works. ``validator`` gates which ids
    each surface accepts (platforms only vs the whole catalog)."""
    autumn = _autumn_or_503(request)
    if not validator(req.id):
        raise HTTPException(status_code=404, detail=f"未知{label}: {req.id}")
    async with request.app.state.integration_lock:
        existing = request.app.state.integration_runtime.pop(req.id, None)
        if existing is not None:
            await integrations_mod.disconnect(autumn, existing)
        try:
            runtime = await integrations_mod.connect(
                autumn, req.id, req.args, write_enabled=req.write_enabled,
            )
        except ValueError as exc:
            request.app.state.integration_errors[req.id] = str(exc)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 - connect spawns a subprocess
            request.app.state.integration_errors[req.id] = str(exc)
            raise HTTPException(
                status_code=502,
                detail=f"{integrations_mod.display_name(req.id)} 连接失败: {exc}",
            ) from exc
        request.app.state.integration_runtime[req.id] = runtime
        request.app.state.integrations[req.id] = dict(req.args)
        request.app.state.integration_write[req.id] = req.write_enabled
        request.app.state.integration_errors.pop(req.id, None)
    return IntegrationStatusEntry(
        id=req.id,
        name=integrations_mod.display_name(req.id),
        connected=True,
        tool_count=runtime.tool_count,
        write_enabled=runtime.write_enabled,
        blocked_tool_count=runtime.blocked_count,
        error=None,
    )


async def _disconnect_mcp(
    request: Request,
    mcp_id: str,
    *,
    validator,
    label: str,
) -> IntegrationStatusEntry:
    """Shared disconnect path for both /integrations/{id} and /mcps/{id}."""
    autumn = _autumn_or_503(request)
    if not validator(mcp_id):
        raise HTTPException(status_code=404, detail=f"未知{label}: {mcp_id}")
    async with request.app.state.integration_lock:
        existing = request.app.state.integration_runtime.pop(mcp_id, None)
        if existing is not None:
            await integrations_mod.disconnect(autumn, existing)
        request.app.state.integrations.pop(mcp_id, None)
        request.app.state.integration_write.pop(mcp_id, None)
        request.app.state.integration_errors.pop(mcp_id, None)
    return IntegrationStatusEntry(
        id=mcp_id,
        name=integrations_mod.display_name(mcp_id),
        connected=False,
        tool_count=0,
        error=None,
    )


def _autumn_or_503(request: Request) -> Autumn:
    autumn: Autumn | None = request.app.state.autumn
    if autumn is None:
        raise HTTPException(
            status_code=503,
            detail="Autumn not configured. Set A1/A2/A3 env vars and restart the server.",
        )
    return autumn


async def _activate_project(autumn: Autumn, project_id: str | None) -> None:
    """Register a project id so it shows up in /projects. No-op when unset."""
    if not project_id:
        return
    projects = getattr(autumn, "projects", None)
    if projects is not None:
        await projects.register(project_id)


def _projects_or_501(autumn: Autumn):
    """Return the ProjectMemory manager, or 501 if this build predates it."""
    projects = getattr(autumn, "projects", None)
    if projects is None:
        raise HTTPException(
            status_code=501, detail="Per-project memory is not available on this server.",
        )
    return projects


def _memory_curator(autumn: Autumn):
    """Return WP4, the memory-management workspace, or 501 on older builds."""
    wp4 = getattr(autumn, "wp4", None)
    if wp4 is None:
        raise HTTPException(
            status_code=501,
            detail="Memory management workspace (WP4) is not available on this server.",
        )
    return wp4


def _curator_with_model_or_400(autumn: Autumn):
    """Return WP4 only when its A4 model slot is configured, else 400."""
    wp4 = _memory_curator(autumn)
    if not wp4.has_model:
        raise HTTPException(
            status_code=400,
            detail="Memory consolidation needs the A4 model slot; none is configured.",
        )
    return wp4


def _project_coordinator_or_400(autumn: Autumn):
    """Return WP1/A1, the owner of project metadata discussions."""
    wp1 = getattr(autumn, "wp1", None)
    if wp1 is None:
        raise HTTPException(
            status_code=501,
            detail="Project coordination workspace (WP1) is not available on this server.",
        )
    if getattr(wp1, "api", None) is None:
        raise HTTPException(
            status_code=400,
            detail="Project discussion needs the A1 model slot; none is configured.",
        )
    return wp1


def _known_secrets(request: Request) -> list[str]:
    """Collect the literal secrets (API keys) that must never appear in an error
    surfaced to a client: the server's own auth key plus every model slot's key.
    """
    secrets: list[str] = []
    env_key = os.environ.get("AUTUMN_API_KEY", "").strip()
    if env_key:
        secrets.append(env_key)
    autumn = getattr(request.app.state, "autumn", None)
    cfg = getattr(autumn, "config", None)
    if cfg is not None:
        for slot in ("a1", "a2", "a3", "a4"):
            mc = getattr(cfg, slot, None)
            key = getattr(mc, "api_key", None)
            if key:
                secrets.append(key)
    return secrets


def _safe_error(request: Request, exc: Exception | str) -> str:
    """Render an exception/message for a client with secrets redacted."""
    raw = str(exc) or (exc.__class__.__name__ if isinstance(exc, Exception) else "error")
    return redact_secrets(raw, _known_secrets(request))


def _record_failure(request: Request, exc: Exception) -> HTTPException:
    """Stash a short failure summary on app.state so /health can report it,
    then return a 502 the caller can `raise from exc`. The summary is redacted
    so a leaked upstream error can't expose an API key via /health.
    """
    message = _safe_error(request, exc)
    request.app.state.last_error = message
    m: _Metrics | None = getattr(request.app.state, "metrics", None)
    if m is not None:
        m.errors += 1
    logger.error("request to %s failed: %s", request.url.path, message)
    return HTTPException(status_code=502, detail=message)


def _trace_response(run: WorkflowRun) -> TraceResponse:
    stages = [TraceStageResponse(**stage.__dict__) for stage in run.stages]
    prompt_sum = sum((s.prompt_tokens or 0) for s in stages)
    completion_sum = sum((s.completion_tokens or 0) for s in stages)
    return TraceResponse(
        output=run.output,
        input_type=run.input_type,
        route=run.route,
        task_type=run.task_type,
        stages=stages,
        total_prompt_tokens=prompt_sum or None,
        total_completion_tokens=completion_sum or None,
        total_cost_usd=run.total_cost_usd,
    )


def _trace_payload(run: WorkflowRun) -> dict:
    # mode="json" yields a JSON-ready dict directly, avoiding a serialize-then-
    # reparse round-trip on every streamed trace event.
    return _trace_response(run).model_dump(mode="json")


# Paths reachable without the API key even when AUTUMN_API_KEY is set, so a
# container/uptime probe never has to carry the secret.
_AUTH_EXEMPT_PATHS = frozenset({"/health"})


def _extract_api_key(request: Request) -> str:
    """Pull the caller's key from ``X-API-Key`` or ``Authorization: Bearer <key>``."""
    header = request.headers.get("x-api-key")
    if header:
        return header.strip()
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        return auth[7:].strip()
    return ""


# Monotonic HTTP-surface revision. Bump whenever the API gains a capability a
# managed client may depend on. A locally-managed desktop client compares this
# against the minimum it needs and auto-restarts a server that predates a
# feature it uses (e.g. an old process left running across a `git pull`).
#   1 — MCP inline-connect surface (/mcps/status|connect|{id}, enriched catalog)
API_REVISION = 1


def _cors_origins() -> list[str]:
    """Allowed CORS origins from ``AUTUMN_CORS_ORIGINS`` (comma-separated).

    Defaults to ``*`` (unchanged) so existing clients keep working; operators
    can lock the API to known origins without touching code.
    """
    raw = os.environ.get("AUTUMN_CORS_ORIGINS", "*").strip()
    if not raw or raw == "*":
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


def _max_body_bytes() -> int:
    """Inbound request-body ceiling from ``AUTUMN_MAX_BODY_BYTES`` (default 4MB)."""
    raw = os.environ.get("AUTUMN_MAX_BODY_BYTES", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return MAX_REQUEST_BYTES


def create_app() -> FastAPI:
    app = FastAPI(title="Autumn HTTP API", version="0.3.4", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _limits_and_headers(request: Request, call_next):
        """Reject oversized request bodies (cheap DoS / cost-amplification guard)
        and stamp conservative security headers on every response."""
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit():
            if int(content_length) > _max_body_bytes():
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body exceeds {_max_body_bytes()} bytes."},
                )
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.middleware("http")
    async def _enforce_api_key(request: Request, call_next):
        """Gate every endpoint (except /health and CORS preflight) behind a
        shared secret when ``AUTUMN_API_KEY`` is set. Unset (the default for
        local single-user runs) → wide open, exactly as before. This is what
        makes the server safe to bind beyond localhost: without the key, no one
        who reaches the port can drive the agent, attach credentials, or read
        memory. The env is read per-request so it can be rotated without a
        restart, and the compare is constant-time."""
        expected = os.environ.get("AUTUMN_API_KEY", "").strip()
        if (
            expected
            and request.method != "OPTIONS"
            and request.url.path not in _AUTH_EXEMPT_PATHS
        ):
            provided = _extract_api_key(request)
            if not (provided and hmac.compare_digest(provided, expected)):
                return JSONResponse(
                    status_code=401, content={"detail": "Missing or invalid API key."},
                )
        return await call_next(request)

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "configured": app.state.autumn is not None,
            "last_error": app.state.last_error,
            # Lets a managed client tell a fresh server from a stale leftover.
            "api_revision": API_REVISION,
            "version": app.version,
        }

    @app.get("/metrics")
    async def metrics():
        m: _Metrics = app.state.metrics
        return {
            "runs": m.runs,
            "errors": m.errors,
            "prompt_tokens": m.prompt_tokens,
            "completion_tokens": m.completion_tokens,
            "uptime_seconds": round(time.time() - m.started_at, 1),
        }

    @app.post("/models", response_model=ModelsResponse)
    async def models(req: ModelsRequest):
        if not req.api_key.strip():
            raise HTTPException(status_code=400, detail="API key is required.")
        if not req.base_url.strip():
            raise HTTPException(status_code=400, detail="Base URL is required.")

        endpoint = _model_endpoint(req.base_url)
        # Same SSRF policy the model-facing fetchers enforce: refuse
        # loopback/private/metadata targets unless AUTUMN_ALLOW_PRIVATE_NETWORK=1
        # (which a localhost-Ollama setup legitimately sets).
        try:
            await assert_url_allowed(endpoint)
        except FetchError as exc:
            raise HTTPException(status_code=400, detail=f"Base URL not allowed: {exc}") from exc

        try:
            async with httpx.AsyncClient(
                headers=_headers_for(req.protocol, req.api_key.strip()),
                timeout=30.0,
                trust_env=False,
            ) as client:
                response = await client.get(endpoint)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Model list request failed with HTTP {exc.response.status_code}.",
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Model list request failed: {exc}",
            ) from exc

        return ModelsResponse(models=_parse_models(response.json()))

    @app.post("/config/apply", response_model=ApplyConfigResponse)
    async def apply_config(req: ApplyConfigRequest, request: Request):
        a4_config: ModelConfig | None = None
        if req.a4 and req.a4.api_key.strip():
            a4_config = _require_model_config("A4", req.a4)
        try:
            config = AutumnConfig(
                a1=_require_model_config("A1", req.a1),
                a2=_require_model_config("A2", req.a2),
                a3=_require_model_config("A3", req.a3),
                a4=a4_config,
                behavior=_behavior_from_request(req.behavior),
            )
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        async with request.app.state.apply_lock:
            old: Autumn | None = request.app.state.autumn
            new_autumn = Autumn(config)
            _register_builtin_terrs(new_autumn)
            _register_core_skills(new_autumn)
            request.app.state.autumn = new_autumn
            request.app.state.last_error = None
            if old is not None:
                await old.close()
            # Re-establish saved platform integrations on the new instance —
            # old.close() disconnected the previous MCP clients.
            await _reapply_integrations(request.app, new_autumn)
            # Re-arm the codebase-memory layer on the rebuilt instance when its
            # env flag is on (runtime-only toggles revert to .env on rebuild,
            # like 4D). Kept inside apply_lock so a concurrent apply can't close
            # this instance out from under the autostart (which spawns an MCP
            # subprocess) — integration_lock it acquires is a different lock.
            await _autostart_codebase_memory(request.app, new_autumn)
        return ApplyConfigResponse(status="ok", configured=True)

    @app.post("/process", response_model=ProcessResponse)
    async def process(req: ProcessRequest, request: Request):
        autumn = _autumn_or_503(request)
        await _activate_project(autumn, req.project_id)
        try:
            with project_context(req.project_id):
                run = await autumn.process_with_trace(
                    _apply_project_context(req.input, req.project_instructions),
                    mission_route=req.route,
                    input_type=req.input_type,
                    task_type=req.task_type,
                )
        except HTTPException:
            raise
        except Exception as exc:
            raise _record_failure(request, exc) from exc
        _record_run(request.app.state, run)
        return ProcessResponse(output=run.output)

    @app.post("/trace", response_model=TraceResponse)
    async def trace(req: ProcessRequest, request: Request):
        autumn = _autumn_or_503(request)
        await _activate_project(autumn, req.project_id)
        try:
            with project_context(req.project_id):
                run = await autumn.process_with_trace(
                    _apply_project_context(req.input, req.project_instructions),
                    mission_route=req.route,
                    input_type=req.input_type,
                    task_type=req.task_type,
                )
        except HTTPException:
            raise
        except Exception as exc:
            raise _record_failure(request, exc) from exc
        _record_run(request.app.state, run)
        return _trace_response(run)

    @app.post("/intent", response_model=IntentResponse)
    async def intent(req: IntentRequest, request: Request):
        autumn = _autumn_or_503(request)
        # Project instructions are advisory for intent classification too —
        # they may shift the classifier's read (e.g. a project full of code
        # work is more likely to interpret short prompts as TASK).
        try:
            with project_context(req.project_id):
                sel, route = await autumn.classify_intent(
                    _apply_project_context(req.input, req.project_instructions),
                    mission_route=req.route,
                    input_type=req.input_type,
                    task_type=req.task_type,
                )
        except HTTPException:
            raise
        except Exception as exc:
            raise _record_failure(request, exc) from exc
        return IntentResponse(
            input_type=sel.input_type,
            task_type=sel.task_type,
            route=route,
            confidence=sel.confidence,
            reasoning=sel.reasoning,
        )

    @app.get("/stream")
    async def stream(
        input: str,
        request: Request,
        route: RequestRoute = None,
        input_type: InputType | None = None,
        task_type: TaskType | None = None,
        project_instructions: str | None = None,
        project_id: str | None = None,
    ):
        autumn = _autumn_or_503(request)
        # The body-limit middleware only sees Content-Length, so a GET like
        # /stream?input=<MBs> would otherwise bypass the cost/DoS guard. Enforce
        # it explicitly on the query-string inputs that feed the model pipeline.
        limit = _max_body_bytes()
        for param, value in (("input", input), ("project_instructions", project_instructions)):
            if value and len(value.encode("utf-8")) > limit:
                raise HTTPException(
                    status_code=413, detail=f"{param} exceeds {limit} bytes.",
                )
        effective_input = _apply_project_context(input, project_instructions)

        async def event_stream():
            # Bind the active project for this stream. Set inside the generator so
            # the per-event Tasks spawned below copy a context that includes it,
            # which is what makes project-scoped memory skills resolve correctly.
            # Project activation + iterator construction live inside the try so a
            # failure there still emits a structured error frame + [DONE] instead
            # of tearing the SSE stream down with no signal to the client.
            proj_token = None
            iterator = None
            next_task: asyncio.Task | None = None
            try:
                await _activate_project(autumn, project_id)
                proj_token = set_current_project(project_id) if project_id else None
                stream_fn = getattr(autumn, "stream_with_trace", autumn.stream)
                iterator = stream_fn(
                    effective_input,
                    mission_route=route,
                    input_type=input_type,
                    task_type=task_type,
                ).__aiter__()
                while True:
                    if await request.is_disconnected():
                        return
                    if next_task is None:
                        next_task = asyncio.ensure_future(iterator.__anext__())
                    # Race the next event against an idle timer so a slow model
                    # call still gives us a chance to ping the proxy and to
                    # re-check the client connection.
                    done, _ = await asyncio.wait(
                        [next_task], timeout=_SSE_HEARTBEAT_SECONDS,
                    )
                    if next_task not in done:
                        yield ": ping\n\n"
                        continue
                    completed = next_task
                    next_task = None
                    try:
                        event = completed.result()
                    except StopAsyncIteration:
                        yield "data: [DONE]\n\n"
                        return
                    if isinstance(event, WorkflowRun):
                        _record_run(request.app.state, event)
                        payload = json.dumps(
                            {"trace": _trace_payload(event)}, ensure_ascii=False,
                        )
                    else:
                        payload = json.dumps({"chunk": event}, ensure_ascii=False)
                    yield f"data: {payload}\n\n"
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                message = _safe_error(request, exc)
                request.app.state.last_error = message
                payload = json.dumps({"error": message}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
                yield "data: [DONE]\n\n"
            finally:
                # If we exit while a next_task is still pending (disconnect or
                # error), cancel it so the upstream model isn't billed for a
                # response no one is going to read.
                if next_task is not None and not next_task.done():
                    next_task.cancel()
                    try:
                        await next_task
                    except (asyncio.CancelledError, StopAsyncIteration, Exception):
                        pass
                aclose = getattr(iterator, "aclose", None)
                if aclose is not None:
                    try:
                        await aclose()
                    except Exception:  # noqa: BLE001
                        pass
                if proj_token is not None:
                    reset_current_project(proj_token)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/terrs", response_model=list[TerrResponse])
    async def terrs(request: Request):
        autumn = _autumn_or_503(request)
        return autumn.describe_terrs()

    @app.patch("/terrs/{terr_name}", response_model=TerrResponse)
    async def update_terr(terr_name: str, req: TerrToggleRequest, request: Request):
        autumn = _autumn_or_503(request)
        try:
            return autumn.set_terr_enabled(terr_name, req.enabled)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"Unknown Terr: {terr_name}") from exc

    @app.get("/mcps/catalog", response_model=list[KnownMCPResponse])
    async def mcps_catalog():
        """Browse the built-in MCP catalog — the official servers the framework
        knows how to launch. Static (no configured Autumn needed) so clients can
        show what's available before any model is wired up."""
        from ..builtin import KNOWN_MCPS
        return KNOWN_MCPS

    @app.get("/integrations/catalog", response_model=list[IntegrationCatalogEntry])
    async def integrations_catalog():
        """The credentialed platforms the agent can be granted access to. Static,
        secret-free — drives the Settings input forms before anything is wired."""
        return integrations_mod.catalog()

    @app.get("/integrations/status", response_model=list[IntegrationStatusEntry])
    async def integrations_status(request: Request):
        """Per-platform connection state: connected?, how many tools it exposed,
        and the last connect error (never the credential itself)."""
        return _integration_status_list(request.app)

    @app.post("/integrations/connect", response_model=IntegrationStatusEntry)
    async def integrations_connect(req: IntegrationConnectRequest, request: Request):
        """Save a platform credential and bring its tools online for the agent.

        Reconnecting an already-connected platform tears the old session down
        first, so rotating a token just works. The agent picks up the tools
        immediately — no restart, no per-request plumbing."""
        return await _connect_mcp(
            request, req, validator=integrations_mod.is_known, label="集成",
        )

    @app.delete("/integrations/{integration_id}", response_model=IntegrationStatusEntry)
    async def integrations_disconnect(integration_id: str, request: Request):
        """Revoke a platform: disconnect its MCP server and forget the credential.
        Effective immediately — the agent loses those tools on the next turn."""
        return await _disconnect_mcp(
            request, integration_id, validator=integrations_mod.is_known, label="集成",
        )

    # ── generalized MCP connection (Terr-page surface) ──────────────────────────
    # The whole catalog, not just credentialed platforms: keyless utilities come
    # online with one click, configured MCPs after their form is filled. Shares
    # the integration runtime, so connect state is consistent across both UIs.

    @app.get("/mcps/status", response_model=list[IntegrationStatusEntry])
    async def mcps_status(request: Request):
        """Per-MCP connection state across the full catalog."""
        return _mcp_status_list(request.app)

    @app.post("/mcps/connect", response_model=IntegrationStatusEntry)
    async def mcps_connect(req: IntegrationConnectRequest, request: Request):
        """Bring any catalog MCP online for the agent — keyless or configured."""
        return await _connect_mcp(
            request, req, validator=integrations_mod.is_connectable, label="MCP",
        )

    @app.delete("/mcps/{mcp_id}", response_model=IntegrationStatusEntry)
    async def mcps_disconnect(mcp_id: str, request: Request):
        """Disconnect a catalog MCP and forget its saved configuration."""
        return await _disconnect_mcp(
            request, mcp_id, validator=integrations_mod.is_connectable, label="MCP",
        )

    # ── codebase-memory token-saving layer (framework subsystem) ────────────────
    # A first-class on/off switch for the framework-owned code-graph layer
    # (autumn.codebase). Flipping it starts/stops the codebase-memory-mcp server,
    # registers the `codebase` Terr, pre-warms the index, and from then on WP2
    # injects a graph-derived architecture brief into code tasks.

    @app.get("/config/codebase-memory", response_model=CodebaseMemoryStatusResponse)
    async def codebase_memory_status(request: Request):
        """Whether the codebase-memory token-saving layer is enabled / live / indexed."""
        autumn = _autumn_or_503(request)
        return _codebase_memory_status(request.app, autumn)

    @app.post("/config/codebase-memory", response_model=CodebaseMemoryStatusResponse)
    async def set_codebase_memory(req: CodebaseMemoryConfigRequest, request: Request):
        """Toggle the codebase-memory layer; starts/stops the framework subsystem.

        Returns the resulting state. A start failure (e.g. the binary isn't
        installed) is reported in ``error`` with the flag still flipped on, so
        the client can surface an install hint rather than silently doing nothing.
        """
        autumn = _autumn_or_503(request)
        b = getattr(getattr(autumn, "config", None), "behavior", None)
        starter = getattr(autumn, "start_codebase_memory", None)
        if b is None or starter is None:
            raise HTTPException(
                status_code=501,
                detail="This server build does not support the codebase-memory layer.",
            )
        b.codebase_memory_enabled = req.enabled
        repo = req.repo.strip() if req.repo is not None else None
        if repo is not None:
            b.codebase_memory_repo = repo
        async with request.app.state.integration_lock:
            try:
                if req.enabled:
                    await starter(repo)
                else:
                    await autumn.stop_codebase_memory()
                request.app.state.codebase_memory_error = None
            except Exception as exc:  # noqa: BLE001 - start spawns a subprocess
                request.app.state.codebase_memory_error = str(exc)
        return _codebase_memory_status(request.app, autumn)

    @app.get("/memory/{area}/history")
    async def get_history(
        area: MemoryArea,
        request: Request,
        limit: Annotated[int, Query(ge=1, le=_HISTORY_PAGE_MAX)] = _HISTORY_PAGE_DEFAULT,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        autumn = _autumn_or_503(request)
        mom = _memory_curator(autumn)._resolve(area)
        history = await mom.get_history()
        return history[offset:offset + limit]

    @app.get("/memory/stats")
    async def memory_stats_all(request: Request):
        """Aggregate stats across every zone WP4 manages."""
        autumn = _autumn_or_503(request)
        return await _memory_curator(autumn).stats()

    @app.get("/memory/{area}/stats")
    async def memory_stats(area: MemoryArea, request: Request):
        autumn = _autumn_or_503(request)
        return await _memory_curator(autumn).stats(area)

    @app.post("/memory/{area}/consolidate")
    async def memory_consolidate(
        area: MemoryArea, request: Request, req: ConsolidateRequest = ConsolidateRequest(),
    ):
        autumn = _autumn_or_503(request)
        wp4 = _curator_with_model_or_400(autumn)
        try:
            summary = await wp4.consolidate(
                area, keep_recent=req.keep_recent, min_candidates=req.min_candidates,
            )
        except Exception as exc:
            raise _record_failure(request, exc) from exc
        if summary is None:
            return {"status": "noop", "summary": None}
        return {"status": "ok", "summary": summary.to_dict()}

    @app.post("/memory/{area}/extract-facts")
    async def memory_extract_facts(
        area: MemoryArea, request: Request, req: ExtractFactsRequest = ExtractFactsRequest(),
    ):
        autumn = _autumn_or_503(request)
        wp4 = _curator_with_model_or_400(autumn)
        try:
            facts = await wp4.extract_facts(
                area, keep_recent=req.keep_recent, max_facts=req.max_facts,
            )
        except Exception as exc:
            raise _record_failure(request, exc) from exc
        return {"status": "ok", "facts": [f.to_dict() for f in facts]}

    @app.post("/memory/{area}/evolve")
    async def memory_evolve(
        area: MemoryArea, request: Request, req: EvolveRequest = EvolveRequest(),
    ):
        autumn = _autumn_or_503(request)
        wp4 = _curator_with_model_or_400(autumn)
        try:
            skills = await wp4.evolve(
                area, min_count=req.min_count,
                min_cluster=req.min_cluster, max_skills=req.max_skills,
            )
        except Exception as exc:
            raise _record_failure(request, exc) from exc
        return {"status": "ok", "skills": [s.to_dict() for s in skills]}

    @app.get("/memory/{area}/profile")
    async def memory_get_profile(area: MemoryArea, request: Request, scope: str = "default"):
        autumn = _autumn_or_503(request)
        wp4 = _memory_curator(autumn)
        return {"status": "ok", "scope": scope, "profile": await wp4.get_profile(area, scope=scope)}

    @app.post("/memory/{area}/profile")
    async def memory_synthesize_profile(
        area: MemoryArea, request: Request, req: ProfileRequest = ProfileRequest(),
    ):
        autumn = _autumn_or_503(request)
        wp4 = _curator_with_model_or_400(autumn)
        try:
            profile = await wp4.synthesize_profile(area, scope=req.scope)
        except Exception as exc:
            raise _record_failure(request, exc) from exc
        return {"status": "ok", "scope": req.scope, "profile": profile}

    @app.post("/memory/{area}/annotate", response_model=AnnotateResponse)
    async def annotate_memory_entry(
        area: MemoryArea, req: AnnotateRequest, request: Request,
    ):
        """Attach 4D dimensions to one history entry (the user/UI producer path).

        Mirrors the agent-facing ``annotate_memory`` skill: declare how a memory
        should be applied (mode), why it matters (intent), and what triggers it
        (scope/cues). Usage stats are preserved.
        """
        autumn = _autumn_or_503(request)
        zone = _memory_curator(autumn)._resolve(area)
        found = await zone.annotate(
            req.entry_id,
            mode=req.mode,
            intent=req.intent,
            goal_ref=req.goal_ref,
            scope=req.scope,
            cues=req.cues,
            half_life=req.half_life,
        )
        if not found:
            raise HTTPException(
                status_code=404,
                detail=f"Entry {req.entry_id!r} not found in {area} history.",
            )
        return AnnotateResponse(status="ok", entry_id=req.entry_id, found=True)

    @app.post("/memory/{area}/auto-annotate", response_model=AutoAnnotateResponse)
    async def auto_annotate(
        area: MemoryArea, request: Request,
        req: AutoAnnotateRequest = AutoAnnotateRequest(),
    ):
        """Run A4 over recent entries to infer and write their 4D dimensions.

        Needs the A4 model slot (400 if unconfigured). Returns how many entries
        were annotated and scanned.
        """
        autumn = _autumn_or_503(request)
        wp4 = _curator_with_model_or_400(autumn)
        try:
            result = await wp4.annotate_recent(
                area, n=req.n, only_unannotated=req.only_unannotated,
            )
        except Exception as exc:
            raise _record_failure(request, exc) from exc
        return AutoAnnotateResponse(status="ok", **result)

    @app.get("/memory/4d/status", response_model=FourDStatusResponse)
    async def fourd_status(request: Request):
        """Report whether the 4D engine is enabled — so the client can show it.

        The activation machinery is always present; these flags say whether it
        actually drives recall/eviction ranking and turn-start push, or sits
        dormant (collapsing to importance×recency).
        """
        autumn = _autumn_or_503(request)
        b = getattr(getattr(autumn, "config", None), "behavior", None)
        return FourDStatusResponse(
            fourd_memory_enabled=bool(getattr(b, "fourd_memory_enabled", False)),
            fourd_push_on_turn=bool(getattr(b, "fourd_push_on_turn", False)),
            fourd_pull_on_turn=bool(getattr(b, "fourd_pull_on_turn", True)),
            fourd_auto_annotate=bool(getattr(b, "fourd_auto_annotate", True)),
            fourd_auto_consolidate=bool(getattr(b, "fourd_auto_consolidate", True)),
            fourd_auto_evolve=bool(getattr(b, "fourd_auto_evolve", False)),
            mom1_access_enabled=bool(getattr(b, "mom1_access_enabled", True)),
        )

    @app.post("/memory/4d/config", response_model=FourDStatusResponse)
    async def set_fourd_config(req: FourDConfigRequest, request: Request):
        """Flip the 4D switches at runtime (env-set otherwise). Returns new state.

        501 on builds whose Autumn predates runtime 4D config.
        """
        autumn = _autumn_or_503(request)
        configure = getattr(autumn, "configure_4d", None)
        if configure is None:
            raise HTTPException(
                status_code=501,
                detail="Runtime 4D configuration is not available on this server.",
            )
        result = configure(
            memory_enabled=req.fourd_memory_enabled,
            push_on_turn=req.fourd_push_on_turn,
            pull_on_turn=req.fourd_pull_on_turn,
            auto_annotate=req.fourd_auto_annotate,
            auto_consolidate=req.fourd_auto_consolidate,
            auto_evolve=req.fourd_auto_evolve,
            mom1_access_enabled=req.mom1_access_enabled,
        )
        return FourDStatusResponse(**result)

    @app.post("/memory/push/preview", response_model=PushPreviewResponse)
    async def push_preview(req: PushPreviewRequest, request: Request):
        """Dry-run the push engine: what would auto-inject for this context.

        Runs the same ``activate_push`` the turn pipeline uses, but never
        reinforces — so inspecting the preview doesn't perturb usage stats. Only
        CONSTRAIN/REMIND memories are candidates. Works regardless of whether
        push is enabled on live turns (``enabled`` reports that separately).
        """
        import time as _t

        from ..core.memory.dimensions import ActivationContext
        from ..core.workspace.wp4 import render_push_context

        autumn = _autumn_or_503(request)
        wp4 = _memory_curator(autumn)
        cues = req.cues if req.cues is not None else [t for t in req.query.split() if t]
        ctx = ActivationContext(now=_t.time(), query=req.query or None, cues=cues)
        try:
            fired = await wp4.activate_push(area=req.area, ctx=ctx, k=req.k, reinforce=False)
        except Exception as exc:
            raise _record_failure(request, exc) from exc
        entries = [
            PushPreviewEntry(
                id=e.id,
                text=e.text[:300],
                mode=e.use.mode.value,
                intent=e.aim.intent,
                cues=list(e.trigger.cues),
                score=round(e.activation(ctx), 4),
            )
            for e in fired
        ]
        b = getattr(getattr(autumn, "config", None), "behavior", None)
        return PushPreviewResponse(
            fired=entries,
            fragment=render_push_context(fired),
            enabled=bool(getattr(b, "fourd_push_on_turn", False)),
        )

    @app.get("/memory/audit/access_log", response_model=AccessLogResponse)
    async def get_access_log(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=_HISTORY_PAGE_MAX)] = _HISTORY_PAGE_DEFAULT,
        offset: Annotated[int, Query(ge=0)] = 0,
        verdict: str | None = None,
    ):
        """Mom1 access audit log from WP4 memory.

        Each entry records one ``request_mom1_access`` invocation: the requester
        (mom2/mom3), query, A1's verdict, redaction flag, and A4 mediator used.
        ``verdict`` filters to ``"granted"`` or ``"denied"``; omit for all entries.
        """
        autumn = _autumn_or_503(request)
        wp4 = _memory_curator(autumn)
        history = await wp4.memory.get_history()
        access_entries = [e for e in history if "access" in e.tags]
        if verdict == "granted":
            access_entries = [e for e in access_entries if "mom1_access_granted" in e.tags]
        elif verdict == "denied":
            access_entries = [e for e in access_entries if "mom1_access_denied" in e.tags]
        access_entries.sort(key=lambda e: e.timestamp, reverse=True)
        total = len(access_entries)
        page = access_entries[offset:offset + limit]
        entries = []
        for e in page:
            c = e.content if isinstance(e.content, dict) else {}
            entries.append(AccessLogEntry(
                id=e.id,
                timestamp=e.timestamp,
                action=c.get("action", ""),
                requester=c.get("requester", ""),
                query=c.get("query", ""),
                reason=c.get("reason", ""),
                decision_reason=c.get("decision_reason", ""),
                redact=bool(c.get("redact", False)),
                entry_ids=c.get("entries") or [],
                mediated_by=c.get("mediated_by"),
            ))
        return AccessLogResponse(entries=entries, total=total)

    # ── Per-project shared memory ────────────────────────────────────────────
    # Each project id gets its own isolated shared memory zone. The zone is
    # written to whenever a /process, /trace or /stream call carries a
    # project_id (and project-scoped memory skills are wired). These endpoints
    # let the client list, inspect and clear that per-project memory.

    @app.get("/projects")
    async def list_projects(request: Request):
        autumn = _autumn_or_503(request)
        projects = _projects_or_501(autumn)
        return {"projects": await projects.list_projects()}

    @app.get("/projects/{project_id}/memory")
    async def project_memory(
        project_id: str,
        request: Request,
        limit: Annotated[int, Query(ge=1, le=_HISTORY_PAGE_MAX)] = _HISTORY_PAGE_DEFAULT,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        autumn = _autumn_or_503(request)
        projects = _projects_or_501(autumn)
        history = await projects.zone(project_id).get_history()
        return history[offset:offset + limit]

    @app.get("/projects/{project_id}/stats")
    async def project_stats(project_id: str, request: Request):
        autumn = _autumn_or_503(request)
        projects = _projects_or_501(autumn)
        return await projects.zone(project_id).stats()

    @app.post("/projects/{project_id}/consolidate")
    async def project_consolidate(
        project_id: str,
        request: Request,
        req: ConsolidateRequest = ConsolidateRequest(),
    ):
        autumn = _autumn_or_503(request)
        projects = _projects_or_501(autumn)
        wp4 = _curator_with_model_or_400(autumn)
        try:
            summary = await projects.zone(project_id).consolidate(
                wp4.api, keep_recent=req.keep_recent, min_candidates=req.min_candidates,
            )
        except Exception as exc:
            raise _record_failure(request, exc) from exc
        if summary is None:
            return {"status": "noop", "summary": None}
        return {"status": "ok", "summary": summary.to_dict()}

    @app.delete("/projects/{project_id}")
    async def clear_project(project_id: str, request: Request):
        autumn = _autumn_or_503(request)
        projects = _projects_or_501(autumn)
        await projects.clear_project(project_id)
        return {"status": "ok", "project_id": project_id}

    # ── Project metadata ─────────────────────────────────────────────────────
    # Structured fields: type, description, goals, files, environment.
    # Metadata lives in the project's own zone under a reserved __meta__ key
    # and is therefore isolated between projects and persisted across restarts.

    @app.get("/projects/{project_id}/metadata")
    async def get_project_metadata(project_id: str, request: Request):
        """Return the full :class:`ProjectMeta` for a project."""
        autumn = _autumn_or_503(request)
        projects = _projects_or_501(autumn)
        meta = await projects.zone(project_id).get_meta()
        return meta.to_dict()

    @app.patch("/projects/{project_id}/metadata")
    async def update_project_metadata(
        project_id: str,
        request: Request,
        body: ProjectMetaUpdateRequest = ProjectMetaUpdateRequest(),
    ):
        """Partially update a project's metadata. Omitted fields are unchanged."""
        autumn = _autumn_or_503(request)
        projects = _projects_or_501(autumn)
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        meta = await projects.update_metadata(project_id, **updates)
        return meta.to_dict()

    @app.post("/projects/{project_id}/files")
    async def add_project_file(
        project_id: str,
        request: Request,
        body: AddFileRequest,
    ):
        """Append a file path to the project's tracked file list."""
        autumn = _autumn_or_503(request)
        projects = _projects_or_501(autumn)
        await projects.zone(project_id).add_file(body.path)
        meta = await projects.zone(project_id).get_meta()
        return {"status": "ok", "files": meta.files}

    @app.delete("/projects/{project_id}/files/{file_path:path}")
    async def remove_project_file(
        project_id: str,
        file_path: str,
        request: Request,
    ):
        """Remove a file path from the project's tracked file list."""
        autumn = _autumn_or_503(request)
        projects = _projects_or_501(autumn)
        await projects.zone(project_id).remove_file(file_path)
        meta = await projects.zone(project_id).get_meta()
        return {"status": "ok", "files": meta.files}

    @app.post("/projects/{project_id}/describe")
    async def draft_project_description(
        project_id: str,
        request: Request,
        body: ProjectDescribeRequest,
    ):
        """Ask A1 to synthesise a project description from free-text input.

        Returns the drafted text; does **not** auto-save it.  To persist, follow
        up with ``PATCH /projects/{id}/metadata`` and ``description=<result>``.
        """
        autumn = _autumn_or_503(request)
        _projects_or_501(autumn)
        wp1 = _project_coordinator_or_400(autumn)
        try:
            description = await wp1.draft_description(body.input, project_id)
        except Exception as exc:
            raise _record_failure(request, exc) from exc
        return {"description": description}

    @app.post("/projects/{project_id}/goals")
    async def draft_project_goals(
        project_id: str,
        request: Request,
        body: ProjectGoalsRequest,
    ):
        """Ask A1 to structure goals into master/long_term/short_term.

        Returns the drafted goal hierarchy; does **not** auto-save it.  To
        persist, follow up with ``PATCH /projects/{id}/metadata``
        and ``goals=<result>``.
        """
        autumn = _autumn_or_503(request)
        _projects_or_501(autumn)
        wp1 = _project_coordinator_or_400(autumn)
        try:
            goals = await wp1.draft_goals(body.input, project_id)
        except Exception as exc:
            raise _record_failure(request, exc) from exc
        return goals.to_dict()

    @app.post("/projects/{project_id}/infer-environment")
    async def infer_project_environment(project_id: str, request: Request):
        """Ask A1 to infer and persist the environment config for a project.

        Reads the project's type, description, and master goal, calls A1, and
        writes the resulting environment (terrs, skills, tools, MCP, agent
        channel) directly into the project's metadata. Returns the full updated
        metadata.
        """
        autumn = _autumn_or_503(request)
        _projects_or_501(autumn)
        wp1 = _project_coordinator_or_400(autumn)
        try:
            meta = await wp1.infer_environment(project_id)
        except Exception as exc:
            raise _record_failure(request, exc) from exc
        return meta.to_dict()

    @app.post("/session/end")
    async def end_session(request: Request):
        autumn = _autumn_or_503(request)
        await autumn.end_session()
        return {"status": "ok"}

    # ── Ollama (local model) management ──────────────────────────────────────
    # Proxy to a local Ollama daemon so the user can deploy and wire up a local
    # A4 memory model from inside the app. These do NOT require Autumn to be
    # configured — you set up the local model *before* applying config.
    #
    # The model must be reachable by *this server*: local models work when the
    # server runs alongside Ollama (local dev / self-host). A cloud container
    # can't see your machine's localhost, so there /ollama/status reports down —
    # which is correct, because A4 inference couldn't reach it either.

    @app.post("/ollama/status")
    async def ollama_status(req: OllamaTarget):
        base = _ollama_base(req.base_url)
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                resp = await client.get(f"{base}/api/version")
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            return {"running": False, "base_url": base, "error": _ollama_unavailable_detail(base, exc)}
        return {"running": True, "base_url": base, "version": data.get("version")}

    @app.post("/ollama/models")
    async def ollama_models(req: OllamaTarget):
        base = _ollama_base(req.base_url)
        try:
            async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                resp = await client.get(f"{base}/api/tags")
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=_ollama_unavailable_detail(base, exc)) from exc
        models = []
        for item in payload.get("models", []):
            details = item.get("details") or {}
            models.append(
                {
                    "name": item.get("name"),
                    "size": item.get("size"),
                    "parameter_size": details.get("parameter_size"),
                    "family": details.get("family"),
                    "modified_at": item.get("modified_at"),
                },
            )
        return {"models": models}

    @app.delete("/ollama/models")
    async def ollama_delete(req: OllamaDeleteRequest):
        base = _ollama_base(req.base_url)
        try:
            async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
                resp = await client.request(
                    "DELETE",
                    f"{base}/api/delete",
                    json={"name": req.name, "model": req.name},
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"删除失败。{_ollama_unavailable_detail(base, exc)}") from exc
        return {"status": "ok", "name": req.name}

    @app.get("/ollama/recommended")
    async def ollama_recommended():
        return {"models": _OLLAMA_RECOMMENDED}

    @app.get("/ollama/pull")
    async def ollama_pull(
        name: str,
        request: Request,
        base_url: str = "http://127.0.0.1:11434",
    ):
        base = _ollama_base(base_url)

        async def event_stream():
            # No read timeout — a pull can take minutes — but bound the connect.
            timeout = httpx.Timeout(None, connect=5.0)
            try:
                async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                    async with client.stream(
                        "POST",
                        f"{base}/api/pull",
                        json={"name": name, "model": name, "stream": True},
                    ) as resp:
                        if resp.status_code != 200:
                            body = (await resp.aread()).decode("utf-8", "ignore")
                            err = json.dumps(
                                {"error": f"Ollama 拉取失败（{base}）HTTP {resp.status_code}: {body[:200]}"},
                                ensure_ascii=False,
                            )
                            yield f"data: {err}\n\n"
                            yield "data: [DONE]\n\n"
                            return
                        async for line in resp.aiter_lines():
                            if await request.is_disconnected():
                                return
                            line = line.strip()
                            if line:
                                # Ollama emits NDJSON progress; forward each verbatim.
                                yield f"data: {line}\n\n"
                yield "data: [DONE]\n\n"
            except httpx.HTTPError as exc:
                err = json.dumps({"error": _ollama_unavailable_detail(base, exc)}, ensure_ascii=False)
                yield f"data: {err}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return app


app = create_app()


def main():
    """Entrypoint for `python -m autumn.server`."""
    import uvicorn

    host = os.environ.get("AUTUMN_HOST", "127.0.0.1")
    port = int(os.environ.get("AUTUMN_PORT", "8765"))
    reload = os.environ.get("AUTUMN_RELOAD") == "1"

    # Loud warning for the one genuinely dangerous configuration: reachable
    # beyond localhost with no API key, i.e. anyone on the network can drive the
    # agent and read every memory zone.
    bound_public = host not in ("127.0.0.1", "localhost", "::1")
    if bound_public and not os.environ.get("AUTUMN_API_KEY", "").strip():
        import warnings

        warnings.warn(
            f"Autumn is binding to {host}:{port} with no AUTUMN_API_KEY set — "
            "every endpoint is unauthenticated and reachable from the network. "
            "Set AUTUMN_API_KEY to require a shared secret on all requests.",
            stacklevel=2,
        )

    uvicorn.run(
        "autumn.server.app:app",
        host=host,
        port=port,
        reload=reload,
    )

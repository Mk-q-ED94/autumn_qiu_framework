"""HTTP/SSE bridge that exposes Autumn to the SwiftUI desktop client."""
import asyncio
import json
import os
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..core.config import AutumnConfig, ModelConfig
from ..core.framework import Autumn
from ..core.memory.project import project_context, set_current_project, reset_current_project
from ..core.types import InputType, MissionRoute, Protocol, TaskType, WorkflowRun


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

MemoryArea = Literal["mom1", "mom2", "mom3"]


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


class ProviderConfigRequest(BaseModel):
    api_key: str
    base_url: str
    model: str | None = None
    protocol: Protocol
    # Optional USD price per 1M tokens; enables per-turn cost in the trace.
    input_price_per_1m: float = 0.0
    output_price_per_1m: float = 0.0


class ApplyConfigRequest(BaseModel):
    a1: ProviderConfigRequest
    a2: ProviderConfigRequest
    a3: ProviderConfigRequest
    a4: ProviderConfigRequest | None = None


class ApplyConfigResponse(BaseModel):
    status: str
    configured: bool


class ModelsRequest(BaseModel):
    api_key: str
    base_url: str
    protocol: Protocol


class ModelsResponse(BaseModel):
    models: list[str]


class OllamaTarget(BaseModel):
    base_url: str = "http://localhost:11434"


class OllamaDeleteRequest(OllamaTarget):
    name: str


def _try_build_from_env() -> Autumn | None:
    if os.environ.get("AUTUMN_SKIP_INIT") == "1":
        return None
    env_file = os.environ.get("AUTUMN_ENV_FILE", ".env")
    try:
        config = AutumnConfig.from_env(env_file=env_file)
    except (KeyError, ValueError) as exc:
        print(f"[autumn-server] startup config missing ({exc}); endpoints will return 503.")
        return None
    return Autumn(config)


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
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    return root or "http://localhost:11434"


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
    # apply_lock serialises swap-out of state.autumn so two concurrent
    # /config/apply calls can't leak an Autumn instance whose close() never runs.
    app.state.apply_lock = asyncio.Lock()
    app.state.last_error = None
    try:
        yield
    finally:
        if app.state.autumn is not None:
            await app.state.autumn.close()


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
            status_code=501, detail="Per-project memory is not available on this server."
        )
    return projects


def _record_failure(request: Request, exc: Exception) -> HTTPException:
    """Stash a short failure summary on app.state so /health can report it,
    then return a 502 the caller can `raise from exc`."""
    message = str(exc) or exc.__class__.__name__
    request.app.state.last_error = message
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
    return json.loads(_trace_response(run).json())


def create_app() -> FastAPI:
    app = FastAPI(title="Autumn HTTP API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "configured": app.state.autumn is not None,
            "last_error": app.state.last_error,
        }

    @app.post("/models", response_model=ModelsResponse)
    async def models(req: ModelsRequest):
        if not req.api_key.strip():
            raise HTTPException(status_code=400, detail="API key is required.")
        if not req.base_url.strip():
            raise HTTPException(status_code=400, detail="Base URL is required.")

        try:
            async with httpx.AsyncClient(
                headers=_headers_for(req.protocol, req.api_key.strip()),
                timeout=30.0,
            ) as client:
                response = await client.get(_model_endpoint(req.base_url))
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
            )
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        async with request.app.state.apply_lock:
            old: Autumn | None = request.app.state.autumn
            request.app.state.autumn = Autumn(config)
            request.app.state.last_error = None
            if old is not None:
                await old.close()
        return ApplyConfigResponse(status="ok", configured=True)

    @app.post("/process", response_model=ProcessResponse)
    async def process(req: ProcessRequest, request: Request):
        autumn = _autumn_or_503(request)
        await _activate_project(autumn, req.project_id)
        try:
            with project_context(req.project_id):
                output = await autumn.process(
                    _apply_project_context(req.input, req.project_instructions),
                    mission_route=req.route,
                    input_type=req.input_type,
                    task_type=req.task_type,
                )
        except HTTPException:
            raise
        except Exception as exc:
            raise _record_failure(request, exc) from exc
        return ProcessResponse(output=output)

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
        effective_input = _apply_project_context(input, project_instructions)

        async def event_stream():
            # Bind the active project for this stream. Set inside the generator so
            # the per-event Tasks spawned below copy a context that includes it,
            # which is what makes project-scoped memory skills resolve correctly.
            await _activate_project(autumn, project_id)
            proj_token = set_current_project(project_id) if project_id else None
            stream_fn = getattr(autumn, "stream_with_trace", autumn.stream)
            iterator = stream_fn(
                effective_input,
                mission_route=route,
                input_type=input_type,
                task_type=task_type,
            ).__aiter__()
            next_task: asyncio.Task | None = None
            try:
                while True:
                    if await request.is_disconnected():
                        return
                    if next_task is None:
                        next_task = asyncio.ensure_future(iterator.__anext__())
                    # Race the next event against an idle timer so a slow model
                    # call still gives us a chance to ping the proxy and to
                    # re-check the client connection.
                    done, _ = await asyncio.wait(
                        [next_task], timeout=_SSE_HEARTBEAT_SECONDS
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
                        payload = json.dumps(
                            {"trace": _trace_payload(event)}, ensure_ascii=False
                        )
                    else:
                        payload = json.dumps({"chunk": event}, ensure_ascii=False)
                    yield f"data: {payload}\n\n"
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                request.app.state.last_error = str(exc)
                payload = json.dumps({"error": str(exc)}, ensure_ascii=False)
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

    @app.get("/memory/{area}/history")
    async def get_history(
        area: MemoryArea,
        request: Request,
        limit: int = Query(_HISTORY_PAGE_DEFAULT, ge=1, le=_HISTORY_PAGE_MAX),
        offset: int = Query(0, ge=0),
    ):
        autumn = _autumn_or_503(request)
        mom = {"mom1": autumn.mom1, "mom2": autumn.mom2, "mom3": autumn.mom3}[area]
        history = await mom.get_history()
        return history[offset:offset + limit]

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
        limit: int = Query(_HISTORY_PAGE_DEFAULT, ge=1, le=_HISTORY_PAGE_MAX),
        offset: int = Query(0, ge=0),
    ):
        autumn = _autumn_or_503(request)
        projects = _projects_or_501(autumn)
        history = await projects.zone(project_id).get_history()
        return history[offset:offset + limit]

    @app.delete("/projects/{project_id}")
    async def clear_project(project_id: str, request: Request):
        autumn = _autumn_or_503(request)
        projects = _projects_or_501(autumn)
        await projects.clear_project(project_id)
        return {"status": "ok", "project_id": project_id}

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
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{base}/api/version")
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            return {"running": False, "base_url": base, "error": str(exc)}
        return {"running": True, "base_url": base, "version": data.get("version")}

    @app.post("/ollama/models")
    async def ollama_models(req: OllamaTarget):
        base = _ollama_base(req.base_url)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base}/api/tags")
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Ollama 未响应: {exc}") from exc
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
                }
            )
        return {"models": models}

    @app.delete("/ollama/models")
    async def ollama_delete(req: OllamaDeleteRequest):
        base = _ollama_base(req.base_url)
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.request(
                    "DELETE",
                    f"{base}/api/delete",
                    json={"name": req.name, "model": req.name},
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"删除失败: {exc}") from exc
        return {"status": "ok", "name": req.name}

    @app.get("/ollama/recommended")
    async def ollama_recommended():
        return {"models": _OLLAMA_RECOMMENDED}

    @app.get("/ollama/pull")
    async def ollama_pull(
        name: str,
        request: Request,
        base_url: str = "http://localhost:11434",
    ):
        base = _ollama_base(base_url)

        async def event_stream():
            # No read timeout — a pull can take minutes — but bound the connect.
            timeout = httpx.Timeout(None, connect=5.0)
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream(
                        "POST",
                        f"{base}/api/pull",
                        json={"name": name, "model": name, "stream": True},
                    ) as resp:
                        if resp.status_code != 200:
                            body = (await resp.aread()).decode("utf-8", "ignore")
                            err = json.dumps(
                                {"error": f"HTTP {resp.status_code}: {body[:200]}"},
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
                err = json.dumps({"error": f"Ollama 未响应: {exc}"}, ensure_ascii=False)
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
    uvicorn.run(
        "autumn.server.app:app",
        host=host,
        port=port,
        reload=reload,
    )

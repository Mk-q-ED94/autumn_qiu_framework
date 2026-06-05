"""HTTP/SSE bridge that exposes Autumn to the SwiftUI desktop client."""
import json
import os
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..core.config import AutumnConfig, ModelConfig
from ..core.framework import Autumn
from ..core.types import InputType, MissionRoute, Protocol, WorkflowRun


RequestRoute = MissionRoute | Literal["auto"] | None


class ProcessRequest(BaseModel):
    input: str
    route: RequestRoute = None


class ProcessResponse(BaseModel):
    output: str


class TraceStageResponse(BaseModel):
    id: str
    title: str
    detail: str
    workspace: str
    status: str


class TraceResponse(BaseModel):
    output: str
    input_type: InputType
    route: MissionRoute | None = None
    stages: list[TraceStageResponse]


class ProviderConfigRequest(BaseModel):
    api_key: str
    base_url: str
    model: str | None = None
    protocol: Protocol


class ApplyConfigRequest(BaseModel):
    a1: ProviderConfigRequest
    a2: ProviderConfigRequest
    a3: ProviderConfigRequest


class ApplyConfigResponse(BaseModel):
    status: str
    configured: bool


class ModelsRequest(BaseModel):
    api_key: str
    base_url: str
    protocol: Protocol


class ModelsResponse(BaseModel):
    models: list[str]


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
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.autumn = _try_build_from_env()
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


def _trace_response(run: WorkflowRun) -> TraceResponse:
    return TraceResponse(
        output=run.output,
        input_type=run.input_type,
        route=run.route,
        stages=[TraceStageResponse(**stage.__dict__) for stage in run.stages],
    )


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
        configured = app.state.autumn is not None
        return {"status": "ok", "configured": configured}

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
        config = AutumnConfig(
            a1=_require_model_config("A1", req.a1),
            a2=_require_model_config("A2", req.a2),
            a3=_require_model_config("A3", req.a3),
        )

        old: Autumn | None = request.app.state.autumn
        request.app.state.autumn = Autumn(config)
        if old is not None:
            await old.close()
        return ApplyConfigResponse(status="ok", configured=True)

    @app.post("/process", response_model=ProcessResponse)
    async def process(req: ProcessRequest, request: Request):
        autumn = _autumn_or_503(request)
        output = await autumn.process(req.input, mission_route=req.route)
        return ProcessResponse(output=output)

    @app.post("/trace", response_model=TraceResponse)
    async def trace(req: ProcessRequest, request: Request):
        autumn = _autumn_or_503(request)
        run = await autumn.process_with_trace(req.input, mission_route=req.route)
        return _trace_response(run)

    @app.get("/stream")
    async def stream(input: str, request: Request, route: RequestRoute = None):
        autumn = _autumn_or_503(request)

        async def event_stream():
            try:
                async for chunk in autumn.stream(input, mission_route=route):
                    payload = json.dumps({"chunk": chunk}, ensure_ascii=False)
                    yield f"data: {payload}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as exc:  # noqa: BLE001
                payload = json.dumps({"error": str(exc)}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
                yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/memory/{area}/history")
    async def get_history(area: str, request: Request):
        autumn = _autumn_or_503(request)
        mom = {"mom1": autumn.mom1, "mom2": autumn.mom2, "mom3": autumn.mom3}.get(area)
        if mom is None:
            raise HTTPException(status_code=404, detail=f"Unknown memory area: {area}")
        return await mom.get_history()

    @app.post("/session/end")
    async def end_session(request: Request):
        autumn = _autumn_or_503(request)
        await autumn.end_session()
        return {"status": "ok"}

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

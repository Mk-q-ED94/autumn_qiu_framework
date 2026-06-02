"""HTTP/SSE bridge that exposes Autumn to the SwiftUI desktop client."""
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..core.config import AutumnConfig
from ..core.framework import Autumn


class ProcessRequest(BaseModel):
    input: str


class ProcessResponse(BaseModel):
    output: str


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

    @app.post("/process", response_model=ProcessResponse)
    async def process(req: ProcessRequest, request: Request):
        autumn = _autumn_or_503(request)
        output = await autumn.process(req.input)
        return ProcessResponse(output=output)

    @app.get("/stream")
    async def stream(input: str, request: Request):
        autumn = _autumn_or_503(request)

        async def event_stream():
            try:
                async for chunk in autumn.stream(input):
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

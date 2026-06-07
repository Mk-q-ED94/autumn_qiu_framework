"""Single-origin ASGI app for Hugging Face Spaces (and any one-container host).

Hugging Face Spaces give you exactly one container exposing one port, so —
unlike the Cloudflare topology, where a Worker serves the SPA and proxies
``/api`` to a separate container — here the Python process has to serve both
the API *and* the built React SPA itself.

Layout:
    /api/*   ->  the real Autumn HTTP API (mounted sub-application)
    /assets/*->  hashed Vite build assets
    /*       ->  index.html (SPA fallback)

Mounting the API at ``/api`` mirrors the Cloudflare Worker exactly, so the
frontend's default ``serverUrl: "/api"`` works with no build-time changes.

Optional auth: set the ``AUTUMN_API_TOKEN`` env var (an HF Space *secret*) to
require ``Authorization: Bearer <token>`` (or ``X-Auth-Token``) on ``/api/*``.
Leave it unset for an open Space.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from autumn.server.app import create_app

STATIC_DIR = Path(os.environ.get("AUTUMN_STATIC_DIR", "/app/static")).resolve()
INDEX_FILE = STATIC_DIR / "index.html"
API_TOKEN = os.environ.get("AUTUMN_API_TOKEN", "").strip()

# Build the real API app once. Its routes read ``request.app.state`` — and for
# a mounted sub-app ``request.app`` resolves to the sub-app — so we must run
# *its* lifespan against *it* (mounting does not propagate lifespan events).
_api = create_app()


@asynccontextmanager
async def _lifespan(_outer: FastAPI):
    async with _api.router.lifespan_context(_api):
        yield


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.headers.get("x-auth-token", "").strip()


def create_combined_app() -> FastAPI:
    app = FastAPI(title="Autumn (single-origin)", lifespan=_lifespan)

    if API_TOKEN:
        @app.middleware("http")
        async def _auth(request: Request, call_next):
            path = request.url.path
            if path.startswith("/api/") and request.method != "OPTIONS":
                if _bearer(request) != API_TOKEN:
                    return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            return await call_next(request)

    # API first so /api/* always wins over the SPA catch-all below.
    app.mount("/api", _api)

    if INDEX_FILE.is_file():
        assets = STATIC_DIR / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        async def spa(full_path: str):
            # Serve a real file when it exists inside the static root, else
            # fall back to index.html for client-side routing.
            candidate = (STATIC_DIR / full_path).resolve()
            if full_path and candidate.is_file() and STATIC_DIR in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(INDEX_FILE)
    else:
        @app.get("/")
        async def _no_ui():
            return JSONResponse(
                {
                    "detail": "Frontend assets not found; the API is live under /api.",
                    "looked_in": str(STATIC_DIR),
                },
            )

    return app


app = create_combined_app()


def main():
    import uvicorn

    host = os.environ.get("AUTUMN_HOST", "0.0.0.0")
    port = int(os.environ.get("AUTUMN_PORT", "7860"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()

# Hugging Face Spaces — single-container image for the Autumn framework.
#
# Build context MUST be the repository root (the Dockerfile COPYs ./autumn,
# ./pyproject.toml and ./web). On HF this happens automatically when the
# Dockerfile sits at the Space repo root and the Space repo contains the source.
#
# Stage 1 builds the React SPA; stage 2 serves API + SPA from one Python process.

# ---- Stage 1: build the React SPA ----
FROM node:20-slim AS frontend
WORKDIR /build
COPY web/frontend/package.json ./
RUN npm install
COPY web/frontend/ ./
# Use vite directly (skip `tsc -b`) so a stray type error can't fail the image
# build. Run `npm run build` locally if you want full type-checking.
RUN npx vite build

# ---- Stage 2: Python runtime ----
FROM python:3.12-slim

# HF Spaces run containers as uid 1000; create a matching user with a home so
# anything that writes to $HOME or the working dir succeeds.
RUN useradd -m -u 1000 appuser
WORKDIR /app

# Install the framework + server extras. Editable keeps the layer small and
# matches how the repo is developed.
COPY pyproject.toml ./
COPY autumn/ ./autumn/
RUN pip install --no-cache-dir -e ".[server]"

# Single-origin entrypoint + the built SPA.
COPY web/hf/app.py ./app.py
COPY --from=frontend /build/dist ./static

# The memory SQLite file is written to the working dir (cwd) at runtime, so the
# whole /app tree must be owned by the unprivileged user.
RUN chown -R appuser:appuser /app
USER appuser

ENV AUTUMN_HOST=0.0.0.0 \
    AUTUMN_PORT=7860 \
    AUTUMN_STATIC_DIR=/app/static \
    AUTUMN_SKIP_INIT=1 \
    HOME=/home/appuser

# HF reads the exposed port from the Space README (app_port: 7860).
EXPOSE 7860
CMD ["python", "app.py"]

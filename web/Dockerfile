FROM python:3.12-slim

# System deps: Node.js for npx MCP servers, curl for health probes
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# uv for uvx-based MCP servers
RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy autumn package (build context = repo root)
COPY autumn/ ./autumn/
COPY pyproject.toml ./

RUN pip install --no-cache-dir -e ".[server]"

# Persistent data dir — mount a volume here for durable Mom1/2/3 SQLite files.
# Without a volume the DBs are ephemeral per container instance, which is fine
# for stateless / preview deployments.
RUN mkdir -p /data

ENV AUTUMN_HOST=0.0.0.0
ENV AUTUMN_PORT=8765
ENV AUTUMN_DB=/data/autumn
ENV AUTUMN_SKIP_INIT=0

EXPOSE 8765

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -sf http://localhost:8765/health || exit 1

CMD ["python", "-m", "autumn.server"]

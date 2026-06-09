# Autumn Web — Cloudflare Deployment

Single-command deploy of the Autumn multi-agent framework to Cloudflare:

- **Worker** (TypeScript) — auth middleware, CORS, SSE proxy
- **Container** (Python FastAPI) — runs `autumn.server` in Docker on Cloudflare infrastructure
- **SPA** (React + Vite) — served as static assets from Cloudflare's CDN

```
Browser ──HTTPS──► Worker
                     ├─ /api/* ──► AutumnContainer (Python FastAPI)
                     └─ /*     ──► Static SPA assets
```

## Prerequisites

- [Cloudflare account](https://dash.cloudflare.com/) with Containers beta access
- Wrangler CLI ≥ 3.99: `npm i -g wrangler`
- Node.js ≥ 18, Docker (for local container builds)

### Enable Cloudflare Containers beta

1. Go to **Workers & Pages → Overview** in the Cloudflare dashboard
2. Click **"Join beta"** under *Containers*
3. Wait for approval (usually instant for paid plans)

## First-time setup

```bash
cd web

# Authenticate with Cloudflare
wrangler login

# (Optional) Set an auth token to protect your deployment
wrangler secret put AUTH_TOKEN
# Enter a random secret — the frontend prompts for it on first load
```

## Deploy

```bash
cd web
npm run deploy
```

This runs:
1. `cd frontend && npm install && npm run build` — builds the React SPA into `frontend/dist/`
2. `wrangler deploy` — builds the Docker image, pushes the container, deploys the Worker + assets

## Local development

Run the Python server and the Vite dev server in two terminals:

```bash
# Terminal 1 — Python backend
pip install -e ".[server]"
python -m autumn.server   # listens on 127.0.0.1:8765

# Terminal 2 — Vite frontend (proxies /api → localhost:8765)
cd web
npm run dev:frontend
# Open http://localhost:5173
```

The Vite proxy rewrites `/api/*` → `http://127.0.0.1:8765/*` so no CORS setup is needed.

In local mode the Worker and Container are not involved — the SPA talks directly to the local Python server via the Vite proxy.

## Local models for A4 (Ollama)

A4 is the optional **memory model** (recall synthesis) — a good fit for a cheap
local LLM. The app can deploy and wire one up for you:

1. Install [Ollama](https://ollama.com/download) on the machine running the
   Autumn server, and `ollama serve`.
2. In the app: **Settings → 模型 → enable A4**. The **本地模型 · Ollama** panel
   appears, shows daemon status, and lists installed + recommended models.
3. Click **拉取** on a recommended model (e.g. `qwen2.5:1.5b`) — it downloads
   with a progress bar and, when done, auto-configures A4 to use it. Or click
   **用于 A4** on any already-installed model.
4. **应用配置** to activate.

The server proxies Ollama's API under `/api/ollama/*`, so model management and
A4 inference always hit the *same* daemon. This means local models work when the
server can reach Ollama — i.e. **local dev or self-host**. On a cloud Container
the daemon isn't reachable, and the panel correctly reports "未运行"; point the
panel's *Ollama 地址* at a reachable host if you self-host Ollama elsewhere.

## Environment variables / secrets

| Name | Where | Description |
|------|-------|-------------|
| `AUTH_TOKEN` | Wrangler secret | Optional bearer token. If set, all `/api/*` requests must include `Authorization: Bearer <token>` or `X-Auth-Token: <token>`. |
| `AUTUMN_HOST` | Dockerfile ENV | Bind address inside container (default `0.0.0.0`). |
| `AUTUMN_PORT` | Dockerfile ENV | Port the Python server listens on (default `8765`). |
| `AUTUMN_DB` | Dockerfile ENV | Path prefix for the SQLite persistence file (default `/data/autumn`). |

To add more secrets visible to the Python container, expose them in `worker/src/index.ts` via the `Env` interface and forward them as headers in the container proxy section.

## Project layout

```
web/
├── Dockerfile          # Python container (copies ../autumn from repo root)
├── .dockerignore
├── wrangler.toml       # Cloudflare config: Container, Assets, Durable Objects
├── package.json        # Top-level: build + deploy scripts
│
├── worker/
│   ├── src/index.ts    # TypeScript Worker (auth, CORS, routing)
│   ├── package.json
│   └── tsconfig.json
│
└── frontend/
    ├── index.html
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── styles.css
        ├── types.ts
        ├── api/client.ts
        └── components/
            ├── ChatView.tsx
            ├── ComposerBar.tsx
            ├── MemoryPanel.tsx
            ├── PipelineStrip.tsx
            ├── SettingsPanel.tsx
            ├── Sidebar.tsx
            └── TerrPanel.tsx
```

## Architecture notes

### Container lifecycle

The `AutumnContainer` Durable Object wraps the Python container:

```typescript
export class AutumnContainer extends Container<Env> {
  defaultPort = 8765;   // matches AUTUMN_PORT
  sleepAfter = "10m";   // container hibernates after 10 min idle
}
```

All requests are routed to the single `"autumn"` instance (`idFromName("autumn")`), so state is shared across all users. For multi-tenant use, change the ID to a per-user value.

### SSE streaming

The frontend uses `fetch` + `ReadableStream` (not `EventSource`) so it can include the `Authorization` header. The async generator `streamChat()` in `api/client.ts` yields `{ chunk }`, `{ trace }`, or `{ error }` events as they arrive from the Python server.

### Auth flow

```
fetch /api/stream?input=...
  Authorization: Bearer <token>
    └► Worker checks token
          ├─ 401 if mismatch
          └─ forward to container (token stripped)
```

The token is stored in `localStorage` inside the Settings panel and is never sent to any third party.

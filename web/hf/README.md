# Autumn on Hugging Face Spaces (free)

Run the whole framework — Python backend **and** React UI — in a single free
Hugging Face **Docker Space**. No credit card, no Cloudflare, no server to keep
running. The Space sleeps when idle and wakes on the next visit.

```
Browser ──HTTPS──► HF Space (one container, port 7860)
                     ├─ /api/*  ──► Autumn FastAPI (mounted sub-app)
                     ├─ /assets ──► Vite build assets
                     └─ /*      ──► index.html (React SPA)
```

Why this differs from the Cloudflare setup: a Space gives you **one container,
one port**, so the Python process serves the SPA itself (see `app.py`). The API
is mounted at `/api`, mirroring the Cloudflare Worker, so the frontend needs no
changes.

## What's in this folder

| File | Purpose |
|------|---------|
| `Dockerfile` | Multi-stage build: compiles the SPA, then serves API + SPA from Python. Build context = repo root. |
| `app.py` | Single-origin ASGI entrypoint (API at `/api`, SPA at `/`, optional token auth). |
| `space_card.md` | The Space's root `README.md` (HF reads `sdk`, `app_port`, etc. from its YAML). |
| `deploy.sh` | One-command push to an HF Space (stages root files on a throwaway branch). |

## Cost / limits

- **Free CPU Basic** Space: 2 vCPU / 16 GB, $0. Sleeps after ~48h idle, wakes on visit.
- Storage is **ephemeral** on the free tier — the memory SQLite file resets on
  rebuild/restart. Fine for a demo; add HF persistent storage if you need it kept.
- **No API keys are baked into the image.** Each user pastes their own model
  key in the UI (Settings → Apply), so sharing the Space URL is safe.

## Deploy

### 1. Create the Space

Go to <https://huggingface.co/new-space> → choose **Docker** (blank template) →
create. Note its git URL: `https://huggingface.co/spaces/<user>/<space>`.

### 2a. Push with the script (easiest)

First make git able to authenticate to HF (one-time): create a **write** token
at <https://huggingface.co/settings/tokens>, then:

```bash
git config --global credential.helper store   # cache the token after first use
web/hf/deploy.sh https://huggingface.co/spaces/<user>/<space>
# username = your HF username, password = the write token
```

The script creates a local `hf-deploy` branch, copies `Dockerfile` and
`space_card.md` → `README.md` to the repo root (HF requires both at root),
and force-pushes it to the Space's `main`. Your other branches stay untouched.

### 2b. Push manually

```bash
git checkout -B hf-deploy
cp web/hf/Dockerfile ./Dockerfile
cp web/hf/space_card.md ./README.md
git add Dockerfile README.md && git commit -m "HF Space deploy artifacts"
git remote add hf-space https://huggingface.co/spaces/<user>/<space>
git push -f hf-space hf-deploy:main
git checkout -        # back to your normal branch
```

### 3. Wait for the build

HF builds the Dockerfile (a few minutes: compiles the SPA, installs Python
deps). When it goes green, open the Space URL.

### 4. Configure models

In the app: **Settings** → fill A1 / A2 / A3 with your own API key, base URL,
and model → **Apply**. Start chatting. (A4 memory model is optional.)

## Optional: lock the Space with a token

In the Space's **Settings → Variables and secrets**, add a secret
`AUTUMN_API_TOKEN`. Then in the app's Settings, set the same token. Now every
`/api/*` request must carry it — handy if you don't want strangers using your
Space's compute.

## Troubleshooting

- **Build fails on `npx vite build`** — a frontend dependency or TS issue. Run
  `cd web/frontend && npm install && npm run build` locally to see the full error.
- **App loads but chat returns 503** — you haven't applied a model config yet
  (Settings → Apply), or the key/base URL is wrong.
- **"Frontend assets not found" JSON at `/`** — the build stage didn't produce
  `dist/`; check the build logs for the Vite step.
- **Memory resets** — expected on the free tier (ephemeral storage).

## Local smoke test (optional)

You can run the exact single-origin server locally with Docker:

```bash
# from the repo root
docker build -f web/hf/Dockerfile -t autumn-hf .
docker run --rm -p 7860:7860 autumn-hf
# open http://localhost:7860
```

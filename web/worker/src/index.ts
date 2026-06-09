/**
 * Autumn Web — Cloudflare Worker (BFF + static asset server)
 *
 * Responsibilities:
 *  1. Serve the React SPA from [assets] for all non-API routes.
 *  2. Proxy /api/* → Cloudflare Container (Python autumn.server on :8765).
 *  3. Optional Bearer-token auth (set AUTH_TOKEN secret via wrangler).
 *  4. Pass SSE streams through transparently (no buffering).
 */

import { Container } from "cloudflare:workers";

// ── Container class ───────────────────────────────────────────────────────────

export class AutumnContainer extends Container<Env> {
  /** Port the Python FastAPI server listens on inside the container. */
  defaultPort = 8765;

  /** Sleep the container after 10 min of inactivity to save costs.
   *  Remove or increase for production workloads that must stay warm. */
  sleepAfter = "10m";
}

// ── Env types ─────────────────────────────────────────────────────────────────

interface Env {
  AUTUMN: DurableObjectNamespace<AutumnContainer>;
  ASSETS: Fetcher;
  /** Optional Bearer token. If unset, the API is publicly accessible. */
  AUTH_TOKEN?: string;
}

// ── CORS headers (dev convenience — tighten for production) ───────────────────

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Auth-Token",
  "Access-Control-Max-Age": "86400",
};

function corsResponse(status = 204): Response {
  return new Response(null, { status, headers: CORS_HEADERS });
}

function addCors(response: Response): Response {
  const next = new Response(response.body, response);
  for (const [k, v] of Object.entries(CORS_HEADERS)) next.headers.set(k, v);
  return next;
}

// ── Auth middleware ───────────────────────────────────────────────────────────

function checkAuth(request: Request, env: Env): Response | null {
  if (!env.AUTH_TOKEN) return null; // auth disabled

  const header = request.headers.get("Authorization") ?? "";
  const tokenHeader = request.headers.get("X-Auth-Token") ?? "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : tokenHeader;

  if (token !== env.AUTH_TOKEN) {
    return new Response(JSON.stringify({ error: "Unauthorized" }), {
      status: 401,
      headers: { "Content-Type": "application/json", ...CORS_HEADERS },
    });
  }
  return null;
}

// ── Main fetch handler ────────────────────────────────────────────────────────

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // Preflight
    if (request.method === "OPTIONS") return corsResponse();

    // API proxy — /api/* → Container (python autumn.server)
    if (url.pathname.startsWith("/api/")) {
      const authError = checkAuth(request, env);
      if (authError) return authError;

      // Acquire a container instance (single shared instance named "autumn").
      const id = env.AUTUMN.idFromName("autumn");
      const container = env.AUTUMN.get(id);

      // Strip the /api prefix before forwarding.
      const containerPath = url.pathname.slice(4) || "/";
      const containerUrl = new URL(containerPath, "http://container");
      containerUrl.search = url.search;

      let containerReq: Request;
      if (request.method === "GET" || request.method === "HEAD") {
        containerReq = new Request(containerUrl, {
          method: request.method,
          headers: request.headers,
        });
      } else {
        containerReq = new Request(containerUrl, {
          method: request.method,
          headers: request.headers,
          body: request.body,
          // @ts-expect-error duplex is required for streaming bodies
          duplex: "half",
        });
      }

      try {
        const response = await container.fetch(containerReq);
        return addCors(response);
      } catch (err) {
        return new Response(
          JSON.stringify({ error: String(err) }),
          {
            status: 502,
            headers: { "Content-Type": "application/json", ...CORS_HEADERS },
          }
        );
      }
    }

    // Serve the React SPA for everything else (client-side routing).
    return env.ASSETS.fetch(request);
  },
};

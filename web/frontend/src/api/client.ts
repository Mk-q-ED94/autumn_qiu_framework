/**
 * Autumn API client — wraps all endpoints and handles SSE streaming.
 *
 * The `baseUrl` and `authToken` are read from the app settings at call time
 * so hot-reloading settings (e.g. pasting a new token) takes effect immediately.
 */

import type {
  IntentPreview,
  MemoryArea,
  MemoryEntry,
  MissionRoute,
  Protocol,
  Settings,
  SlotConfig,
  StreamEvent,
  Terr,
  WorkflowTrace,
} from "../types";

// ── helpers ───────────────────────────────────────────────────────────────────

function headers(settings: Settings): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  if (settings.authToken) h["Authorization"] = `Bearer ${settings.authToken}`;
  return h;
}

function url(settings: Settings, path: string): string {
  const base = settings.serverUrl.replace(/\/$/, "");
  return `${base}${path}`;
}

async function json<T>(
  settings: Settings,
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(url(settings, path), {
    headers: headers(settings),
    ...options,
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

// ── /health ───────────────────────────────────────────────────────────────────

export async function getHealth(settings: Settings): Promise<{
  status: string;
  configured: boolean;
  last_error?: string;
}> {
  return json(settings, "/health");
}

// ── /models ───────────────────────────────────────────────────────────────────

export async function getModels(
  settings: Settings,
  slot: SlotConfig
): Promise<string[]> {
  const res = await json<{ models: string[] }>(settings, "/models", {
    method: "POST",
    body: JSON.stringify({
      api_key: slot.api_key,
      base_url: slot.base_url,
      protocol: slot.protocol,
    }),
  });
  return res.models;
}

// ── /config/apply ─────────────────────────────────────────────────────────────

export async function applyConfig(
  settings: Settings
): Promise<{ status: string; configured: boolean }> {
  const body: Record<string, unknown> = {
    a1: settings.a1,
    a2: settings.a2,
    a3: settings.a3,
  };
  if (settings.a4?.api_key) body.a4 = settings.a4;
  return json(settings, "/config/apply", { method: "POST", body: JSON.stringify(body) });
}

// ── /intent ───────────────────────────────────────────────────────────────────

export async function classifyIntent(
  settings: Settings,
  input: string,
  route?: MissionRoute | "auto"
): Promise<IntentPreview> {
  return json(settings, "/intent", {
    method: "POST",
    body: JSON.stringify({ input, route: route ?? null }),
  });
}

// ── /trace ────────────────────────────────────────────────────────────────────

export async function runTrace(
  settings: Settings,
  input: string,
  route?: MissionRoute | "auto",
  projectInstructions?: string
): Promise<WorkflowTrace> {
  return json(settings, "/trace", {
    method: "POST",
    body: JSON.stringify({
      input,
      route: route ?? null,
      project_instructions: projectInstructions ?? null,
    }),
  });
}

// ── /stream (SSE) ─────────────────────────────────────────────────────────────

/**
 * Returns an async generator that yields SSE events from the server.
 * Handles ping comments, [DONE], error events, and graceful abort.
 *
 * Usage:
 *   for await (const event of streamChat(settings, "hello")) {
 *     if ('chunk' in event) appendText(event.chunk);
 *     else if ('trace' in event) setTrace(event.trace);
 *   }
 */
export async function* streamChat(
  settings: Settings,
  input: string,
  route?: MissionRoute | "auto",
  projectInstructions?: string,
  signal?: AbortSignal
): AsyncGenerator<StreamEvent> {
  const params = new URLSearchParams({ input });
  if (route) params.set("route", route);
  if (projectInstructions) params.set("project_instructions", projectInstructions);

  const res = await fetch(`${url(settings, "/stream")}?${params}`, {
    headers: headers(settings),
    signal,
  });

  if (!res.ok || !res.body) {
    throw new Error(`Stream failed: HTTP ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const data = line.slice(6).trim();
        if (data === "[DONE]") return;
        if (!data) continue;
        try {
          yield JSON.parse(data) as StreamEvent;
        } catch {
          // malformed event — skip
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}

// ── /terrs ────────────────────────────────────────────────────────────────────

export async function getTerrs(settings: Settings): Promise<Terr[]> {
  return json(settings, "/terrs");
}

export async function setTerrEnabled(
  settings: Settings,
  name: string,
  enabled: boolean
): Promise<Terr> {
  return json(settings, `/terrs/${encodeURIComponent(name)}`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
}

// ── /memory ───────────────────────────────────────────────────────────────────

export async function getMemoryHistory(
  settings: Settings,
  area: MemoryArea,
  limit = 200,
  offset = 0
): Promise<MemoryEntry[]> {
  return json(
    settings,
    `/memory/${area}/history?limit=${limit}&offset=${offset}`
  );
}

// ── /session/end ──────────────────────────────────────────────────────────────

export async function endSession(settings: Settings): Promise<void> {
  await json(settings, "/session/end", { method: "POST" });
}

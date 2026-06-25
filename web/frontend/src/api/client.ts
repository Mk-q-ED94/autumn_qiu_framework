/**
 * Autumn API client — wraps all endpoints and handles SSE streaming.
 *
 * The `baseUrl` and `authToken` are read from the app settings at call time
 * so hot-reloading settings (e.g. pasting a new token) takes effect immediately.
 */

import type {
  AccessLog,
  AnnotateResult,
  AutoAnnotateResult,
  CodebaseMemoryStatus,
  CooperativeBehavior,
  FourDStatus,
  IntentPreview,
  MemoryArea,
  MemoryEntry,
  MissionRoute,
  OllamaModel,
  OllamaPullEvent,
  OllamaRecommended,
  OllamaStatus,
  Protocol,
  PushPreview,
  Settings,
  SlotConfig,
  StreamEvent,
  Terr,
  WorkflowTrace,
} from "../types";

// ── errors ──────────────────────────────────────────────────────────────────

/**
 * A typed HTTP failure. `status` is the response code (0 for network/transport
 * errors); `detail` is the server's `{detail}` string when present. `message`
 * is a human-facing, status-aware explanation the UI can show directly.
 */
export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(friendlyMessage(status, detail));
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function parseDetail(body: string): string {
  try {
    const j = JSON.parse(body);
    return typeof j?.detail === "string" ? j.detail : body;
  } catch {
    return body;
  }
}

function friendlyMessage(status: number, detail: string): string {
  switch (status) {
    case 401:
      return "未授权：请在「设置 · 服务器」中填写正确的 Auth Token。";
    case 413:
      return "输入过大：内容超出服务器请求上限，请缩短后重试。";
    case 502:
      return `上游模型出错：${detail || "请稍后重试"}`;
    case 503:
      return "服务尚未配置模型：请在「设置 · 模型」中配置 A1–A3 后重试。";
    default:
      return detail ? `HTTP ${status}: ${detail}` : `请求失败（HTTP ${status}）`;
  }
}

async function failure(res: Response): Promise<ApiError> {
  const body = await res.text().catch(() => "");
  return new ApiError(res.status, parseDetail(body));
}

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
    throw await failure(res);
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
  settings: Settings,
  behavior?: CooperativeBehavior
): Promise<{ status: string; configured: boolean }> {
  const body: Record<string, unknown> = {
    a1: settings.a1,
    a2: settings.a2,
    a3: settings.a3,
  };
  if (settings.a4?.api_key) body.a4 = settings.a4;
  if (behavior) body.behavior = behavior;
  return json(settings, "/config/apply", { method: "POST", body: JSON.stringify(body) });
}

// ── /config/codebase-memory ───────────────────────────────────────────────────

export async function getCodebaseMemoryStatus(
  settings: Settings
): Promise<CodebaseMemoryStatus> {
  return json(settings, "/config/codebase-memory");
}

export async function setCodebaseMemory(
  settings: Settings,
  enabled: boolean,
  repo?: string
): Promise<CodebaseMemoryStatus> {
  return json(settings, "/config/codebase-memory", {
    method: "POST",
    body: JSON.stringify({ enabled, repo: repo ?? null }),
  });
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

  if (!res.ok) throw await failure(res);
  if (!res.body) throw new ApiError(0, "stream has no body");

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

// ── /memory/4d (runtime flags) ────────────────────────────────────────────────

export async function getFourDStatus(settings: Settings): Promise<FourDStatus> {
  return json(settings, "/memory/4d/status");
}

export async function setFourDConfig(
  settings: Settings,
  patch: Partial<FourDStatus>
): Promise<FourDStatus> {
  return json(settings, "/memory/4d/config", {
    method: "POST",
    body: JSON.stringify(patch),
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

// ── /memory/push/preview ──────────────────────────────────────────────────────

export async function pushPreview(
  settings: Settings,
  area: MemoryArea = "mom1",
  query = "",
  cues?: string[]
): Promise<PushPreview> {
  return json(settings, "/memory/push/preview", {
    method: "POST",
    body: JSON.stringify({ area, query, cues: cues ?? null }),
  });
}

// ── /memory/audit/access_log ──────────────────────────────────────────────────

export async function getAccessLog(
  settings: Settings,
  limit = 200,
  offset = 0,
  verdict?: "granted" | "denied"
): Promise<AccessLog> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (verdict) params.set("verdict", verdict);
  return json(settings, `/memory/audit/access_log?${params}`);
}

// ── /memory/{area} A4 cognitive ops ───────────────────────────────────────────

export async function annotateMemory(
  settings: Settings,
  area: MemoryArea,
  req: {
    entry_id: string;
    mode?: string;
    intent?: string;
    goal_ref?: string;
    scope?: string[];
    cues?: string[];
    half_life?: number;
  }
): Promise<AnnotateResult> {
  return json(settings, `/memory/${area}/annotate`, {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function autoAnnotate(
  settings: Settings,
  area: MemoryArea,
  body: { n?: number; only_unannotated?: boolean } = {}
): Promise<AutoAnnotateResult> {
  return json(settings, `/memory/${area}/auto-annotate`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function consolidateMemory(
  settings: Settings,
  area: MemoryArea,
  body: { keep_recent?: number; min_candidates?: number } = {}
): Promise<Record<string, unknown>> {
  return json(settings, `/memory/${area}/consolidate`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function extractFacts(
  settings: Settings,
  area: MemoryArea,
  body: { keep_recent?: number; max_facts?: number } = {}
): Promise<Record<string, unknown>> {
  return json(settings, `/memory/${area}/extract-facts`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function evolveMemory(
  settings: Settings,
  area: MemoryArea,
  body: { min_count?: number; min_cluster?: number; max_skills?: number } = {}
): Promise<Record<string, unknown>> {
  return json(settings, `/memory/${area}/evolve`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getProfile(
  settings: Settings,
  area: MemoryArea
): Promise<Record<string, unknown>> {
  return json(settings, `/memory/${area}/profile`);
}

// ── /session/end ──────────────────────────────────────────────────────────────

export async function endSession(settings: Settings): Promise<void> {
  await json(settings, "/session/end", { method: "POST" });
}

// ── /ollama (local model management) ────────────────────────────────────────────

export async function ollamaStatus(
  settings: Settings,
  baseUrl: string
): Promise<OllamaStatus> {
  return json(settings, "/ollama/status", {
    method: "POST",
    body: JSON.stringify({ base_url: baseUrl }),
  });
}

export async function ollamaModels(
  settings: Settings,
  baseUrl: string
): Promise<OllamaModel[]> {
  const res = await json<{ models: OllamaModel[] }>(settings, "/ollama/models", {
    method: "POST",
    body: JSON.stringify({ base_url: baseUrl }),
  });
  return res.models;
}

export async function ollamaRecommended(
  settings: Settings
): Promise<OllamaRecommended[]> {
  const res = await json<{ models: OllamaRecommended[] }>(
    settings,
    "/ollama/recommended"
  );
  return res.models;
}

export async function ollamaDelete(
  settings: Settings,
  baseUrl: string,
  name: string
): Promise<void> {
  await json(settings, "/ollama/models", {
    method: "DELETE",
    body: JSON.stringify({ base_url: baseUrl, name }),
  });
}

/**
 * Streams `ollama pull` progress as it downloads. Yields each NDJSON progress
 * object, or a final `{ error }`. Mirrors the SSE shape of `streamChat`.
 */
export async function* streamOllamaPull(
  settings: Settings,
  baseUrl: string,
  name: string,
  signal?: AbortSignal
): AsyncGenerator<OllamaPullEvent> {
  const params = new URLSearchParams({ name, base_url: baseUrl });
  const res = await fetch(`${url(settings, "/ollama/pull")}?${params}`, {
    headers: headers(settings),
    signal,
  });
  if (!res.ok) throw await failure(res);
  if (!res.body) throw new ApiError(0, "stream has no body");

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
          yield JSON.parse(data) as OllamaPullEvent;
        } catch {
          // malformed event — skip
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
}

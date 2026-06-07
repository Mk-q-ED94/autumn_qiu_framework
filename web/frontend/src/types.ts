// ── Workflow trace types (mirrors autumn/core/types.py + server schema) ────────

export type WorkspaceId = "WP1" | "WP2" | "WP3";
export type StageStatus = "pending" | "active" | "completed" | "failed";
export type StageKind = "stage" | "tool" | "agent";

export interface WorkflowStage {
  id: string;
  title: string;
  detail: string;
  workspace: WorkspaceId;
  status: StageStatus;
  kind: StageKind;
  duration_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  source_terr?: string;
}

export interface WorkflowTrace {
  output: string;
  input_type: InputType;
  route?: MissionRoute;
  task_type?: string;
  stages: WorkflowStage[];
  total_prompt_tokens?: number;
  total_completion_tokens?: number;
}

// ── Routing + intent ──────────────────────────────────────────────────────────

export type InputType = "task" | "mission";
export type MissionRoute = "direct" | "convert" | "auto";

export interface IntentPreview {
  input_type: InputType;
  task_type?: string;
  route?: MissionRoute;
  confidence: number;
  reasoning?: string;
}

// ── SSE stream events ─────────────────────────────────────────────────────────

export type StreamEvent =
  | { chunk: string }
  | { trace: WorkflowTrace }
  | { error: string };

// ── Terr (capability domain) ──────────────────────────────────────────────────

export interface TerrCallable {
  name: string;
  description: string;
  parameters: Array<{ name: string; type: string; description: string; required: boolean }>;
}

export interface Terr {
  name: string;
  description: string;
  enabled: boolean;
  tools: TerrCallable[];
  skills: TerrCallable[];
  mcps: Array<{ name: string; description: string }>;
}

// ── Memory ────────────────────────────────────────────────────────────────────

export type MemoryArea = "mom1" | "mom2" | "mom3";
export type MemoryEntry = unknown; // raw from backend

// ── Server config ─────────────────────────────────────────────────────────────

export type Protocol = "openai" | "anthropic";

export interface SlotConfig {
  api_key: string;
  base_url: string;
  model: string;
  protocol: Protocol;
}

// ── Ollama (local model) management ─────────────────────────────────────────────

/** A model already installed in the local Ollama daemon. */
export interface OllamaModel {
  name: string;
  size?: number;
  parameter_size?: string;
  family?: string;
  modified_at?: string;
}

/** A curated model the user can pull with one click. */
export interface OllamaRecommended {
  name: string;
  label: string;
  size: string;
  note: string;
  recommended: boolean;
}

export interface OllamaStatus {
  running: boolean;
  base_url: string;
  version?: string;
  error?: string;
}

/** One NDJSON progress line from `ollama pull`, or a terminal error. */
export type OllamaPullEvent =
  | { status: string; digest?: string; total?: number; completed?: number }
  | { error: string };

/** Default endpoint of a local Ollama daemon (its OpenAI-compat base, no /v1). */
export const DEFAULT_OLLAMA_URL = "http://localhost:11434";

export interface Settings {
  /** URL of the Autumn server (the /api proxy prefix or direct). */
  serverUrl: string;
  /** Bearer token for the Worker auth middleware. */
  authToken: string;
  a1: SlotConfig;
  a2: SlotConfig;
  a3: SlotConfig;
  a4?: SlotConfig;
}

export const DEFAULT_SLOT: SlotConfig = {
  api_key: "",
  base_url: "https://api.openai.com",
  model: "",
  protocol: "openai",
};

export const DEFAULT_SETTINGS: Settings = {
  serverUrl: "/api",
  authToken: "",
  a1: { ...DEFAULT_SLOT },
  a2: { ...DEFAULT_SLOT },
  a3: { ...DEFAULT_SLOT },
};

// ── Messages + Conversations ──────────────────────────────────────────────────

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  trace?: WorkflowTrace;
  isStreaming?: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  messages: Message[];
}

// ── Health ────────────────────────────────────────────────────────────────────

export interface HealthStatus {
  status: "ok" | "error" | "unchecked";
  configured: boolean;
  last_error?: string;
}

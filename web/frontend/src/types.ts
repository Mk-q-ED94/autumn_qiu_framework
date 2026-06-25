// ── Workflow trace types (mirrors autumn/core/types.py + server schema) ────────

export type WorkspaceId = "WP1" | "WP2" | "WP3" | "WP4";
export type StageStatus = "pending" | "active" | "completed" | "failed";
export type StageKind = "stage" | "tool" | "agent" | "push";

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
  cost_usd?: number;
}

export interface WorkflowTrace {
  output: string;
  input_type: InputType;
  route?: MissionRoute;
  task_type?: string;
  stages: WorkflowStage[];
  total_prompt_tokens?: number;
  total_completion_tokens?: number;
  total_cost_usd?: number;
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

export type MemoryArea = "mom1" | "mom2" | "mom3" | "shared";
export type MemoryEntry = unknown; // raw from backend

/** Runtime 4D-memory flags (GET /memory/4d/status, POST /memory/4d/config). */
export interface FourDStatus {
  fourd_memory_enabled: boolean;
  fourd_push_on_turn: boolean;
  mom1_access_enabled: boolean;
}

/** One push-activated memory in a dry-run preview (POST /memory/push/preview). */
export interface PushPreviewEntry {
  id: string;
  text: string;
  mode: string;
  intent: string;
  cues: string[];
  score: number;
}

export interface PushPreview {
  fired: PushPreviewEntry[];
  fragment: string;
  /** Whether push is actually active on live turns (vs. just previewable). */
  enabled: boolean;
}

/** State of the codebase-memory token-saving layer (GET/POST /config/codebase-memory). */
export interface CodebaseMemoryStatus {
  enabled: boolean;
  connected: boolean;
  indexed: boolean;
  repo: string;
  tool_count: number;
  error?: string | null;
}

/** One adjudicated Mom1 access request (GET /memory/audit/access_log). */
export interface AccessLogEntry {
  id: string;
  timestamp: number;
  action: string;
  requester: string;
  query: string;
  reason: string;
  decision_reason: string;
  redact: boolean;
  entry_ids: string[];
  mediated_by?: string | null;
}

export interface AccessLog {
  entries: AccessLogEntry[];
  total: number;
}

/** Cooperative-workflow toggles for POST /config/apply (all optional). */
export interface CooperativeBehavior {
  cooperative_workflow?: boolean;
  a1_task_planning?: boolean;
  a1_supervision?: boolean;
  archive_executions?: boolean;
  a4_delegate_to_a1?: boolean;
  a4_knowledge_terr?: boolean;
}

export interface AnnotateResult {
  status: string;
  entry_id: string;
  found: boolean;
}

export interface AutoAnnotateResult {
  status: string;
  annotated: number;
  scanned: number;
}

// ── Server config ─────────────────────────────────────────────────────────────

export type Protocol = "openai" | "anthropic";

export interface SlotConfig {
  api_key: string;
  base_url: string;
  model: string;
  protocol: Protocol;
  /** Optional USD price per 1M tokens — enables per-turn cost in the trace. */
  input_price_per_1m?: number;
  output_price_per_1m?: number;
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

export interface ServerMetrics {
  runs: number;
  errors: number;
  prompt_tokens: number;
  completion_tokens: number;
  uptime_seconds: number;
}

import { useState } from "react";
import type { WorkflowStage, WorkflowTrace, WorkspaceId } from "../types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function workspaceClass(ws: WorkspaceId | string): string {
  if (ws === "WP1") return "wp1";
  if (ws === "WP2") return "wp2";
  if (ws === "WP3") return "wp3";
  return "wp1";
}

function statusClass(status: string): string {
  if (status === "completed") return "completed";
  if (status === "active") return "active";
  if (status === "failed") return "failed";
  return "pending";
}

function fmtMs(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

function fmtTok(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function fmtCost(usd: number): string {
  // Sub-cent costs are common — show enough precision to be meaningful.
  if (usd >= 1) return `$${usd.toFixed(2)}`;
  if (usd >= 0.01) return `$${usd.toFixed(3)}`;
  return `$${usd.toFixed(5)}`;
}

function stageTooltip(stage: WorkflowStage): string {
  const parts = [`${stage.workspace} · ${stage.title}`];
  if (stage.duration_ms !== undefined) parts.push(fmtMs(stage.duration_ms));
  if (stage.prompt_tokens !== undefined && stage.completion_tokens !== undefined) {
    parts.push(`↑${fmtTok(stage.prompt_tokens)} ↓${fmtTok(stage.completion_tokens)}`);
  }
  if (stage.cost_usd !== undefined && stage.cost_usd !== null) parts.push(fmtCost(stage.cost_usd));
  if (stage.source_terr) parts.push(`Terr: ${stage.source_terr}`);
  return parts.join(" · ");
}

function routeLabel(trace: WorkflowTrace): string {
  if (trace.input_type === "task") return "Task";
  if (trace.route === "direct") return "Mission · Direct";
  if (trace.route === "convert") return "Mission → Task";
  return trace.input_type;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StageCapsule({ stage }: { stage: WorkflowStage }) {
  const ws = workspaceClass(stage.workspace);
  const st = statusClass(stage.status);
  const isTool = stage.kind === "tool";
  const isAgent = stage.kind === "agent";

  return (
    <div
      className={`stage-capsule ${ws} ${st}`}
      title={stageTooltip(stage)}
    >
      {isAgent ? "◉" : isTool ? "⬡" : "●"}{" "}
      {stage.title}
      {stage.source_terr && (
        <span className="badge badge--info" style={{ marginLeft: 3, fontSize: 8 }}>
          {stage.source_terr}
        </span>
      )}
    </div>
  );
}

function ToolCountChip({ count }: { count: number }) {
  return <div className="tool-chip">🔧 {count}</div>;
}

function AgentChip() {
  return <div className="agent-chip">◉ Agent</div>;
}

// ── Expanded trace rows ───────────────────────────────────────────────────────

function TraceRow({ stage, isLast }: { stage: WorkflowStage; isLast: boolean }) {
  const ws = workspaceClass(stage.workspace);
  const isTool = stage.kind === "tool";
  const isAgent = stage.kind === "agent";

  return (
    <div className="trace-stage-row">
      <div className={`trace-stage-indicator ${isTool ? "tool" : isAgent ? "agent" : ws}`}>
        {isAgent ? "◉" : isTool ? "⬡" : "●"}
      </div>
      <div className="trace-stage-body">
        <div className="trace-stage-title">
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}>{stage.title}</span>
          {stage.source_terr && (
            <span className="badge badge--info" style={{ fontSize: 9 }}>
              Terr · {stage.source_terr}
            </span>
          )}
          {!isLast && <span className="trace-stage-ms">
            {stage.duration_ms !== undefined && fmtMs(stage.duration_ms)}
          </span>}
        </div>
        <div className="trace-stage-detail">{stage.detail}</div>
        {(stage.prompt_tokens !== undefined || stage.completion_tokens !== undefined) && (
          <div style={{ fontSize: 10, color: "var(--text-3)", fontFamily: "var(--font-mono)", marginTop: 2 }}>
            {stage.prompt_tokens !== undefined && `↑${fmtTok(stage.prompt_tokens)}`}
            {" "}
            {stage.completion_tokens !== undefined && `↓${fmtTok(stage.completion_tokens)}`}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function PipelineStrip({ trace }: { trace: WorkflowTrace }) {
  const [expanded, setExpanded] = useState(false);

  // Filter out tool/agent stages for the main strip — aggregate them into chips.
  const mainStages = trace.stages.filter((s) => s.kind === "stage");
  const toolCount = trace.stages.filter((s) => s.kind === "tool").length;
  const agentCount = trace.stages.filter((s) => s.kind === "agent").length;

  const totalMs = trace.stages.reduce((acc, s) => acc + (s.duration_ms ?? 0), 0);

  const tokenSummary =
    trace.total_prompt_tokens !== undefined && trace.total_completion_tokens !== undefined
      ? `↑${fmtTok(trace.total_prompt_tokens)} ↓${fmtTok(trace.total_completion_tokens)}`
      : null;

  const costSummary =
    trace.total_cost_usd !== undefined && trace.total_cost_usd !== null
      ? fmtCost(trace.total_cost_usd)
      : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
      {/* Strip row */}
      <div className="pipeline-strip">
        {mainStages.map((stage, i) => (
          <div key={stage.id} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            {i > 0 && <div className="stage-connector" />}
            <StageCapsule stage={stage} />
          </div>
        ))}
        {agentCount > 0 && (
          <>
            <div className="stage-connector" />
            <AgentChip />
          </>
        )}
        {toolCount > 0 && <ToolCountChip count={toolCount} />}

        {/* Summary + expand toggle */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginLeft: "auto" }}>
          {tokenSummary && (
            <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-3)" }}>
              {tokenSummary}
            </span>
          )}
          {costSummary && (
            <span
              className="trace-cost"
              title="本轮预估费用（按已配置的模型单价）"
              style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--success)" }}
            >
              {costSummary}
            </span>
          )}
          {totalMs > 0 && (
            <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-3)" }}>
              {fmtMs(totalMs)}
            </span>
          )}
          <button
            className="pipeline-expand-btn"
            onClick={() => setExpanded((e) => !e)}
            title={expanded ? "收起 trace" : "展开 trace"}
          >
            <span
              style={{ display: "inline-block", transition: "transform 0.15s", transform: expanded ? "rotate(180deg)" : "rotate(0deg)" }}
            >
              ▾
            </span>
          </button>
        </div>
      </div>

      {/* Expanded trace detail */}
      {expanded && (
        <div className="trace-detail">
          <div className="trace-header">
            <span className="badge badge--neutral" style={{ fontSize: 10 }}>
              {routeLabel(trace)}
            </span>
            {tokenSummary && <span className="trace-tokens">{tokenSummary}</span>}
            {costSummary && (
              <span className="trace-cost" style={{ marginLeft: 4, color: "var(--success)" }}>
                {costSummary}
              </span>
            )}
            {totalMs > 0 && (
              <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-3)", marginLeft: 4 }}>
                {fmtMs(totalMs)}
              </span>
            )}
          </div>
          <div className="trace-stages">
            {trace.stages.map((stage, i) => (
              <TraceRow key={`${stage.id}-${i}`} stage={stage} isLast={i === trace.stages.length - 1} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

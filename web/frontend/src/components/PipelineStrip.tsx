import { useState } from "react";
import type { WorkflowStage, WorkflowTrace, WorkspaceId } from "../types";

// ── Helpers ───────────────────────────────────────────────────────────────────

function workspaceClass(ws: WorkspaceId | string): string {
  if (ws === "WP1") return "wp1";
  if (ws === "WP2") return "wp2";
  if (ws === "WP3") return "wp3";
  if (ws === "WP4") return "wp4";
  return "wp1";
}

// One glyph per stage. Keyed on kind first, then on the WP1 stage id so the
// 0.3.0 planning / supervision stages read distinctly from a plain step.
function stageGlyph(stage: WorkflowStage): string {
  if (stage.kind === "push") return "✦";   // 4D memory push-injection
  if (stage.kind === "agent") return "◉";
  if (stage.kind === "tool") return "⬡";
  if (stage.id.startsWith("wp1.plan")) return "❖";       // A1 制定计划
  if (stage.id.includes("supervise")) return "⊙";        // A1 监督介入
  return "●";
}

// The class on the round trace-row indicator: tool/agent/push get their own,
// everything else colors by workspace.
function indicatorClass(stage: WorkflowStage): string {
  if (stage.kind === "tool") return "tool";
  if (stage.kind === "agent") return "agent";
  if (stage.kind === "push") return "push";
  return workspaceClass(stage.workspace);
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

  return (
    <div
      className={`stage-capsule ${ws} ${st}`}
      title={stageTooltip(stage)}
    >
      {stageGlyph(stage)}{" "}
      {stage.title}
      {stage.source_terr && (
        <span className="badge badge--info pipeline-source-badge">
          {stage.source_terr}
        </span>
      )}
    </div>
  );
}

function ToolCountChip({ count }: { count: number }) {
  return <div className="tool-chip">Tool · {count}</div>;
}

function AgentChip() {
  return <div className="agent-chip">◉ Agent</div>;
}

// ── Expanded trace rows ───────────────────────────────────────────────────────

function TraceRow({ stage, isLast }: { stage: WorkflowStage; isLast: boolean }) {
  return (
    <div className="trace-stage-row">
      <div className={`trace-stage-indicator ${indicatorClass(stage)}`}>
        {stageGlyph(stage)}
      </div>
      <div className="trace-stage-body">
        <div className="trace-stage-title">
          <span className="trace-stage-name">{stage.title}</span>
          {stage.source_terr && (
            <span className="badge badge--info trace-source-badge">
              Terr · {stage.source_terr}
            </span>
          )}
          {!isLast && <span className="trace-stage-ms">
            {stage.duration_ms !== undefined && fmtMs(stage.duration_ms)}
          </span>}
        </div>
        <div className="trace-stage-detail">{stage.detail}</div>
        {(stage.prompt_tokens !== undefined || stage.completion_tokens !== undefined) && (
          <div className="trace-stage-metrics">
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

  // Main strip shows workflow steps + the 4D push stage; tool/agent calls are
  // aggregated into chips so a long ReAct loop doesn't blow out the strip.
  const mainStages = trace.stages.filter((s) => s.kind === "stage" || s.kind === "push");
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
    <div className="pipeline-stack">
      {/* Strip row */}
      <div className="pipeline-strip">
        {mainStages.map((stage, i) => (
          <div key={stage.id} className="pipeline-stage-wrap">
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
        <div className="pipeline-summary">
          {tokenSummary && (
            <span className="pipeline-metric">
              {tokenSummary}
            </span>
          )}
          {costSummary && (
            <span
              title="本轮预估费用（按已配置的模型单价）"
              className="pipeline-metric pipeline-metric--cost"
            >
              {costSummary}
            </span>
          )}
          {totalMs > 0 && (
            <span className="pipeline-metric">
              {fmtMs(totalMs)}
            </span>
          )}
          <button
            className="pipeline-expand-btn"
            onClick={() => setExpanded((e) => !e)}
            title={expanded ? "收起 trace" : "展开 trace"}
          >
            <span className={`pipeline-chevron${expanded ? " expanded" : ""}`}>
              ▾
            </span>
          </button>
        </div>
      </div>

      {/* Expanded trace detail */}
      {expanded && (
        <div className="trace-detail">
          <div className="trace-header">
            <span className="badge badge--neutral trace-route-badge">
              {routeLabel(trace)}
            </span>
            {tokenSummary && <span className="trace-tokens">{tokenSummary}</span>}
            {costSummary && (
              <span className="trace-cost trace-header-cost">
                {costSummary}
              </span>
            )}
            {totalMs > 0 && (
              <span className="trace-header-duration">
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

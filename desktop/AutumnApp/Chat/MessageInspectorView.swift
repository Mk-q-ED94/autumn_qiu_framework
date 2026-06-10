import SwiftUI

/// Right-rail inspector that surfaces the trace of the most recent assistant
/// message in detail, without clobbering the chat scroll with deeply expanded
/// trace cards.
///
/// Sections (top → bottom):
///   - Header: route pill + token totals + duration
///   - Per-workspace token breakdown (WP1 / WP2 / WP3)
///   - Stage list (reuses WorkflowStageRow rendering)
///   - Tool calls section (if any)
///
/// Auto-tracks the latest assistant message; an empty state appears when the
/// conversation has no assistant turn yet.
struct MessageInspectorView: View {
    let trace: WorkflowTrace?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if let trace {
                ScrollView {
                    VStack(alignment: .leading, spacing: Autumn.spacing.lg) {
                        headerSection(trace)
                        breakdownSection(trace)
                        if hasAgentActivity(trace) {
                            agentSection(trace)
                        }
                        stagesSection(trace)
                        if hasToolCalls(trace) {
                            toolsSection(trace)
                        }
                    }
                    .padding(Autumn.spacing.lg)
                }
            } else {
                emptyState
            }
        }
        .background(.regularMaterial)
    }

    // ── header ────────────────────────────────────────────────────────────────

    @ViewBuilder
    private func headerSection(_ trace: WorkflowTrace) -> some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
            Text("流水线详情")
                .font(Autumn.typography.captionStrong)
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
                .tracking(0.5)

            HStack(spacing: Autumn.spacing.sm) {
                routePill(trace)
                Spacer()
                if let total = trace.totalDurationMS {
                    Text(Autumn.format.duration(total))
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundStyle(.secondary)
                }
            }

            if let totalPrompt = trace.totalPromptTokens,
               let totalCompletion = trace.totalCompletionTokens {
                HStack(spacing: Autumn.spacing.md) {
                    tokenStat(label: "输入", value: totalPrompt, icon: "arrow.up")
                    tokenStat(label: "输出", value: totalCompletion, icon: "arrow.down")
                    tokenStat(label: "合计", value: totalPrompt + totalCompletion, icon: "sum")
                }
            }

            if let cost = trace.totalCostUsd, cost > 0 {
                Text(Autumn.format.cost(cost))
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func routePill(_ trace: WorkflowTrace) -> some View {
        let color: Color = trace.inputKind == .task ? Autumn.colors.warning : Autumn.colors.info
        let text: String = {
            switch trace.inputKind {
            case .task:
                if let kind = trace.taskKind, kind != .general { return "Task · \(kind.title)" }
                return "Task"
            case .mission:
                return "Mission · \((trace.routeMode ?? .auto).title)"
            }
        }()
        return AutumnChip(text, icon: trace.inputKind.icon, color: color)
    }

    private func tokenStat(label: String, value: Int, icon: String) -> some View {
        HStack(spacing: 4) {
            Image(systemName: icon)
                .font(.system(size: 9, weight: .bold))
                .foregroundStyle(.tertiary)
            VStack(alignment: .leading, spacing: 0) {
                Text(label)
                    .font(.system(size: 9))
                    .foregroundStyle(.tertiary)
                Text(Autumn.format.tokens(value))
                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                    .foregroundStyle(.primary)
            }
        }
    }

    // ── per-workspace breakdown ───────────────────────────────────────────────

    @ViewBuilder
    private func breakdownSection(_ trace: WorkflowTrace) -> some View {
        let buckets = workspaceBuckets(trace)
        if !buckets.isEmpty {
            VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                Text("按工作区拆分")
                    .font(Autumn.typography.captionStrong)
                    .foregroundStyle(.secondary)
                    .textCase(.uppercase)
                    .tracking(0.5)

                VStack(spacing: Autumn.spacing.xs) {
                    ForEach(buckets, id: \.workspace) { bucket in
                        WorkspaceTokenRow(bucket: bucket)
                    }
                }
            }
        }
    }

    private func workspaceBuckets(_ trace: WorkflowTrace) -> [WorkspaceBucket] {
        var byWorkspace: [String: WorkspaceBucket] = [:]
        for stage in trace.stages where stage.kind != "tool" {
            let key = stage.workspace
            var current = byWorkspace[key] ?? WorkspaceBucket(workspace: key)
            current.stageCount += 1
            current.promptTokens += stage.promptTokens ?? 0
            current.completionTokens += stage.completionTokens ?? 0
            current.durationMS += stage.durationMS ?? 0
            byWorkspace[key] = current
        }
        let order = ["WP1", "WP2", "WP3"]
        return byWorkspace.values.sorted { a, b in
            (order.firstIndex(of: a.workspace) ?? 99) < (order.firstIndex(of: b.workspace) ?? 99)
        }
    }

    // ── agent status ────────────────────────────────────────────────────────────

    @ViewBuilder
    private func agentSection(_ trace: WorkflowTrace) -> some View {
        let agents = trace.stages.filter { $0.kind == "agent" }
        VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
            HStack(spacing: 4) {
                Image(systemName: "cpu")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundStyle(Autumn.colors.warning)
                Text("Agent 状态")
                    .font(Autumn.typography.captionStrong)
                    .foregroundStyle(.secondary)
                    .textCase(.uppercase)
                    .tracking(0.5)
            }

            ForEach(agents) { agent in
                VStack(alignment: .leading, spacing: 3) {
                    HStack(spacing: Autumn.spacing.xs) {
                        Text(agent.title)
                            .font(.system(.caption, design: .monospaced).weight(.semibold))
                        AutumnBadge(agent.status == "completed" ? "完成" : "运行中",
                                    tone: agent.status == "completed" ? .success : .warning)
                        if let sourceTerr = agent.sourceTerr {
                            AutumnBadge("Terr · \(sourceTerr)", icon: "square.stack.3d.up.fill", tone: .info)
                        }
                        Spacer()
                        if let ms = agent.durationMS {
                            Text(Autumn.format.duration(ms))
                                .font(.system(.caption2, design: .monospaced))
                                .foregroundStyle(.tertiary)
                        }
                    }
                    Text(agent.detail)
                        .font(Autumn.typography.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.vertical, 7)
                .padding(.horizontal, 8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                        .fill(Autumn.colors.warning.opacity(0.08))
                )
            }
        }
    }

    // ── stage list ────────────────────────────────────────────────────────────

    @ViewBuilder
    private func stagesSection(_ trace: WorkflowTrace) -> some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
            Text("阶段")
                .font(Autumn.typography.captionStrong)
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
                .tracking(0.5)

            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(trace.stages.enumerated()), id: \.element.id) { index, stage in
                    InspectorStageRow(
                        stage: stage,
                        isLast: index == trace.stages.count - 1
                    )
                }
            }
        }
    }

    // ── tool calls ────────────────────────────────────────────────────────────

    @ViewBuilder
    private func toolsSection(_ trace: WorkflowTrace) -> some View {
        let tools = trace.stages.filter { $0.kind == "tool" }
        VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
            HStack(spacing: 4) {
                Image(systemName: "wrench.and.screwdriver.fill")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundStyle(Autumn.colors.accent)
                Text("工具调用 · \(tools.count)")
                    .font(Autumn.typography.captionStrong)
                    .foregroundStyle(.secondary)
                    .textCase(.uppercase)
                    .tracking(0.5)
            }

            ForEach(tools) { tool in
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: Autumn.spacing.xs) {
                        Text(tool.title)
                            .font(.system(.caption, design: .monospaced).weight(.semibold))
                        if let sourceTerr = tool.sourceTerr {
                            AutumnBadge("Terr · \(sourceTerr)", icon: "square.stack.3d.up.fill", tone: .info)
                        }
                    }
                    Text(tool.detail)
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(.secondary)
                    if let ms = tool.durationMS {
                        Text(Autumn.format.duration(ms))
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.tertiary)
                    }
                }
                .padding(.vertical, 6)
                .padding(.horizontal, 8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(
                    RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                        .fill(Autumn.colors.accent.opacity(0.06))
                )
            }
        }
    }

    private func hasToolCalls(_ trace: WorkflowTrace) -> Bool {
        trace.stages.contains { $0.kind == "tool" }
    }

    private func hasAgentActivity(_ trace: WorkflowTrace) -> Bool {
        trace.stages.contains { $0.kind == "agent" }
    }

    // ── empty ─────────────────────────────────────────────────────────────────

    private var emptyState: some View {
        VStack(spacing: Autumn.spacing.sm) {
            Image(systemName: "point.3.connected.trianglepath.dotted")
                .font(.system(size: 28))
                .foregroundStyle(.tertiary)
            Text("等待第一条回复")
                .font(Autumn.typography.captionMedium)
                .foregroundStyle(.secondary)
            Text("发送消息后，每条 assistant 回复的流水线细节会显示在这里。")
                .font(Autumn.typography.caption)
                .foregroundStyle(.tertiary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, Autumn.spacing.md)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(Autumn.spacing.lg)
    }
}

private struct WorkspaceBucket: Equatable {
    let workspace: String
    var stageCount: Int = 0
    var promptTokens: Int = 0
    var completionTokens: Int = 0
    var durationMS: Double = 0
}

private struct WorkspaceTokenRow: View {
    let bucket: WorkspaceBucket

    var body: some View {
        HStack(spacing: Autumn.spacing.sm) {
            Text(bucket.workspace)
                .font(Autumn.typography.captionStrong)
                .foregroundStyle(workspaceColor)
                .frame(width: 36, alignment: .leading)

            Text("\(bucket.stageCount) 阶段")
                .font(.system(size: 10))
                .foregroundStyle(.tertiary)

            Spacer()

            if bucket.promptTokens > 0 || bucket.completionTokens > 0 {
                Text("↑\(Autumn.format.tokens(bucket.promptTokens)) ↓\(Autumn.format.tokens(bucket.completionTokens))")
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
            if bucket.durationMS > 0 {
                Text(Autumn.format.duration(bucket.durationMS))
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 5)
        .background(
            RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                .fill(workspaceColor.opacity(0.06))
        )
    }

    private var workspaceColor: Color { Autumn.colors.workspace(bucket.workspace) }
}

private struct InspectorStageRow: View {
    let stage: WorkflowStage
    let isLast: Bool

    var body: some View {
        HStack(alignment: .top, spacing: Autumn.spacing.sm) {
            VStack(spacing: 0) {
                Circle()
                    .fill(workspaceColor)
                    .frame(width: 8, height: 8)
                if !isLast {
                    Rectangle()
                        .fill(Color.secondary.opacity(0.18))
                        .frame(width: 1)
                        .frame(maxHeight: .infinity)
                }
            }
            .frame(width: 8)

            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 4) {
                    Text(stage.workspace)
                        .font(.system(size: 10, weight: .bold))
                        .foregroundStyle(workspaceColor)
                    Text(stage.title)
                        .font(Autumn.typography.captionMedium)
                    if let sourceTerr = stage.sourceTerr {
                        AutumnBadge("Terr · \(sourceTerr)", icon: "square.stack.3d.up.fill", tone: .info)
                    }
                }
                Text(stage.detail)
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: Autumn.spacing.xs) {
                    if let d = stage.durationMS {
                        Text(Autumn.format.duration(d))
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.tertiary)
                    }
                    if let p = stage.promptTokens, let c = stage.completionTokens {
                        Text("↑\(Autumn.format.tokens(p)) ↓\(Autumn.format.tokens(c))")
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.tertiary)
                    }
                }
            }
            .padding(.bottom, isLast ? 0 : Autumn.spacing.sm)
        }
    }

    private var workspaceColor: Color { Autumn.colors.workspace(stage.workspace) }
}

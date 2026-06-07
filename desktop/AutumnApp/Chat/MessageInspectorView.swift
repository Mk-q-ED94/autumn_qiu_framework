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
                    Text(formatDuration(total))
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
        }
    }

    private func routePill(_ trace: WorkflowTrace) -> some View {
        let color: Color = {
            switch trace.inputKind {
            case .task: return Autumn.colors.warning
            case .mission: return Autumn.colors.info
            }
        }()
        let text: String = {
            switch trace.inputKind {
            case .task:
                if let kind = trace.taskKind, kind != .general {
                    return "Task · \(kind.title)"
                }
                return "Task"
            case .mission:
                return "Mission · \((trace.routeMode ?? .auto).title)"
            }
        }()
        return HStack(spacing: 4) {
            Image(systemName: trace.inputKind.icon)
                .font(.system(size: 9, weight: .bold))
            Text(text)
                .font(Autumn.typography.captionStrong)
        }
        .foregroundStyle(color)
        .padding(.horizontal, 8)
        .padding(.vertical, 3)
        .background(Capsule().fill(color.opacity(0.14)))
        .overlay(Capsule().strokeBorder(color.opacity(0.30), lineWidth: 0.5))
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
                Text(formatTokens(value))
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
                    Text(tool.title)
                        .font(.system(.caption, design: .monospaced).weight(.semibold))
                    Text(tool.detail)
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(.secondary)
                    if let ms = tool.durationMS {
                        Text(formatDuration(ms))
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
                Text("↑\(formatTokens(bucket.promptTokens)) ↓\(formatTokens(bucket.completionTokens))")
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                    .foregroundStyle(.secondary)
            }
            if bucket.durationMS > 0 {
                Text(formatDuration(bucket.durationMS))
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

    private var workspaceColor: Color {
        switch bucket.workspace {
        case "WP1": return Autumn.colors.accent
        case "WP2": return Autumn.colors.warning
        case "WP3": return Autumn.colors.info
        default:    return Autumn.colors.muted
        }
    }
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
                }
                Text(stage.detail)
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                HStack(spacing: Autumn.spacing.xs) {
                    if let d = stage.durationMS {
                        Text(formatDuration(d))
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.tertiary)
                    }
                    if let p = stage.promptTokens, let c = stage.completionTokens {
                        Text("↑\(formatTokens(p)) ↓\(formatTokens(c))")
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.tertiary)
                    }
                }
            }
            .padding(.bottom, isLast ? 0 : Autumn.spacing.sm)
        }
    }

    private var workspaceColor: Color {
        switch stage.workspace {
        case "WP1": return Autumn.colors.accent
        case "WP2": return Autumn.colors.warning
        case "WP3": return Autumn.colors.info
        default:    return Autumn.colors.muted
        }
    }
}

private func formatDuration(_ ms: Double) -> String {
    if ms >= 1000 { return String(format: "%.1fs", ms / 1000) }
    return "\(Int(ms.rounded()))ms"
}

private func formatTokens(_ count: Int) -> String {
    if count >= 1000 {
        return String(format: "%.1fk", Double(count) / 1000)
    }
    return "\(count)"
}

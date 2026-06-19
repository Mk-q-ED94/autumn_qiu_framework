import SwiftUI

/// Detailed view of the run selected from an assistant message. Each raw stage
/// appears exactly once, grouped by its collaboration responsibility.
struct MessageInspectorView: View {
    let trace: WorkflowTrace?

    var body: some View {
        Group {
            if let trace {
                ScrollView {
                    VStack(alignment: .leading, spacing: Autumn.spacing.lg) {
                        RunHeaderView(trace: trace)
                        WorkspaceBreakdownView(trace: trace)
                        CollaborationFlowView(groups: trace.stageGroups)
                    }
                    .padding(Autumn.spacing.lg)
                }
            } else {
                emptyState
            }
        }
        .background(.regularMaterial)
    }

    private var emptyState: some View {
        VStack(spacing: Autumn.spacing.sm) {
            Image(systemName: "point.3.connected.trianglepath.dotted")
                .font(.system(size: 28))
                .foregroundStyle(.tertiary)
            Text("选择一轮运行")
                .font(Autumn.typography.captionMedium)
                .foregroundStyle(.secondary)
            Text("发送消息，或点击历史回复下方的运行摘要，在这里查看 A1–A4 的协作过程。")
                .font(Autumn.typography.caption)
                .foregroundStyle(.tertiary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, Autumn.spacing.md)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(Autumn.spacing.lg)
    }
}

private struct RunHeaderView: View {
    let trace: WorkflowTrace

    var body: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
            Text("协作运行")
                .font(Autumn.typography.captionStrong)
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
                .tracking(0.5)

            HStack(spacing: Autumn.spacing.sm) {
                AutumnChip(routeText, icon: trace.inputKind.icon, color: routeColor)
                Spacer()
                if let duration = trace.totalDurationMS {
                    Text(Autumn.format.duration(duration))
                        .font(.system(.caption, design: .monospaced).weight(.semibold))
                        .foregroundStyle(.secondary)
                }
            }

            if let prompt = trace.totalPromptTokens,
               let completion = trace.totalCompletionTokens {
                HStack(spacing: Autumn.spacing.md) {
                    TokenStat(label: "输入", value: prompt, icon: "arrow.up")
                    TokenStat(label: "输出", value: completion, icon: "arrow.down")
                    TokenStat(label: "合计", value: prompt + completion, icon: "sum")
                }
            }

            FlowLayout(spacing: Autumn.spacing.xs) {
                AutumnBadge("\(trace.stages.count) 阶段", icon: "list.number", tone: .neutral)
                if trace.agentStageCount > 0 {
                    AutumnBadge("Agent", icon: "cpu", tone: .warning)
                }
                if trace.toolStageCount > 0 {
                    AutumnBadge("\(trace.toolStageCount) 工具", icon: "wrench.and.screwdriver.fill", tone: .info)
                }
                if trace.pushStage != nil {
                    AutumnBadge("4D 推入", icon: "brain", tone: .memory)
                }
                if trace.archiveStage != nil {
                    AutumnBadge("A4 已归档", icon: "archivebox.fill", tone: .memory)
                }
                if !trace.sourceTerrNames.isEmpty {
                    AutumnBadge("\(trace.sourceTerrNames.count) Terr", icon: "square.stack.3d.up.fill", tone: .info)
                }
            }

            if let cost = trace.totalCostUsd, cost > 0 {
                Text(Autumn.format.cost(cost))
                    .font(.system(.caption2, design: .monospaced).weight(.medium))
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var routeText: String {
        switch trace.inputKind {
        case .task:
            if let task = trace.taskKind, task != .general {
                return "Task · \(task.title)"
            }
            return "Task"
        case .mission:
            return "Mission · \((trace.routeMode ?? .auto).title)"
        }
    }

    private var routeColor: Color {
        trace.inputKind == .task ? Autumn.colors.warning : Autumn.colors.info
    }
}

private struct TokenStat: View {
    let label: String
    let value: Int
    let icon: String

    var body: some View {
        HStack(spacing: Autumn.spacing.xs) {
            Image(systemName: icon)
                .font(.caption2.weight(.bold))
                .foregroundStyle(.tertiary)
            VStack(alignment: .leading, spacing: 0) {
                Text(label)
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.tertiary)
                Text(Autumn.format.tokens(value))
                    .font(.system(.caption, design: .monospaced).weight(.semibold))
            }
        }
    }
}

private struct WorkspaceBreakdownView: View {
    let trace: WorkflowTrace

    var body: some View {
        let buckets = workspaceBuckets
        if !buckets.isEmpty {
            VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
                SectionLabel(title: "工作区用量", icon: "chart.bar.xaxis")
                VStack(spacing: Autumn.spacing.xs) {
                    ForEach(buckets) { bucket in
                        WorkspaceTokenRow(bucket: bucket)
                    }
                }
            }
        }
    }

    private var workspaceBuckets: [WorkspaceBucket] {
        var result: [String: WorkspaceBucket] = [:]
        for stage in trace.stages where stage.kind != "tool" && stage.kind != "agent" {
            var bucket = result[stage.workspace] ?? WorkspaceBucket(workspace: stage.workspace)
            bucket.stageCount += 1
            bucket.promptTokens += stage.promptTokens ?? 0
            bucket.completionTokens += stage.completionTokens ?? 0
            bucket.durationMS += stage.durationMS ?? 0
            result[stage.workspace] = bucket
        }
        let order = ["WP1", "WP2", "WP3", "WP4"]
        return result.values.sorted { lhs, rhs in
            (order.firstIndex(of: lhs.workspace) ?? 99) <
                (order.firstIndex(of: rhs.workspace) ?? 99)
        }
    }
}

private struct WorkspaceBucket: Identifiable, Equatable {
    let workspace: String
    var stageCount = 0
    var promptTokens = 0
    var completionTokens = 0
    var durationMS: Double = 0

    var id: String { workspace }
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
                .font(Autumn.typography.caption)
                .foregroundStyle(.tertiary)
            Spacer()
            if bucket.promptTokens > 0 || bucket.completionTokens > 0 {
                Text("↑\(Autumn.format.tokens(bucket.promptTokens)) ↓\(Autumn.format.tokens(bucket.completionTokens))")
                    .font(.system(.caption2, design: .monospaced).weight(.medium))
                    .foregroundStyle(.secondary)
            }
            if bucket.durationMS > 0 {
                Text(Autumn.format.duration(bucket.durationMS))
                    .font(.system(.caption2, design: .monospaced).weight(.medium))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, Autumn.spacing.sm)
        .padding(.vertical, Autumn.spacing.xs)
        .background(
            RoundedRectangle(cornerRadius: Autumn.radius.sm, style: .continuous)
                .fill(workspaceColor.opacity(0.06))
        )
    }

    private var workspaceColor: Color {
        Autumn.colors.workspace(bucket.workspace)
    }
}

private struct CollaborationFlowView: View {
    let groups: [WorkflowStageGroup]

    var body: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
            SectionLabel(title: "协作过程", icon: "point.3.connected.trianglepath.dotted")
            ForEach(groups) { group in
                CollaborationGroupView(group: group)
            }
        }
    }
}

private struct CollaborationGroupView: View {
    let group: WorkflowStageGroup

    var body: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
            HStack(spacing: Autumn.spacing.xs) {
                Image(systemName: group.role.icon)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(roleColor)
                    .frame(width: 18)
                Text(group.role.title)
                    .font(Autumn.typography.captionStrong)
                Spacer()
                Text("\(group.stages.count)")
                    .font(.system(.caption2, design: .monospaced).weight(.semibold))
                    .foregroundStyle(.secondary)
            }

            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(group.stages.enumerated()), id: \.element.id) { index, stage in
                    InspectorStageRow(
                        stage: stage,
                        roleColor: roleColor,
                        isLast: index == group.stages.count - 1
                    )
                }
            }
        }
        .padding(Autumn.spacing.sm)
        .background(
            RoundedRectangle(cornerRadius: Autumn.radius.md, style: .continuous)
                .fill(roleColor.opacity(0.045))
        )
        .overlay(
            RoundedRectangle(cornerRadius: Autumn.radius.md, style: .continuous)
                .strokeBorder(roleColor.opacity(0.14), lineWidth: Autumn.stroke.hairline)
        )
    }

    private var roleColor: Color {
        switch group.role {
        case .memory: return Autumn.colors.memory
        case .orientation, .quality: return Autumn.colors.clay
        case .routing: return Autumn.colors.slate
        case .execution: return Autumn.colors.warning
        }
    }
}

private struct InspectorStageRow: View {
    let stage: WorkflowStage
    let roleColor: Color
    let isLast: Bool

    var body: some View {
        HStack(alignment: .top, spacing: Autumn.spacing.sm) {
            indicator
            VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
                HStack(spacing: Autumn.spacing.xs) {
                    Text(stage.title)
                        .font(stage.kind == "tool" || stage.kind == "agent"
                              ? .system(.caption, design: .monospaced).weight(.semibold)
                              : Autumn.typography.captionMedium)
                    Spacer(minLength: Autumn.spacing.xs)
                    AutumnBadge(stage.statusTitle, tone: statusTone)
                }

                HStack(spacing: Autumn.spacing.xs) {
                    Text(stage.workspace)
                        .font(.system(.caption2, design: .monospaced).weight(.bold))
                        .foregroundStyle(Autumn.colors.workspace(stage.workspace))
                    if let sourceTerr = stage.sourceTerr {
                        AutumnBadge("Terr · \(sourceTerr)", icon: "square.stack.3d.up.fill", tone: .info)
                    }
                }

                Text(stage.detail)
                    .font(stage.kind == "tool"
                          ? .system(.caption2, design: .monospaced)
                          : Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                if !stage.items.isEmpty {
                    VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
                        ForEach(Array(stage.items.enumerated()), id: \.offset) { index, item in
                            HStack(alignment: .firstTextBaseline, spacing: Autumn.spacing.xs) {
                                Text("\(index + 1)")
                                    .font(.system(.caption2, design: .monospaced).weight(.bold))
                                    .foregroundStyle(roleColor)
                                    .frame(width: 16, alignment: .trailing)
                                Text(item)
                                    .font(Autumn.typography.caption)
                                    .foregroundStyle(.primary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                    }
                    .padding(.top, 2)
                }

                metrics
            }
            .padding(.bottom, isLast ? 0 : Autumn.spacing.sm)
        }
    }

    private var indicator: some View {
        VStack(spacing: Autumn.spacing.xs) {
            ZStack {
                Circle()
                    .fill(roleColor.opacity(0.14))
                    .frame(width: 18, height: 18)
                Image(systemName: stage.semanticIcon)
                    .font(.system(size: 8, weight: .bold))
                    .foregroundStyle(stage.status == "failed" ? Autumn.colors.danger : roleColor)
            }
            if !isLast {
                Rectangle()
                    .fill(roleColor.opacity(0.18))
                    .frame(width: Autumn.stroke.hairline)
                    .frame(maxHeight: .infinity)
            }
        }
        .frame(width: 18)
    }

    @ViewBuilder
    private var metrics: some View {
        if stage.durationMS != nil || stage.promptTokens != nil || stage.costUsd != nil {
            HStack(spacing: Autumn.spacing.xs) {
                if let duration = stage.durationMS {
                    Text(Autumn.format.duration(duration))
                }
                if let prompt = stage.promptTokens, let completion = stage.completionTokens {
                    Text("↑\(Autumn.format.tokens(prompt)) ↓\(Autumn.format.tokens(completion))")
                }
                if let cost = stage.costUsd, cost > 0 {
                    Text(Autumn.format.cost(cost))
                }
            }
            .font(.system(.caption2, design: .monospaced))
            .foregroundStyle(.tertiary)
        }
    }

    private var statusTone: AutumnBadge.Tone {
        switch stage.status {
        case "completed": return .success
        case "active": return .info
        case "failed": return .danger
        default: return .neutral
        }
    }
}

private struct SectionLabel: View {
    let title: String
    let icon: String

    var body: some View {
        Label(title, systemImage: icon)
            .font(Autumn.typography.captionStrong)
            .foregroundStyle(.secondary)
            .textCase(.uppercase)
            .tracking(0.5)
    }
}

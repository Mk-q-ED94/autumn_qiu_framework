import SwiftUI

/// Compact trace summary attached below each assistant message. Full stage,
/// token, tool and agent details live in the workspace inspector.
struct WorkflowTraceView: View {
    let trace: WorkflowTrace
    let isSelected: Bool
    let onSelect: () -> Void

    var body: some View {
        Button(action: onSelect) {
            content
        }
        .buttonStyle(.plain)
        .padding(Autumn.spacing.sm)
        .background(cardSurface)
        .overlay(cardBorder)
        .help("在检视面板中查看运行详情")
        .accessibilityLabel("运行摘要，\(routeText)")
        .accessibilityHint("打开检视面板查看阶段、工具调用与用量")
    }

    private var content: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
            header
            PipelineStripView(trace: trace)
        }
        .contentShape(Rectangle())
    }

    private var cardSurface: some View {
        RoundedRectangle(cornerRadius: Autumn.radius.md, style: .continuous)
            .fill(isSelected ? Autumn.colors.clay.opacity(0.055) : Autumn.colors.surfaceElevated)
    }

    private var cardBorder: some View {
        RoundedRectangle(cornerRadius: Autumn.radius.md, style: .continuous)
            .strokeBorder(
                isSelected ? Autumn.colors.clay.opacity(0.38) : Color.secondary.opacity(0.16),
                lineWidth: Autumn.stroke.hairline
            )
    }

    private var header: some View {
        HStack(spacing: Autumn.spacing.sm) {
            AutumnChip(routeText, icon: routeIcon, color: routeColor)
            Spacer(minLength: Autumn.spacing.sm)
            Text(summary)
                .font(.system(size: 10, weight: .medium, design: .monospaced))
                .foregroundStyle(.secondary)
                .lineLimit(1)
            Image(systemName: isSelected ? "sidebar.right" : "chevron.right")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(isSelected ? Autumn.colors.clay : Color.secondary)
        }
    }

    private var routeText: String {
        if trace.hasFailedStage {
            return "失败"
        }
        switch trace.inputKind {
        case .task:
            if let kind = trace.taskKind, kind != .general {
                return "Task · \(kind.title)"
            }
            return "Task"
        case .mission:
            return "Mission · \((trace.routeMode ?? .auto).title)"
        }
    }

    private var routeIcon: String {
        if trace.hasFailedStage { return "exclamationmark.triangle.fill" }
        if trace.isLive { return "bolt.fill" }
        return trace.inputKind.icon
    }

    private var routeColor: Color {
        if trace.hasFailedStage { return Autumn.colors.danger }
        if trace.isLive { return Autumn.colors.info }
        return trace.inputKind == .task ? Autumn.colors.warning : Autumn.colors.info
    }

    private var summary: String {
        var parts: [String] = []
        if trace.pushStage != nil {
            parts.append("4D 推入")
        }
        if trace.archiveStage != nil {
            parts.append("A4 归档")
        }
        if trace.hasAgentActivity {
            parts.append(trace.toolStageCount > 0 ? "Agent · \(trace.toolStageCount) 工具" : "Agent")
        }
        if !trace.sourceTerrNames.isEmpty {
            parts.append("Terr · \(trace.sourceTerrNames.count)")
        }
        if let prompt = trace.totalPromptTokens, let completion = trace.totalCompletionTokens {
            parts.append("↑\(Autumn.format.tokens(prompt)) ↓\(Autumn.format.tokens(completion))")
        }
        if let duration = trace.totalDurationMS {
            parts.append(Autumn.format.duration(duration))
        }
        if let cost = trace.totalCostUsd, cost > 0 {
            parts.append(Autumn.format.cost(cost))
        }
        if parts.isEmpty {
            parts.append("\(trace.completedStageCount)/\(trace.stages.count) 阶段")
        }
        return parts.joined(separator: " · ")
    }
}

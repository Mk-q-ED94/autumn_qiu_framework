import SwiftUI

/// Trace card attached below each assistant message.
///
/// Collapsed layout (default):
///   [Mission · Direct]  ↑1.2k ↓800 · 1.8s              ▼
///   ▰▰▰▰▰  🔧 1                                          (PipelineStripView)
///
/// Expanded layout adds the full ``WorkflowStageRow`` list below.
/// The whole header is one big tap target so the affordance is obvious.
struct WorkflowTraceView: View {
    let trace: WorkflowTrace
    @State private var isExpanded: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
            header

            PipelineStripView(trace: trace)

            if isExpanded {
                Divider()
                    .padding(.top, Autumn.spacing.xs)
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(trace.stages.enumerated()), id: \.element.id) { index, stage in
                        WorkflowStageRow(
                            stage: stage,
                            isLast: index == trace.stages.count - 1
                        )
                    }
                }
                .padding(.top, Autumn.spacing.xs)
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .padding(Autumn.spacing.sm)
        .background(
            RoundedRectangle(cornerRadius: Autumn.radius.md, style: .continuous)
                .fill(.background.opacity(0.6))
        )
        .overlay(
            RoundedRectangle(cornerRadius: Autumn.radius.md, style: .continuous)
                .strokeBorder(Color.secondary.opacity(0.16), lineWidth: Autumn.stroke.hairline)
        )
        .onChange(of: trace.isLive) { _, isLive in
            withAnimation(Autumn.motion.snappy) {
                isExpanded = isLive || trace.hasFailedStage
            }
        }
        .onAppear {
            isExpanded = trace.isLive || trace.hasFailedStage
        }
    }

    private var header: some View {
        HStack(spacing: Autumn.spacing.sm) {
            routePill
            Spacer(minLength: Autumn.spacing.sm)
            Text(summary)
                .font(.system(size: 10, weight: .medium, design: .monospaced))
                .foregroundStyle(.secondary)
                .lineLimit(1)
            Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.tertiary)
        }
        .contentShape(Rectangle())
        .onTapGesture {
            withAnimation(Autumn.motion.snappy) { isExpanded.toggle() }
        }
    }

    private var routePill: some View {
        AutumnChip(routeText, icon: routeIcon, color: routeColor)
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
            let route = trace.routeMode ?? .auto
            return "Mission · \(route.title)"
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
        switch trace.inputKind {
        case .task: return Autumn.colors.warning
        case .mission: return Autumn.colors.info
        }
    }

    private var summary: String {
        var parts: [String] = []
        if trace.hasAgentActivity {
            parts.append(trace.toolStageCount > 0 ? "Agent · \(trace.toolStageCount) 工具" : "Agent")
        }
        if !trace.sourceTerrNames.isEmpty {
            parts.append("Terr · \(trace.sourceTerrNames.count)")
        }
        if let totalPrompt = trace.totalPromptTokens, let totalCompletion = trace.totalCompletionTokens {
            parts.append("↑\(Autumn.format.tokens(totalPrompt)) ↓\(Autumn.format.tokens(totalCompletion))")
        }
        if let total = trace.totalDurationMS {
            parts.append(Autumn.format.duration(total))
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

private struct WorkflowStageRow: View {
    let stage: WorkflowStage
    let isLast: Bool

    private var isTool: Bool { stage.kind == "tool" }
    private var isAgent: Bool { stage.kind == "agent" }
    @State private var pulse = false

    var body: some View {
        HStack(alignment: .top, spacing: Autumn.spacing.sm) {
            indicator

            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: Autumn.spacing.xs) {
                    Text(stage.workspace)
                        .font(Autumn.typography.captionStrong)
                        .foregroundStyle(workspaceColor)
                    Text("·")
                        .foregroundStyle(.tertiary)
                    Text(stage.title)
                        .font(isTool || isAgent
                            ? .system(.caption, design: .monospaced).weight(.medium)
                            : Autumn.typography.captionMedium)
                    if let sourceTerr = stage.sourceTerr {
                        AutumnBadge("Terr · \(sourceTerr)", icon: "square.stack.3d.up.fill", tone: .info)
                    }
                }

                Text(stage.detail)
                    .font(isTool || isAgent
                        ? .system(.caption2, design: .monospaced)
                        : Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: Autumn.spacing.xs) {
                    if let duration = stage.durationMS {
                        Text(Autumn.format.duration(duration))
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.tertiary)
                    }
                    if let prompt = stage.promptTokens, let completion = stage.completionTokens {
                        Text("↑\(Autumn.format.tokens(prompt)) ↓\(Autumn.format.tokens(completion))")
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.tertiary)
                    }
                }
            }
            .padding(.bottom, isLast ? 0 : Autumn.spacing.sm)
        }
        .onAppear {
            if stage.status == "active" {
                withAnimation(Autumn.motion.pulse) { pulse = true }
            }
        }
    }

    private var workspaceColor: Color { Autumn.colors.workspace(stage.workspace) }

    private var indicator: some View {
        VStack(spacing: 2) {
            ZStack {
                if isAgent {
                    Circle()
                        .fill(Autumn.colors.warning.opacity(0.16))
                        .frame(width: 14, height: 14)
                    Image(systemName: "cpu")
                        .font(.system(size: 7, weight: .bold))
                        .foregroundStyle(Autumn.colors.warning)
                } else if isTool {
                    Circle()
                        .fill(Autumn.colors.accent.opacity(0.15))
                        .frame(width: 14, height: 14)
                    Image(systemName: "wrench.and.screwdriver.fill")
                        .font(.system(size: 7, weight: .bold))
                        .foregroundStyle(Autumn.colors.accent)
                } else {
                    Circle()
                        .stroke(indicatorColor.opacity(0.35), lineWidth: 1.2)
                        .frame(width: 14, height: 14)
                    Image(systemName: indicatorIcon)
                        .font(.system(size: 8, weight: .bold))
                        .foregroundStyle(isPending ? indicatorColor : .white)
                        .frame(width: 14, height: 14)
                        .background(Circle().fill(isPending ? Color.clear : indicatorColor))
                        .scaleEffect(stage.status == "active" && pulse ? 1.18 : 1.0)
                        .opacity(stage.status == "active" && pulse ? 0.68 : 1.0)
                }
            }
            if !isLast {
                Rectangle()
                    .fill(Color.secondary.opacity(0.18))
                    .frame(width: 1, height: 26)
            }
        }
    }

    private var isPending: Bool {
        stage.status == "pending"
    }

    private var indicatorIcon: String {
        switch stage.status {
        case "completed": return "checkmark"
        case "active": return "bolt.fill"
        case "failed": return "xmark"
        default: return "circle"
        }
    }

    private var indicatorColor: Color {
        switch stage.status {
        case "completed": return Autumn.colors.success
        case "active": return Autumn.colors.info
        case "failed": return Autumn.colors.danger
        default: return Autumn.colors.muted
        }
    }
}


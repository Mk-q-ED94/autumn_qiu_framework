import SwiftUI

struct WorkflowTraceView: View {
    let trace: WorkflowTrace
    @State private var isExpanded: Bool = false
    @State private var liveBlink: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.sm) {
            header

            if isExpanded {
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
        .task(id: trace.isLive) {
            guard trace.isLive else {
                liveBlink = false
                return
            }
            withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) {
                liveBlink.toggle()
            }
        }
    }

    @ViewBuilder
    private var header: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.xs) {
            HStack(spacing: Autumn.spacing.sm) {
                AutumnBadge(statusTitle, icon: statusIcon, tone: statusTone)
                AutumnBadge(inputTitle, icon: inputIcon, tone: trace.isLive ? .info : .accent)
                if let taskTitle = taskTypeTitle {
                    AutumnBadge(taskTitle, tone: .accent)
                }
                if let routeTitle {
                    AutumnBadge(routeTitle, tone: .neutral)
                }
                Spacer()
                Button {
                    withAnimation(Autumn.motion.snappy) { isExpanded.toggle() }
                } label: {
                    Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }

            HStack(spacing: Autumn.spacing.sm) {
                TraceProgressMeter(
                    completed: trace.completedStageCount,
                    total: trace.stages.count,
                    tone: statusColor
                )
                if trace.isLive, let live = liveStage {
                    liveStatusLine(live)
                } else {
                    Text(summary)
                        .font(Autumn.typography.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Spacer()
            }
        }
        .contentShape(Rectangle())
        .onTapGesture {
            // The whole header is clickable to expand/collapse — clearer affordance
            // than the small chevron alone.
            withAnimation(Autumn.motion.snappy) { isExpanded.toggle() }
        }
    }

    @ViewBuilder
    private func liveStatusLine(_ stage: WorkflowStage) -> some View {
        HStack(spacing: Autumn.spacing.xs) {
            Circle()
                .fill(Autumn.colors.info)
                .frame(width: 6, height: 6)
                .opacity(liveBlink ? 0.35 : 1.0)
            Text("\(stage.workspace) · \(stage.title)")
                .font(Autumn.typography.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
    }

    /// The first stage with `status == "active"` — what we surface in the collapsed live header.
    private var liveStage: WorkflowStage? {
        trace.stages.first { $0.status == "active" }
    }

    private var inputTitle: String {
        trace.inputKind == .mission ? "Mission" : "Task"
    }

    private var inputIcon: String {
        trace.inputKind.icon
    }

    private var taskTypeTitle: String? {
        guard trace.inputKind == .task, let taskKind = trace.taskKind, taskKind != .general else { return nil }
        return taskKind.title
    }

    private var routeTitle: String? {
        if let route = trace.routeMode { return route.title }
        return trace.inputKind == .task ? nil : MissionRouteMode.auto.title
    }

    private var summary: String {
        var parts = ["\(trace.stages.count) 阶段"]
        if trace.toolStageCount > 0 {
            parts.append("\(trace.toolStageCount) 工具")
        }
        if let total = trace.totalDurationMS {
            parts.append(formatDuration(total))
        }
        if let totalPrompt = trace.totalPromptTokens, let totalCompletion = trace.totalCompletionTokens {
            parts.append("↑\(formatTokens(totalPrompt)) ↓\(formatTokens(totalCompletion))")
        }
        return parts.joined(separator: " · ")
    }

    private var statusTitle: String {
        if trace.hasFailedStage { return "失败" }
        if trace.isLive { return "运行中" }
        return "已同步"
    }

    private var statusIcon: String {
        if trace.hasFailedStage { return "xmark.circle.fill" }
        if trace.isLive { return "bolt.fill" }
        return "checkmark.seal.fill"
    }

    private var statusTone: AutumnBadge.Tone {
        if trace.hasFailedStage { return .danger }
        return trace.isLive ? .info : .success
    }

    private var statusColor: Color {
        if trace.hasFailedStage { return Autumn.colors.danger }
        return trace.isLive ? Autumn.colors.info : Autumn.colors.success
    }
}

private struct TraceProgressMeter: View {
    let completed: Int
    let total: Int
    let tone: Color

    var body: some View {
        GeometryReader { proxy in
            let width = proxy.size.width
            ZStack(alignment: .leading) {
                Capsule(style: .continuous)
                    .fill(Color.secondary.opacity(0.14))
                Capsule(style: .continuous)
                    .fill(tone.opacity(0.78))
                    .frame(width: progressWidth(totalWidth: width))
            }
        }
        .frame(width: 54, height: 4)
        .accessibilityLabel("\(completed)/\(max(total, 1))")
    }

    private func progressWidth(totalWidth: CGFloat) -> CGFloat {
        guard total > 0 else { return 0 }
        let ratio = min(max(Double(completed) / Double(total), 0), 1)
        return max(4, totalWidth * CGFloat(ratio))
    }
}

private struct WorkflowStageRow: View {
    let stage: WorkflowStage
    let isLast: Bool

    private var isTool: Bool { stage.kind == "tool" }
    @State private var pulse = false

    var body: some View {
        HStack(alignment: .top, spacing: Autumn.spacing.sm) {
            indicator

            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: Autumn.spacing.xs) {
                    Text(stage.workspace)
                        .font(Autumn.typography.captionStrong)
                        .foregroundStyle(.tint)
                    Text("·")
                        .foregroundStyle(.tertiary)
                    Text(stage.title)
                        .font(isTool
                            ? .system(.caption, design: .monospaced).weight(.medium)
                            : Autumn.typography.captionMedium)
                }

                Text(stage.detail)
                    .font(isTool
                        ? .system(.caption2, design: .monospaced)
                        : Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: Autumn.spacing.xs) {
                    if let duration = stage.durationMS {
                        Text(formatDuration(duration))
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(.tertiary)
                    }
                    if let prompt = stage.promptTokens, let completion = stage.completionTokens {
                        Text("↑\(formatTokens(prompt)) ↓\(formatTokens(completion))")
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

    private var indicator: some View {
        VStack(spacing: 2) {
            ZStack {
                if isTool {
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

    private var isCompleted: Bool {
        stage.status == "completed"
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

private func formatDuration(_ ms: Double) -> String {
    if ms >= 1000 {
        return String(format: "%.1fs", ms / 1000)
    }
    return "\(Int(ms.rounded()))ms"
}

/// Compact token formatter: 1240 → "1.2k", 980 → "980".
private func formatTokens(_ count: Int) -> String {
    if count >= 1000 {
        let k = Double(count) / 1000
        return String(format: "%.1fk", k)
    }
    return "\(count)"
}

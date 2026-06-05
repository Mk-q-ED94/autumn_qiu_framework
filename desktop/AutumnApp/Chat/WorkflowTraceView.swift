import SwiftUI

struct WorkflowTraceView: View {
    let trace: WorkflowTrace
    @State private var isExpanded: Bool = true

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
    }

    private var header: some View {
        HStack(spacing: Autumn.spacing.sm) {
            AutumnBadge(inputTitle, icon: inputIcon, tone: .accent)
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
    }

    private var inputTitle: String {
        trace.inputType == "mission" ? "Mission" : "Task"
    }

    private var inputIcon: String {
        trace.inputType == "mission" ? "arrow.triangle.branch" : "checklist"
    }

    private var routeTitle: String? {
        switch trace.route {
        case "direct": return "直接回答"
        case "convert": return "转为任务"
        case "auto": return "自动路由"
        case nil: return trace.inputType == "task" ? nil : "自动路由"
        default: return trace.route
        }
    }
}

private struct WorkflowStageRow: View {
    let stage: WorkflowStage
    let isLast: Bool

    private var isTool: Bool { stage.kind == "tool" }

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
            }
            .padding(.bottom, isLast ? 0 : Autumn.spacing.sm)
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
                        .stroke(Color.secondary.opacity(0.25), lineWidth: 1.2)
                        .frame(width: 14, height: 14)
                    if isCompleted {
                        Image(systemName: "checkmark")
                            .font(.system(size: 8, weight: .bold))
                            .foregroundStyle(.white)
                            .frame(width: 14, height: 14)
                            .background(Circle().fill(Autumn.colors.success))
                    }
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
}

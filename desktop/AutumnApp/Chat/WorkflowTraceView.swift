import SwiftUI

struct WorkflowTraceView: View {
    let trace: WorkflowTrace

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Divider()

            HStack(spacing: 8) {
                Label(inputTitle, systemImage: inputIcon)
                    .font(.caption.weight(.semibold))

                if let routeTitle {
                    Text(routeTitle)
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                }
            }

            VStack(alignment: .leading, spacing: 0) {
                ForEach(Array(trace.stages.enumerated()), id: \.element.id) { index, stage in
                    WorkflowStageRow(stage: stage, isLast: index == trace.stages.count - 1)
                }
            }
        }
        .foregroundStyle(.primary)
    }

    private var inputTitle: String {
        trace.inputType == "mission" ? "Mission 协作路径" : "Task 协作路径"
    }

    private var inputIcon: String {
        trace.inputType == "mission" ? "arrow.triangle.branch" : "checklist"
    }

    private var routeTitle: String? {
        switch trace.route {
        case "direct": return "直接回答"
        case "convert": return "转换为任务"
        case nil: return trace.inputType == "task" ? nil : "自动路由"
        default: return trace.route
        }
    }
}

private struct WorkflowStageRow: View {
    let stage: WorkflowStage
    let isLast: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            VStack(spacing: 3) {
                Image(systemName: iconName)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(iconColor)
                    .frame(width: 14, height: 14)

                if !isLast {
                    Rectangle()
                        .fill(.secondary.opacity(0.28))
                        .frame(width: 1, height: 20)
                }
            }

            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(stage.workspace)
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.tint)
                    Text(stage.title)
                        .font(.caption.weight(.medium))
                }

                Text(stage.detail)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(.bottom, isLast ? 0 : 8)
        }
    }

    private var iconName: String {
        stage.status == "completed" ? "checkmark.circle.fill" : "circle"
    }

    private var iconColor: Color {
        stage.status == "completed" ? .green : .secondary
    }
}

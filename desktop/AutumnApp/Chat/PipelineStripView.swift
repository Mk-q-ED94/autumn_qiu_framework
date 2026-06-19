import SwiftUI

/// A compact, glanceable timeline that maps each ``WorkflowStage`` to a
/// colour-coded capsule:
///
///   ▰  WP1 select  →  ▰  WP3 route  →  ▰  WP3 direct  →  ▰  WP1 final
///
/// Workspace colour mapping (the visual language of the redesign):
///   - WP1  →  accent  (the brand colour, anchoring start + end)
///   - WP2  →  orange  (action / execution)
///   - WP3  →  blue    (routing / exploration)
///
/// Status semantics:
///   - completed  →  full-fill capsule
///   - active     →  pulsing capsule (live ring around the dot)
///   - pending    →  hairline outline only
///   - failed     →  red fill + ✕ glyph
///
    /// Agent handoff and tool calls are surfaced as compact chips so the user can
    /// tell when WP2 switched from plain completion to agentic execution.
struct PipelineStripView: View {
    let trace: WorkflowTrace

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var pulse = false
    @State private var hoveredStageID: String?

    var body: some View {
        HStack(spacing: 4) {
            ForEach(pipelineStages) { stage in
                StageCapsule(
                    stage: stage,
                    isHovered: hoveredStageID == stage.id,
                    isPulsing: pulse && stage.status == "active"
                )
                .onHover { hovering in
                    hoveredStageID = hovering ? stage.id : nil
                }
                .help(tooltipText(for: stage))
            }
            if trace.pushStage != nil {
                PushStatusChip()
            }
            if trace.archiveStage != nil {
                ArchiveStatusChip()
            }
            if agentCount > 0 {
                AgentStatusChip()
            }
            if toolCount > 0 {
                ToolCountChip(count: toolCount)
            }
        }
        .task(id: trace.isLive) {
            guard trace.isLive else {
                pulse = false
                return
            }
            guard !reduceMotion else { return }
            withAnimation(Autumn.motion.pulse) {
                pulse.toggle()
            }
        }
    }

    private var pipelineStages: [WorkflowStage] {
        trace.stages.filter(\.isPrimaryPipelineStage)
    }

    private var toolCount: Int {
        trace.stages.filter { $0.kind == "tool" }.count
    }

    private var agentCount: Int {
        trace.stages.filter { $0.kind == "agent" }.count
    }

    private func tooltipText(for stage: WorkflowStage) -> String {
        var parts = ["\(stage.workspace) · \(stage.title)"]
        if let ms = stage.durationMS {
            parts.append(Autumn.format.duration(ms))
        }
        if let prompt = stage.promptTokens, let completion = stage.completionTokens {
            parts.append("↑\(Autumn.format.tokens(prompt)) ↓\(Autumn.format.tokens(completion))")
        }
        if let sourceTerr = stage.sourceTerr {
            parts.append("Terr: \(sourceTerr)")
        }
        return parts.joined(separator: " · ")
    }
}

private struct StageCapsule: View {
    let stage: WorkflowStage
    let isHovered: Bool
    let isPulsing: Bool

    var body: some View {
        ZStack {
            base
            if stage.status == "failed" {
                Image(systemName: "xmark")
                    .font(.system(size: 6, weight: .black))
                    .foregroundStyle(.white)
            }
        }
        .frame(width: width, height: 6)
        .scaleEffect(isHovered ? 1.18 : 1.0, anchor: .center)
        .animation(Autumn.motion.snappy, value: isHovered)
    }

    @ViewBuilder
    private var base: some View {
        let shape = Capsule(style: .continuous)
        switch stage.status {
        case "completed":
            shape.fill(workspaceColor)
        case "active":
            shape.fill(workspaceColor.opacity(isPulsing ? 0.55 : 1.0))
        case "failed":
            shape.fill(Autumn.colors.danger)
        default:
            shape
                .strokeBorder(workspaceColor.opacity(0.5), lineWidth: 1)
        }
    }

    private var width: CGFloat {
        // The first/last WP1 segments anchor the strip; route/convert mid-stages
        // get slightly shorter capsules so the visual rhythm reads end-to-end.
        if stage.isPipelineAnchor {
            return 22
        }
        return 16
    }

    private var workspaceColor: Color { Autumn.colors.workspace(stage.workspace) }
}

private struct ToolCountChip: View {
    let count: Int

    var body: some View {
        AutumnChip("\(count)", icon: "wrench.and.screwdriver.fill", color: Autumn.colors.accent, size: .compact)
    }
}

private struct AgentStatusChip: View {
    var body: some View {
        AutumnChip("Agent", icon: "cpu", color: Autumn.colors.warning, size: .compact)
    }
}

private struct PushStatusChip: View {
    var body: some View {
        AutumnChip("4D", icon: "brain", color: Autumn.colors.memory, size: .compact)
    }
}

private struct ArchiveStatusChip: View {
    var body: some View {
        AutumnChip("归档", icon: "archivebox.fill", color: Autumn.colors.memory, size: .compact)
    }
}

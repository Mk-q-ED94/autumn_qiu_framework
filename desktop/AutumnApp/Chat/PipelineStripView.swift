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
/// Tool calls (``stage.kind == "tool"``) are aggregated into a single trailing
/// 🔧 chip rather than inflating the strip — the user cares that tools ran,
/// not which order WP2 invoked them in.
struct PipelineStripView: View {
    let trace: WorkflowTrace

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
            if toolCount > 0 {
                ToolCountChip(count: toolCount)
            }
        }
        .task(id: trace.isLive) {
            guard trace.isLive else {
                pulse = false
                return
            }
            withAnimation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true)) {
                pulse.toggle()
            }
        }
    }

    private var pipelineStages: [WorkflowStage] {
        trace.stages.filter { $0.kind != "tool" }
    }

    private var toolCount: Int {
        trace.stages.filter { $0.kind == "tool" }.count
    }

    private func tooltipText(for stage: WorkflowStage) -> String {
        var parts = ["\(stage.workspace) · \(stage.title)"]
        if let ms = stage.durationMS {
            parts.append(formatDuration(ms))
        }
        if let prompt = stage.promptTokens, let completion = stage.completionTokens {
            parts.append("↑\(formatTokens(prompt)) ↓\(formatTokens(completion))")
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
        if stage.id.hasSuffix(".select") || stage.id.hasSuffix(".final_check") {
            return 22
        }
        return 16
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

private struct ToolCountChip: View {
    let count: Int

    var body: some View {
        HStack(spacing: 2) {
            Image(systemName: "wrench.and.screwdriver.fill")
                .font(.system(size: 7, weight: .bold))
            Text("\(count)")
                .font(.system(size: 9, weight: .semibold, design: .monospaced))
        }
        .foregroundStyle(Autumn.colors.accent)
        .padding(.horizontal, 5)
        .padding(.vertical, 1)
        .background(
            Capsule().fill(Autumn.colors.accent.opacity(0.12))
        )
        .overlay(
            Capsule().strokeBorder(Autumn.colors.accent.opacity(0.25), lineWidth: 0.5)
        )
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

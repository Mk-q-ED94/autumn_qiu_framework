import SwiftUI

struct SidebarView: View {
    @Binding var selection: String
    @Binding var selectedConversationID: UUID?

    var body: some View {
        VStack(spacing: 0) {
            sidebarHeader

            VStack(spacing: Qcowork.spacing.xs) {
                ForEach(AppSection.allCases) { section in
                    QcoworkNavItem(
                        section: section,
                        isSelected: selection == section.rawValue,
                        action: { selection = section.rawValue }
                    )
                }
            }
            .padding(.horizontal, Qcowork.spacing.sm)
            .padding(.bottom, Qcowork.spacing.sm)

            Rectangle()
                .fill(Color.primary.opacity(0.08))
                .frame(height: Qcowork.stroke.hairline)

            if selection == AppSection.workspace.rawValue {
                ProjectSidebarView(selectedConversationID: $selectedConversationID)
            } else {
                Spacer()
            }

            AgentStatusFooter()
        }
        .background(Qcowork.colors.sidebar)
    }

    private var sidebarHeader: some View {
        HStack(spacing: Qcowork.spacing.sm) {
            QcoworkLogoMark(size: 24)
            VStack(alignment: .leading, spacing: 1) {
                Text("Qcowork")
                    .font(Qcowork.typography.headline)
                Text("多模型协作工作台")
                    .font(Qcowork.typography.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(.horizontal, Qcowork.spacing.md)
        .padding(.top, Qcowork.spacing.md)
        .padding(.bottom, Qcowork.spacing.sm)
    }
}

// MARK: - Agent status footer

/// Pinned to the bottom of the sidebar — surfaces the four agent slots at a
/// glance so the user doesn't have to navigate into Settings to learn that A2
/// just failed.
///
///   [A1•] [A2•] [A3•] [A4•]         ⚙
///
/// Dot colour:  ready=green · connecting=orange · failed=red · unconfigured=gray
/// Click any dot or the gear to jump to Settings.
private struct AgentStatusFooter: View {
    @EnvironmentObject private var settings: AppSettings
    @Environment(\.openSettings) private var openSettings

    var body: some View {
        HStack(spacing: Qcowork.spacing.xs) {
            ForEach(AgentSlotID.allCases) { slot in
                AgentDot(
                    label: slot.label,
                    state: state(for: slot),
                    tooltip: tooltip(for: slot)
                )
                .onTapGesture { openSettings() }
            }
            Spacer()
            Button(action: { openSettings() }) {
                Image(systemName: "gearshape.fill")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
            .help("打开设置")
        }
        .padding(.horizontal, Qcowork.spacing.md)
        .padding(.vertical, Qcowork.spacing.sm)
        .background(Color.primary.opacity(0.04))
        .overlay(
            Rectangle()
                .fill(Color.primary.opacity(0.1))
                .frame(height: Qcowork.stroke.hairline),
            alignment: .top
        )
    }

    private func state(for slot: AgentSlotID) -> ModelConnectionState {
        switch slot {
        case .a1: return settings.modelState(for: .a1)
        case .a2: return settings.modelState(for: .a2)
        case .a3: return settings.modelState(for: .a3)
        case .a4:
            if !settings.a4Enabled { return .unconfigured }
            let hasURL = !settings.a4BaseURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            return hasURL ? .ready : .unconfigured
        }
    }

    private func tooltip(for slot: AgentSlotID) -> String {
        let s = state(for: slot)
        let role: String
        switch slot {
        case .a1: role = "A1 · 路由与总检"
        case .a2: role = "A2 · 任务执行"
        case .a3: role = "A3 · Mission 与转换"
        case .a4: role = "A4 · 记忆模型（可选）"
        }
        return "\(role)\n\(s.title)"
    }
}

private enum AgentSlotID: String, CaseIterable, Identifiable {
    case a1, a2, a3, a4

    var id: String { rawValue }
    var label: String { rawValue.uppercased() }
}

private struct AgentDot: View {
    let label: String
    let state: ModelConnectionState
    let tooltip: String
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var pulse = false

    var body: some View {
        HStack(spacing: 3) {
            ZStack {
                Circle()
                    .fill(dotColor)
                    .frame(width: 7, height: 7)
                if state == .connecting {
                    Circle()
                        .stroke(dotColor.opacity(pulse ? 0.0 : 0.5), lineWidth: 1.5)
                        .frame(width: 11, height: 11)
                }
            }
            .frame(width: 11, height: 11)
            Text(label)
                .font(.system(size: 9, weight: .semibold, design: .monospaced))
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 5)
        .padding(.vertical, 2)
        .background(
            Capsule().fill(Color.secondary.opacity(0.08))
        )
        .help(tooltip)
        .task(id: state) {
            guard state == .connecting else { pulse = false; return }
            guard !reduceMotion else { return }
            withAnimation(Qcowork.motion.pulse) {
                pulse.toggle()
            }
        }
    }

    private var dotColor: Color {
        switch state {
        case .ready:        return Qcowork.colors.success
        case .connecting:   return Qcowork.colors.warning
        case .failed:       return Qcowork.colors.danger
        case .unconfigured: return Qcowork.colors.muted
        }
    }
}

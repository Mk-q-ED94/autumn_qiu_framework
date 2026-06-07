import SwiftUI

/// Horizontal strip directly above the composer that surfaces the resolved
/// intent for the *next* turn — the model + route the next ⌘↩ will use.
///
///   [📋 Task · 代码 ▾]   85%   ▸ 看起来像写代码的请求
///
/// Tapping the pill opens an override popover; setting an override locks the
/// pill (🔒) until the user clears it. Low-confidence previews tint the bar
/// warning so the user notices the system isn't sure.
struct ComposerIntentBar: View {
    let preview: IntentPreview?
    let inputKind: WorkflowInputKind?
    let taskKind: WorkflowTaskKind?
    let routeOverride: MissionRouteMode?
    let inputOverride: WorkflowInputKind?
    let taskOverride: WorkflowTaskKind?
    let effectiveRoute: MissionRouteMode
    let isLoading: Bool
    let hasInput: Bool

    let setInput: (WorkflowInputKind) -> Void
    let setTask: (WorkflowTaskKind) -> Void
    let setRoute: (MissionRouteMode?) -> Void
    let clearOverrides: () -> Void

    @State private var popoverVisible: Bool = false

    var body: some View {
        HStack(spacing: Autumn.spacing.sm) {
            pillButton

            if let confidence = preview?.confidence, hasInput {
                ConfidenceChip(value: confidence)
            }

            Spacer(minLength: Autumn.spacing.xs)

            Text(reasoningText)
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.tail)

            if hasOverride {
                Button(action: clearOverrides) {
                    Image(systemName: "arrow.uturn.backward")
                        .font(.system(size: 9, weight: .semibold))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 3)
                        .background(
                            Capsule().fill(Color.secondary.opacity(0.10))
                        )
                }
                .buttonStyle(.plain)
                .help("清除手动覆盖，恢复自动判定")
            }
        }
        .padding(.horizontal, Autumn.spacing.md)
        .padding(.vertical, 6)
        .background(barBackground)
        .overlay(
            Rectangle()
                .fill(Color.secondary.opacity(0.10))
                .frame(height: Autumn.stroke.hairline),
            alignment: .top
        )
    }

    private var pillButton: some View {
        Button {
            popoverVisible.toggle()
        } label: {
            HStack(spacing: 5) {
                Image(systemName: pillIcon)
                    .font(.system(size: 10, weight: .bold))
                Text(pillLabel)
                    .font(Autumn.typography.captionStrong)
                if hasOverride {
                    Image(systemName: "lock.fill")
                        .font(.system(size: 8, weight: .bold))
                }
                if isLoading {
                    ProgressView()
                        .controlSize(.mini)
                        .scaleEffect(0.7)
                } else {
                    Image(systemName: "chevron.down")
                        .font(.system(size: 8, weight: .bold))
                }
            }
            .foregroundStyle(pillColor)
            .padding(.horizontal, 9)
            .padding(.vertical, 4)
            .background(
                Capsule().fill(pillColor.opacity(0.14))
            )
            .overlay(
                Capsule().strokeBorder(pillColor.opacity(0.32), lineWidth: 0.5)
            )
        }
        .buttonStyle(.plain)
        .popover(isPresented: $popoverVisible, arrowEdge: .bottom) {
            ComposerIntentPopover(
                selectedInput: inputKind ?? .mission,
                selectedTask: taskKind ?? .general,
                routeOverride: routeOverride,
                reasoning: preview?.reasoning,
                confidence: preview?.confidence,
                setInput: setInput,
                setTask: setTask,
                setRoute: setRoute
            )
        }
    }

    // ── pill style ────────────────────────────────────────────────────────────

    private var pillIcon: String {
        if !hasInput && preview == nil {
            return "wand.and.stars"
        }
        guard let kind = inputKind else { return "wand.and.stars" }
        return kind.icon
    }

    private var pillLabel: String {
        if !hasInput && preview == nil {
            return "自动模式"
        }
        guard let kind = inputKind else { return "自动模式" }
        switch kind {
        case .task:
            return "Task · \(taskKind?.title ?? "通用")"
        case .mission:
            return "Mission · \(effectiveRoute.title)"
        }
    }

    private var pillColor: Color {
        if let confidence = preview?.confidence, hasInput, confidence < 0.7 {
            return Autumn.colors.warning
        }
        switch inputKind {
        case .task:    return Autumn.colors.warning
        case .mission: return Autumn.colors.info
        case .none:    return Autumn.colors.accent
        }
    }

    private var hasOverride: Bool {
        inputOverride != nil || taskOverride != nil || routeOverride != nil
    }

    private var reasoningText: String {
        if isLoading { return "检测中…" }
        if !hasInput { return "输入消息后将自动检测意图" }
        if let reasoning = preview?.reasoning, !reasoning.isEmpty { return reasoning }
        if hasOverride { return "已锁定为手动选择" }
        return "等待 A1 判定…"
    }

    private var barBackground: AnyShapeStyle {
        if let confidence = preview?.confidence, hasInput, confidence < 0.7 {
            return AnyShapeStyle(Autumn.colors.warning.opacity(0.06))
        }
        return AnyShapeStyle(Material.bar)
    }
}

private struct ConfidenceChip: View {
    let value: Double

    var body: some View {
        let percent = Int((value * 100).rounded())
        return Text("\(percent)%")
            .font(.system(size: 9, weight: .semibold, design: .monospaced))
            .foregroundStyle(color)
            .padding(.horizontal, 5)
            .padding(.vertical, 2)
            .background(
                Capsule().fill(color.opacity(0.10))
            )
    }

    private var color: Color {
        if value < 0.5 { return Autumn.colors.danger }
        if value < 0.7 { return Autumn.colors.warning }
        return Autumn.colors.success
    }
}

private struct ComposerIntentPopover: View {
    let selectedInput: WorkflowInputKind
    let selectedTask: WorkflowTaskKind
    let routeOverride: MissionRouteMode?
    let reasoning: String?
    let confidence: Double?

    let setInput: (WorkflowInputKind) -> Void
    let setTask: (WorkflowTaskKind) -> Void
    let setRoute: (MissionRouteMode?) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Autumn.spacing.md) {
            HStack(alignment: .firstTextBaseline) {
                Text("本次意图")
                    .font(Autumn.typography.headline)
                Spacer()
                if let confidence {
                    Text(String(format: "A1 置信 %.0f%%", confidence * 100))
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .foregroundStyle(confidence < 0.7 ? Autumn.colors.warning : .secondary)
                }
            }

            if let reasoning, !reasoning.isEmpty {
                Text(reasoning)
                    .font(Autumn.typography.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Picker("输入类型", selection: inputBinding) {
                ForEach(WorkflowInputKind.allCases) { kind in
                    Text(kind.title).tag(kind)
                }
            }
            .pickerStyle(.segmented)

            if selectedInput == .task {
                Picker("任务种类", selection: taskBinding) {
                    ForEach(WorkflowTaskKind.allCases) { kind in
                        Text(kind.title).tag(kind)
                    }
                }
            } else {
                Picker("Mission 路由", selection: routeBinding) {
                    Text("跟随默认").tag("__default__")
                    ForEach(MissionRouteMode.allCases) { route in
                        Text(route.title).tag(route.rawValue)
                    }
                }
            }
        }
        .padding(Autumn.spacing.lg)
        .frame(width: 300)
    }

    private var inputBinding: Binding<WorkflowInputKind> {
        Binding(get: { selectedInput }, set: setInput)
    }

    private var taskBinding: Binding<WorkflowTaskKind> {
        Binding(get: { selectedTask }, set: setTask)
    }

    private var routeBinding: Binding<String> {
        Binding(
            get: { routeOverride?.rawValue ?? "__default__" },
            set: { value in
                setRoute(value == "__default__" ? nil : MissionRouteMode(rawValue: value))
            }
        )
    }
}
